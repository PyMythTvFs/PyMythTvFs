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
CACHE_TIME = 30

class FileBase(object):
    def __init__(self, fs):
        self._fs = fs
        self._is_dir = False
        self._atime = 0
        self._mtime = 0
        self._ctime = 0
        self._size = 0
    
    def getattr(self):
        return StatResult(
            dir = self._is_dir,
            atime = self._atime,
            ctime = self._ctime,
            mtime = self._mtime,
            size = self._size)
        
    def resolve(self, path):
        cwd = self
        print path
        for d in path.rstrip(DIR_SEP).split(DIR_SEP):
            if d != "":
                cwd = cwd[d]
        return cwd

class File(FileBase):
    def __init__(self, fs):
        super(File, self).__init__(fs)
        self._is_dir = False

def datetimeToInt(dt):
    return time.mktime(dt.timetuple())
    
class Recording(File):
    def __init__(self, fs, recording):
        super(Recording, self).__init__(fs)
        self._recording = recording
        self._size = recording['filesize']
        self._ctime = datetimeToInt(recording['recstartts'])
        self._mtime = datetimeToInt(recording['recendts'])
        self._atime = self._mtime
        
    def getFileName(self):
        return self._recording.formatPath(
            u"%s - %s" % (
                self._recording['title'],
                self._recording['subtitle'])).encode('UTF-8')

class Directory(FileBase):
    def __init__(self, fs):
        super(Directory, self).__init__(fs)
        self._contents = {}
        self._is_dir = True
    
    def __getitem__(self, key):
        return self._contents[key]
        
    def readdir(self):
        return self._contents.values()

class Root(Directory):
    def __init__(self, fs):
        super(Root, self).__init__(fs)
        for r in self._fs.be.getRecordings():
            rf = Recording(self._fs, r)
            self._contents[rf.getFileName()] = rf

class StatResult:
    def __init__(self, dir, atime, ctime, mtime, size):
        self.st_mode = stat.S_IRUSR
        if dir:
            self.st_mode = self.st_mode | stat.S_IFDIR | stat.S_IXUSR
        else:
            self.st_mode = self.st_mode | stat.S_IFREG
            
        self.st_ino = 1L
        self.st_dev = 1L
        self.st_nlink = 1
        self.st_uid = 1000
        self.st_gid = 1000
        self.st_size = size
        self.st_atime = atime
        self.st_mtime = ctime
        self.st_ctime = mtime
        
class MissingOptionException(Exception):
    def __init__(self, missing):
        self.missing = missing
        
class Fs(fuse.Fuse):
    """
    """

    def __init__(self, *args, **kw):
        fuse.Fuse.__init__(self, *args, **kw)
        self.be = MythTV.MythBE()
        self._root_cache = None
        self._last_root_time = time.time()

    def getRoot(self):
        time_since_last_update = time.time() - self._last_root_time
        if self._root_cache == None or time_since_last_update > CACHE_TIME:
            self._root_cache = Root(self)
        return self._root_cache

    def parse(self):
        fuse.Fuse.parse(self, errex=1)

    def getattr(self, path):
        try:
            return self.getRoot().resolve(path).getattr()
        except:
            traceback.print_exc()
            return -errno.ENOENT
        
    def readdir(self, path, offset):
        for f in self.getRoot().resolve(path).readdir():
            yield fuse.Direntry(f.getFileName())
