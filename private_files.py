"""Shared reads for owner-only local files."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path


def open_private_file(
    path: Path, *, max_bytes: int | None = None
) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise PermissionError("refusing unsafe private file")
        if max_bytes is not None and info.st_size > max_bytes:
            raise OSError("private file exceeds its size limit")
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
    )


def read_private_bytes(path: Path, *, max_bytes: int | None = None) -> bytes:
    """Read a bounded stable file, rejecting replacement as well as mutation."""
    fd, before = open_private_file(path, max_bytes=max_bytes)
    try:
        chunks: list[bytes] = []
        size = 0
        while True:
            limit = 1024 * 1024
            if max_bytes is not None:
                limit = min(limit, max_bytes + 1 - size)
            chunk = os.read(fd, limit)
            if not chunk:
                break
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise OSError("private file exceeds its size limit")
            chunks.append(chunk)
        if (
            size != before.st_size
            or _identity(before) != _identity(os.fstat(fd))
            or _identity(before) != _identity(path.lstat())
        ):
            raise OSError(errno.ESTALE, "private file changed during read")
        return b"".join(chunks)
    finally:
        os.close(fd)
