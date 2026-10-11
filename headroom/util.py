"""Small helpers shared by the scanners: sizes, disk usage, commands, and the Trash."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache")
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share")
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state")
TRASH_DIR = DATA_DIR / "Trash"

_UNITS = {
    # binary units (pacman, paccache, journalctl)
    "B": 1,
    "K": 1024, "KiB": 1024,
    "M": 1024**2, "MiB": 1024**2,
    "G": 1024**3, "GiB": 1024**3,
    "T": 1024**4, "TiB": 1024**4,
    # decimal units (docker)
    "kB": 1000, "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
}
_SIZE_RE = re.compile(r"([\d.]+)\s*(KiB|MiB|GiB|TiB|kB|KB|MB|GB|TB|B|K|M|G|T)\b")


def parse_size(text: str) -> int | None:
    """Parse the first size in `text`, e.g. "12.5 MiB", "32.0M" or "1.2GB"."""
    match = _SIZE_RE.search(text)
    if not match:
        return None
    return int(float(match.group(1)) * _UNITS[match.group(2)])


def human(size: int | None) -> str:
    """Format bytes for display, e.g. 1536 -> "1.5 KB"."""
    if size is None:
        return "?"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def disk_usage(path: Path) -> int:
    """Bytes actually used on disk by `path` (like `du -s`). Never follows symlinks."""
    try:
        st = path.lstat()
    except OSError:
        return 0
    if not path.is_dir() or path.is_symlink():
        return st.st_blocks * 512
    total = st.st_blocks * 512
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        est = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    total += est.st_blocks * 512
                    if entry.is_dir(follow_symlinks=False) and est.st_dev == st.st_dev:
                        stack.append(Path(entry.path))
        except OSError:
            continue
    return total


def clear_contents(path: Path, exclude: set[str] = frozenset()) -> int:
    """Delete everything inside `path` (but not `path` itself). Returns bytes freed.

    Items that are locked or in use are skipped, never forced.
    """
    if not path.is_dir():
        return 0
    freed = 0
    for child in path.iterdir():
        if child.name in exclude:
            continue
        before = disk_usage(child)
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
        except OSError:
            pass
        freed += before - disk_usage(child)
    return freed


def run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess[str] | None:
    """Run a command quietly with a C locale (stable output to parse). None if it can't run."""
    if not shutil.which(cmd[0]):
        return None
    env = {**os.environ, "LC_ALL": "C"}
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def move_to_trash(path: Path) -> bool:
    """Move a file or folder to the desktop Trash (recoverable)."""
    result = run(["gio", "trash", "--", str(path)])
    return result is not None and result.returncode == 0


def open_folder(path: Path) -> None:
    """Open a folder in the desktop file manager, detached from Headroom."""
    if shutil.which("xdg-open"):
        subprocess.Popen(
            ["xdg-open", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def tilde(path: Path | str) -> str:
    """Show paths under $HOME as ~/…"""
    text = str(path)
    home = str(HOME)
    return "~" + text[len(home):] if text == home or text.startswith(home + "/") else text
