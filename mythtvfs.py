# mythtvfs.py - Fuse filesystem for MythTV
# Copyright (C) 2013  Toby Gray <toby.gray@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import os
import sys
import stat
import datetime
import time
import errno
import fuse
import MythTV
import traceback
import logging

# Let fuse know what API we are expecting
fuse.fuse_python_api = (0, 2)

VERSION = 0.1
""" Version of pymythtvfs. """

DIR_SEP = '/'
""" Directory separator character. """

CACHE_TIME = 30
"""
Minimum time period in seconds between asking the backend for the
latest list of recordings.
"""

def logAllExceptions(function):
    """
    Simple Python decorator to log exceptions
    """
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except:
            stackText = traceback.format_exc()
            logging.error("Uncaught exception: %s", stackText)
            raise
    return wrapper

class MissingOptionException(Exception):
    """ Exception used to indicate a missing mount option. """
    def __init__(self, missing):
        """
        Creates a new exception indicating that the mount option with
        the name of missing is required to be present.
        """
        self.missing = missing

class FileBase(object):
    """
    Represents a file or a directory in the file system.
    """
    def __init__(self, fs):
        self._fs = fs
        self._is_dir = False
        self._atime = 0
        self._mtime = 0
        self._ctime = 0
        self._size = 0
    
    @logAllExceptions
    def getattr(self):
        """ Returns the stat results for this file. """
        return StatResult(
            fs = self._fs,
            dir = self._is_dir,
            atime = self._atime,
            ctime = self._ctime,
            mtime = self._mtime,
            size = self._size)
        
    def resolve(self, path):
        """ Resolves the given path into a FileBase object """
        cwd = self
        for d in path.rstrip(DIR_SEP).split(DIR_SEP):
            if d != "":
                cwd = cwd[d]
        return cwd

    @logAllExceptions
    def unlink(self):
        """ Remove this file """
        return -errno.ENOSYS
        
    def _clean_name(self, name):
        ret = name
        for c in self._fs.invalid_chars_list:
            ret = ret.replace(c, self._fs.replacement_char)
        return ret

class File(FileBase):
    """ Represents a file in the file system. """
    def __init__(self, fs):
        super(File, self).__init__(fs)
        self._is_dir = False

def datetimeToInt(dt):
    """ Transform a datetime object into seconds since the unix epoch. """
    return time.mktime(dt.timetuple())
    
class Recording(File):
    """ Represents a file in the file system which is a recording. """
    def __init__(self, fs, recording):
        super(Recording, self).__init__(fs)
        self._recording = recording
        self._size = recording['filesize']
        self._ctime = datetimeToInt(recording['recstartts'])
        self._mtime = datetimeToInt(recording['recendts'])
        self._atime = self._mtime
        self._dupIdx = 0
        
    def _getFilePath(self):
        """ Returns the full path of this file. """
        basename = unicode(self._fs.format_string).format(**self._recording)
        if self._dupIdx > 0:
            basename += u" (%d)" % self._dupIdx
        name = self._recording.formatPath(basename).encode('UTF-8')
        return self._clean_name(name)
        
    def getSplitPath(self):
        """ Returns a pre-split path list for this file """
        return os.path.split(self._getFilePath())
    
    def getBaseName(self):
        """ Returns the basename of this file. """
        return os.path.basename(self._getFilePath())
                
    def open(self):
        """ Returns an open file handle for the contents of this file. """
        return self._recording.open()
        
    def incrementDeDup(self):
        """ Increments the duplicate filename index"""
        self._dupIdx += 1

    def unlink(self):
        if not self._fs.allow_delete:
            return -errno.EPERM
        try:
            self._recording.delete()
            # Tell the parent to rescan
            self._fs.invalidateCache()
            return 0
        except:
            stackText = traceback.format_exc()
            logging.debug("Exception in deleting: %s", stackText)
            return -errno.EBADF

class Directory(FileBase):
    """ Represents a directory in the file system. """
    def __init__(self, fs, basename):
        super(Directory, self).__init__(fs)
        self._basename = basename
        self._contents = {}
        self._is_dir = True
    
    def __getitem__(self, key):
        """ Returns a FileBase with the name given by key. """
        return self._contents[key]
        
    def getBaseName(self):
        """ Returns the basename of this file. """
        return self._basename
        
    def readdir(self):
        """ Returns a list of files in this directory. """
        return self._contents.values()

    def unlink(self):
        if not self._fs.allow_delete:
            return -errno.EPERM
        # TODO need to remove from parent
        return 0

class Root(Directory):
    """ Represents the root directory of the file system "/". """
    @logAllExceptions
    def __init__(self, fs):
        super(Root, self).__init__(fs, "")
        for r in self._fs.be.getRecordings():
            rf = Recording(self._fs, r)
            currentDir = self
            splitPath = rf.getSplitPath()
            # Find the right subdirectory to place it in
            while len(splitPath) > 1:
                dirName = splitPath[0]
                splitPath = splitPath[1:]
                try:
                    # Try to place it in a pre-existing directory
                    currentDir = currentDir._contents[dirName]
                except KeyError:
                    # No pre-existing directory, create a new one
                    newDir = Directory(self._fs, dirName)
                    currentDir._contents[dirName] = newDir
                    currentDir = newDir
            # Walked through all the directories, so time to place it
            # Make sure the name is unique
            while rf.getBaseName() in currentDir._contents.keys():
                rf.incrementDeDup()
            currentDir._contents[rf.getBaseName()] = rf

class FileHandle(object):
    """ Handle representing an open recording file. """
    @logAllExceptions
    def __init__(self, fs, path, flags, *mode):
        self._fs = fs
        self._file = fs.getRoot().resolve(path)
        self._fh = self._file.open()
    
    @logAllExceptions
    def read(self, length, offset):
        """ Reads a given length of bytes at an offset into file. """
        self._fh.seek(offset)
        return self._fh.read(length)

    @logAllExceptions
    def release(self, flags):
        """ Releases this FileHandle, closing any open resources. """
        self._fh.close()
            
class StatResult(object):
    """ Encapsulates the required fields for the return from getattr for Fuse. """
    def __init__(self, fs, dir, atime, ctime, mtime, size):
        self.st_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        if dir:
            self.st_mode = (self.st_mode | stat.S_IFDIR |
                stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        else:
            self.st_mode = self.st_mode | stat.S_IFREG

        if fs.allow_delete and dir:
            # Allow directories to be written to by user and group
            self.st_mode = self.st_mode | stat.S_IWUSR | stat.S_IWGRP
            
        self.st_ino = 1L
        self.st_dev = 1L
        self.st_nlink = 1
        self.st_uid = os.geteuid()
        self.st_gid = os.getegid()
        self.st_size = size
        self.st_atime = atime
        self.st_mtime = ctime
        self.st_ctime = mtime
        
class Fs(fuse.Fuse):
    """ Fuse file system object for MythTV recordings. """
    def __init__(self, *args, **kw):
        fuse.Fuse.__init__(self, *args, **kw)
        self.be = None
        class WrappedFileHandle(FileHandle):
            def __init__(fself, path, flags, *mode):
                super(WrappedFileHandle, fself).__init__(self, path, flags, *mode)
        self.file_class = WrappedFileHandle
        self._root_cache = None
        self._last_root_time = time.time()
        self._logger = None
        self.be_hostname = None
        # Setup default options
        self.show_version = False
        self.invalid_chars = "<>|:\\?*'\""
        self.replacement_char= "_"
        self.invalid_chars_list = []
        self.log_file = None
        self.format_string = os.path.join("{title}","{title} - {subtitle}")
        self.allow_delete = False
        self.dbuser = None
        self.dbpassword = None
        # Add mount options
        self.parser.add_option(mountopt="invalid-chars", metavar="INVALID_CHARS",
            dest="invalid_chars", type="string",
            help="invalid characters to replace in names [default: %s]" % self.invalid_chars)
        self.parser.add_option(mountopt="replacement-char", metavar="REPLACEMENT_CHAR",
            dest="replacement_char", type="string",
            help="replacement character for invalid characters [default: %s]" % self.replacement_char)
        self.parser.add_option(mountopt="format-string", metavar="FORMAT_STRING",
            dest="format_string", type="string",
            help="format string for files [default: %s]" % self.format_string)
        self.parser.add_option(mountopt="log-file", metavar="LOG_FILE",
            dest="log_file", type="string",
            help="file to use for output of errors and warnings")
        self.parser.add_option(mountopt="allow-delete", metavar="ALLOW_DELETE",
            dest="allow_delete", action="store_true",
            help="allow deletion of recordings via file system")
        self.parser.add_option(mountopt="dbuser",
            dest="dbuser", type="string",
            help="username for authenticating with MythTV database")
        self.parser.add_option(mountopt="dbpassword",
            dest="dbpassword", type="string",
            help="password for authenticating with MythTV database")
        # Add process options
        self.parser.add_option("--version", dest="show_version",
            action="store_true", help="output version and exit")
        

    def _split_invalid_chars(self):
        """ Splits the invalid_chars string into a list. """
        self.invalid_chars_list = list(self.invalid_chars)
            
    def connect(self):
        """ Connects to the MythTV backend. """
        # Open the log file if necessary
        if self.log_file != None:
            self._logger = logging.basicConfig(
                filename=self.log_file,
                format='%(asctime)s:%(levelname)s- %(message)s',
                level=logging.INFO
                )
        db = None
        if self.dbuser != None and self.dbpassword != None:
           db = MythTV.MythDB(DBUserName = self.dbuser, DBPassword = self.dbpassword)
        self.be = MythTV.MythBE(db = db)
        self.be_hostname = self.be_hostname

    @logAllExceptions
    def getRoot(self):
        """ Returns the root directory of this file system. """
        time_since_last_update = time.time() - self._last_root_time
        if self._root_cache == None or time_since_last_update > CACHE_TIME:
            # Reconnect to the same backend to make sure the MySQL connection is fresh
            # This prevents a OperationalError: (2006, 'MySQL server has gone away')
            # exception occurring at some later point
            #
            # Force the module to reload to compensate for upgrades.
            reload(MythTV)
            self.be = MythTV.MythBE(self.be_hostname)
            self._root_cache = Root(self)
            self._last_root_time = time.time()
        return self._root_cache
        
    def getLogger(self):
        return self._logger

    def invalidateCache(self):
        """
        Used to indicate that the cache of recordings needs to be rebuilt.
        
        Called by file operations which alter the cache, such as unlink.
        """
        self._root_cache = None
        
    def parse(self):
        """ Parses and verifies mount options. """
        fuse.Fuse.parse(self, values=self, errex=1)
        # Process options
        self._split_invalid_chars()
        # Return false if filesystem shouldn't be mounted
        return not self.show_version

    @logAllExceptions
    def getattr(self, path):
        """ Returns the attributes for the given file. """
        try:
            return self.getRoot().resolve(path).getattr()
        except:
            return -errno.ENOENT

    @logAllExceptions
    def readdir(self, path, offset):
        """ Returns the contents of the requested directory. """
        for f in self.getRoot().resolve(path).readdir():
            yield fuse.Direntry(f.getBaseName())

    @logAllExceptions
    def unlink(self, path):
        """ Unlink the given path. """
        if not self.allow_delete:
            # Not allowed to delete
            return -errno.EPERM
        f = self.getRoot().resolve(path)
        return f.unlink()
