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

# Let fuse know what API we are expecting
fuse.fuse_python_api = (0, 2)

DIR_SEP = '/'
""" Directory separator character. """

CACHE_TIME = 30
"""
Minimum time period in seconds between asking the backend for the
latest list of recordings.
"""

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
    
    def getattr(self):
        """ Returns the stat results for this file. """
        return StatResult(
            dir = self._is_dir,
            atime = self._atime,
            ctime = self._ctime,
            mtime = self._mtime,
            size = self._size)
        
    def resolve(self, path):
        """ Resolves the given path into a FileBase object """
        cwd = self
        print path
        for d in path.rstrip(DIR_SEP).split(DIR_SEP):
            if d != "":
                cwd = cwd[d]
        return cwd

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
        
    def getFileName(self):
        """ Returns the filename of this file. """
        return self._recording.formatPath(
            u"%s - %s" % (
                self._recording['title'],
                self._recording['subtitle'])).encode('UTF-8')
                
    def open(self):
        """ Returns an open file handle for the contents of this file. """
        return self._recording.open()

class Directory(FileBase):
    """ Represents a directory in the file system. """
    def __init__(self, fs):
        super(Directory, self).__init__(fs)
        self._contents = {}
        self._is_dir = True
    
    def __getitem__(self, key):
        """ Returns a FileBase with the name given by key. """
        return self._contents[key]
        
    def readdir(self):
        """ Returns a list of files in this directory. """
        return self._contents.values()

class Root(Directory):
    """ Represents the root directory of the file system "/". """
    def __init__(self, fs):
        super(Root, self).__init__(fs)
        for r in self._fs.be.getRecordings():
            rf = Recording(self._fs, r)
            self._contents[rf.getFileName()] = rf

class FileHandle(object):
    """ Handle representing an open recording file. """
    def __init__(self, fs, path, flags, *mode):
        self._fs = fs
        self._file = fs.getRoot().resolve(path)
        self._fh = self._file.open()
    
    def read(self, length, offset):
        """ Reads a given length of bytes at an offset into file. """
        self._fh.seek(offset)
        return self._fh.read(length)
    
    def release(self, flags):
        """ Releases this FileHandle, closing any open resources. """
        self._fh.release()
            
class StatResult(object):
    """ Encapsulates the required fields for the return from getattr for Fuse. """
    def __init__(self, dir, atime, ctime, mtime, size):
        self.st_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        if dir:
            self.st_mode = (self.st_mode | stat.S_IFDIR |
                stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        else:
            self.st_mode = self.st_mode | stat.S_IFREG
            
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
        self.be = MythTV.MythBE()
        class WrappedFileHandle(FileHandle):
            def __init__(fself, path, flags, *mode):
                super(WrappedFileHandle, fself).__init__(self, path, flags, *mode)
        self.file_class = WrappedFileHandle
        self._root_cache = None
        self._last_root_time = time.time()

    def getRoot(self):
        """ Returns the root directory of this file system. """
        time_since_last_update = time.time() - self._last_root_time
        if self._root_cache == None or time_since_last_update > CACHE_TIME:
            self._root_cache = Root(self)
            self._last_root_time = time.time()
        return self._root_cache

    def parse(self):
        """ Parses and verifies mount options. """
        fuse.Fuse.parse(self, errex=1)

    def getattr(self, path):
        """ Returns the attributes for the given file. """
        try:
            return self.getRoot().resolve(path).getattr()
        except:
            traceback.print_exc()
            return -errno.ENOENT
        
    def readdir(self, path, offset):
        """ Returns the contents of the requested directory. """
        for f in self.getRoot().resolve(path).readdir():
            yield fuse.Direntry(f.getFileName())
            
