"""
storage.py — local file storage for uploaded PDFs.

Phase A: write bytes to ./storage/ with a timestamped filename. No dedupe,
no cloud. The API layer (Phase C) calls save_upload(); the terminal runner
just passes a path that already exists on disk.
"""
import os
import time
from pathlib import Path

STORAGE_DIR = Path(__file__).parent / "storage"


def save_upload(file_bytes: bytes, filename: str) -> str:
    """Write bytes to storage/ with a timestamp prefix. Returns the path."""
    STORAGE_DIR.mkdir(exist_ok=True)
    stem, ext = os.path.splitext(filename)
    safe = f"{int(time.time() * 1000)}_{stem}{ext}"
    path = STORAGE_DIR / safe
    path.write_bytes(file_bytes)
    return str(path)
