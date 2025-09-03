# License: GPL 3
# ScanDir module for directory scanning

import os
from enum import Enum
from pathlib import Path

class PosixFileType(Enum):
    Unknown = 0
    File = 1
    Directory = 2
    Link = 3
    FIFO = 4
    Socket = 5
    CharDev = 6
    BlockDev = 7

class DirEntry:
    def __init__(self, name: str, path: str, type: PosixFileType):
        self.name = name
        self.path = path
        self.type = type

    def __str__(self):
        return f"<{self.type.name.lower()} {repr(self.path)}>"

    def isfile(self):
        return self.type == PosixFileType.File or (self.type == PosixFileType.Link and os.path.isfile(self.path))

    def isdir(self):
        return self.type == PosixFileType.Directory or (self.type == PosixFileType.Link and os.path.isdir(self.path))

    def islink(self):
        return self.type == PosixFileType.Link

    def isfifo(self):
        return self.type == PosixFileType.FIFO or (self.type == PosixFileType.Link and stat.S_ISFIFO(os.stat(self.path).st_mode))

    def issocket(self):
        return self.type == PosixFileType.Socket or (self.type == PosixFileType.Link and stat.S_ISSOCK(os.stat(self.path).st_mode))

    def ischardev(self):
        return self.type == PosixFileType.CharDev or (self.type == PosixFileType.Link and stat.S_ISCHR(os.stat(self.path).st_mode))

    def isblockdev(self):
        return self.type == PosixFileType.BlockDev or (self.type == PosixFileType.Link and stat.S_ISBLK(os.stat(self.path).st_mode))

def scandir(dir: str = ".", sort: bool = True):
    """Scan directory and return DirEntry objects."""
    entries = []
    for entry in os.scandir(dir):
        file_type = PosixFileType.Unknown
        if entry.is_file(follow_symlinks=False):
            file_type = PosixFileType.File
        elif entry.is_dir(follow_symlinks=False):
            file_type = PosixFileType.Directory
        elif entry.is_symlink():
            file_type = PosixFileType.Link
        elif stat.S_ISFIFO(entry.stat(follow_symlinks=False).st_mode):
            file_type = PosixFileType.FIFO
        elif stat.S_ISSOCK(entry.stat(follow_symlinks=False).st_mode):
            file_type = PosixFileType.Socket
        elif stat.S_ISCHR(entry.stat(follow_symlinks=False).st_mode):
            file_type = PosixFileType.CharDev
        elif stat.S_ISBLK(entry.stat(follow_symlinks=False).st_mode):
            file_type = PosixFileType.BlockDev
        entries.append(DirEntry(entry.name, entry.path, file_type))
    if sort:
        entries.sort(key=lambda e: e.name)
    return entries

def scandirtree(root: str = ".", topdown: bool = True, follow_symlinks: bool = False, onerror=None, prune=lambda x: False):
    """Walk directory tree and yield (root, dirs, files) tuples."""
    def _scandirtree():
        def isfilelike(e):
            return (not follow_symlinks and e.islink()) or not e.isdir()
        
        content = scandir(root) if not onerror else (scandir(root) if not isinstance(scandir(root), Exception) else None)
        if content is None:
            return
        dirs = []
        files = []
        for entry in content:
            if prune(entry):
                continue
            if isfilelike(entry):
                files.append(entry)
            else:
                dirs.append(entry)
        
        if topdown:
            yield root, dirs, files
        for dir_entry in dirs:
            yield from _scandirtree(dir_entry.path)
        if not topdown:
            yield root, dirs, files

    return _scandirtree()

def walkdir(root: str = ".", topdown: bool = True, follow_symlinks: bool = False, onerror=None, prune=lambda x: False):
    """Walk directory and yield (root, dirs, files) tuples with names."""
    for root, dirs, files in scandirtree(root, topdown, follow_symlinks, onerror, prune):
        yield root, [d.name for d in dirs], [f.name for f in files]