#!/usr/bin/env python
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

from distutils.core import setup
import mythtvfs

setup(name='pymythtvfs',
	description='Mythtv Fuse Filesystem',
    author='Toby Gray',
    author_email='toby.gray@gmail.com',
    url='http://github.com/tobygray/pymythtvfs',
    py_modules=['mythtvfs'],
	scripts=['pymythtvfs'],
    data_files=[('man/man8', ['pymythtvfs.8'])],
	version=str(mythtvfs.VERSION))
