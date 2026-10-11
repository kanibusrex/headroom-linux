"""Find the biggest files in your home folder."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from headroom.util import HOME, TRASH_DIR

THRESHOLDS = (100 * 1024**2, 500 * 1024**2, 1024**3)
MAX_RESULTS = 500


@dataclass
class LargeFile:
    path: Path
    size: int
    modified: float


def find_large_files(
    root: Path = HOME,
    min_size: int = THRESHOLDS[0],
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[int], None] = lambda dirs: None,
) -> list[LargeFile]:
    """Walk `root` (staying on one filesystem, skipping symlinks, the Trash and .git folders)."""
    results: list[LargeFile] = []
    try:
        device = root.stat().st_dev
    except OSError:
        return results
    skip = {str(TRASH_DIR)}
    stack = [str(root)]
    dirs = 0
    while stack:
        if cancelled():
            break
        current = stack.pop()
        dirs += 1
        if dirs % 500 == 0:
            progress(dirs)
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        # .git internals look like big junk files, but trashing them breaks the repo.
                        if st.st_dev == device and entry.path not in skip and entry.name != ".git":
                            stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        # Allocated size, so sparse files (VM disks) aren't overstated.
                        size = min(st.st_size, st.st_blocks * 512)
                        if size >= min_size:
                            results.append(LargeFile(Path(entry.path), size, st.st_mtime))
        except OSError:
            continue
    results.sort(key=lambda f: f.size, reverse=True)
    return results[:MAX_RESULTS]
