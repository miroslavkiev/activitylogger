from __future__ import annotations

import errno
import os
import subprocess
import sys

import pytest

import private_files
from operator_errors import OperatorError, safe_error_message


def test_private_reader_preserves_bytes_and_enforces_boundary(tmp_path):
    path = tmp_path / "private"
    path.write_bytes(b"private\x00data")
    path.chmod(0o600)
    assert private_files.read_private_bytes(path, max_bytes=12) == b"private\x00data"
    with pytest.raises(OSError, match="size limit"):
        private_files.read_private_bytes(path, max_bytes=11)
    path.chmod(0o644)
    with pytest.raises(OSError, match="unsafe"):
        private_files.read_private_bytes(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        private_files.read_private_bytes(link)
    link.unlink()
    os.link(path, link)
    with pytest.raises(OSError, match="unsafe"):
        private_files.read_private_bytes(path)


def test_private_fifo_is_rejected_without_waiting_for_a_writer(tmp_path):
    path = tmp_path / "fifo"
    os.mkfifo(path, 0o600)
    result = subprocess.run(
        [sys.executable, "-c", (
            "from pathlib import Path; from private_files import read_private_bytes; "
            "import sys; read_private_bytes(Path(sys.argv[1]))"
        ), str(path)],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode != 0
    assert "refusing unsafe private file" in result.stderr


def test_private_reader_rejects_replaced_path(tmp_path, monkeypatch):
    path = tmp_path / "private"
    replacement = tmp_path / "replacement"
    for item in (path, replacement):
        item.write_bytes(b"same bytes")
        item.chmod(0o600)
    real_read = os.read
    changed = False

    def replace_after_read(fd, size):
        nonlocal changed
        data = real_read(fd, size)
        if not changed:
            changed = True
            os.replace(replacement, path)
        return data

    monkeypatch.setattr(private_files.os, "read", replace_after_read)
    with pytest.raises(OSError, match="changed during read"):
        private_files.read_private_bytes(path)


def test_safe_errors_never_show_arbitrary_exception_content():
    secret = "SYNTHETIC_PRIVATE_TEXT"
    for error in (ValueError(secret), OSError(secret), PermissionError(secret)):
        assert secret not in safe_error_message(error)
    assert "4,000" in safe_error_message(OperatorError("text_too_long"))
    assert "full" in safe_error_message(OSError(errno.ENOSPC, secret))
    assert "Source files changed" in safe_error_message(OSError(errno.ESTALE, secret))
