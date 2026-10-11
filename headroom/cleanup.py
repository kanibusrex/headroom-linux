"""Cleanup categories: well-known locations that are safe to clear and regenerate on demand.

Each category scans to estimate how much space it can reclaim. Categories that touch the
system (pacman, journald, Docker) clean by running commands in the terminal, so sudo can
prompt for a password and pacman can ask for confirmation. User-level caches are cleared
directly by Headroom.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from headroom.util import CACHE_DIR, HOME, TRASH_DIR, clear_contents, disk_usage, parse_size, run, tilde

PACMAN_CACHE = Path("/var/cache/pacman/pkg")


@dataclass
class ScanResult:
    size: int | None  # reclaimable bytes; None when it can't be measured
    detail: str = ""
    available: bool = True


@dataclass
class Category:
    key: str
    name: str
    description: str
    default_selected: bool = True
    result: ScanResult | None = field(default=None, init=False)

    def scan(self) -> ScanResult:
        raise NotImplementedError

    def commands(self) -> list[list[str]]:
        """Commands to run in the terminal to clean. Empty if cleaned in-process."""
        return []

    def clean(self) -> int:
        """Clean in-process. Returns bytes freed."""
        return 0

    @property
    def runs_in_terminal(self) -> bool:
        return bool(self.commands())


@dataclass
class DirectoryCategory(Category):
    """Clears the contents of one or more user-owned directories."""

    paths: tuple[Path, ...] = ()
    exclude: frozenset[str] = frozenset()

    def _existing(self) -> list[Path]:
        return [p for p in self.paths if p.is_dir()]

    def scan(self) -> ScanResult:
        existing = self._existing()
        if not existing:
            return ScanResult(0, "nothing here")
        size = 0
        for path in existing:
            for child in path.iterdir():
                if child.name not in self.exclude:
                    size += disk_usage(child)
        return ScanResult(size, ", ".join(tilde(p) for p in existing))

    def clean(self) -> int:
        return sum(clear_contents(p, set(self.exclude)) for p in self._existing())


class PacmanCache(Category):
    KEEP = 2  # the installed version plus one older one, so you can still roll back

    def scan(self) -> ScanResult:
        if not shutil.which("paccache"):
            return ScanResult(None, "paccache not found (install pacman-contrib)", available=False)
        # The two passes overlap (old versions of uninstalled packages), so count each file once.
        candidates: set[Path] = set()
        for args in ([f"-k{self.KEEP}"], ["-u", "-k0"]):
            result = run(["paccache", "-d", "-v", *args])
            if result is None:
                return ScanResult(None, "couldn't run paccache", available=False)
            for line in result.stdout.splitlines():
                line = line.strip()
                if ".pkg.tar" in line and not line.startswith("==>"):
                    path = Path(line)
                    candidates.add(path if path.is_absolute() else PACMAN_CACHE / path)
        size = 0
        for path in candidates:
            try:
                size += path.stat().st_size
            except OSError:
                pass
        return ScanResult(size, f"keeps the newest {self.KEEP} versions of each package")

    def commands(self) -> list[list[str]]:
        return [
            ["sudo", "paccache", "-r", f"-k{self.KEEP}"],
            ["sudo", "paccache", "-r", "-u", "-k0"],
        ]


class JournalLogs(Category):
    KEEP = "2weeks"

    def scan(self) -> ScanResult:
        result = run(["journalctl", "--disk-usage"])
        if result is None:
            return ScanResult(None, "journalctl not found", available=False)
        size = parse_size(result.stdout + result.stderr)
        return ScanResult(size, "total size — keeps the last 2 weeks")

    def commands(self) -> list[list[str]]:
        return [["sudo", "journalctl", f"--vacuum-time={self.KEEP}"]]


class OrphanPackages(Category):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orphans: list[str] = []

    def scan(self) -> ScanResult:
        result = run(["pacman", "-Qdtq"])
        if result is None:
            return ScanResult(None, "pacman not found", available=False)
        self.orphans = result.stdout.split()
        if not self.orphans:
            return ScanResult(0, "no orphaned packages")
        info = run(["pacman", "-Qi", *self.orphans])
        size = 0
        if info is not None:
            for line in info.stdout.splitlines():
                if line.startswith("Installed Size"):
                    size += parse_size(line) or 0
        names = ", ".join(self.orphans[:4]) + (" …" if len(self.orphans) > 4 else "")
        return ScanResult(size, f"{len(self.orphans)}: {names}")

    def commands(self) -> list[list[str]]:
        return [["sudo", "pacman", "-Rns", *self.orphans]] if self.orphans else []


class Docker(Category):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sudo = False

    def scan(self) -> ScanResult:
        if not shutil.which("docker"):
            return ScanResult(None, "Docker not installed", available=False)
        result = run(["docker", "system", "df", "--format", "{{json .}}"], timeout=30)
        if result is None or result.returncode != 0:
            # Usually the user isn't in the docker group; cleaning can still go through sudo.
            self.sudo = True
            return ScanResult(None, "size unknown without Docker access — cleans with sudo")
        self.sudo = False
        size = 0
        for line in result.stdout.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("Type") != "Local Volumes":  # volumes hold data; never touched
                size += parse_size(row.get("Reclaimable", "")) or 0
        return ScanResult(size, "stopped containers, unused images, build cache")

    def commands(self) -> list[list[str]]:
        cmd = ["docker", "system", "prune", "--all", "--force"]
        return [["sudo", *cmd] if self.sudo else cmd]


AUR_DIRS = ("yay", "paru")


def default_categories() -> list[Category]:
    return [
        PacmanCache("pacman", "Package cache", "Old package downloads in /var/cache/pacman/pkg"),
        DirectoryCategory(
            "aur", "AUR build cache", "Sources and builds left by yay / paru",
            paths=tuple(CACHE_DIR / d for d in AUR_DIRS),
        ),
        DirectoryCategory(
            "cache", "App caches", "Everything else in ~/.cache — apps rebuild it as needed",
            paths=(CACHE_DIR,),
            exclude=frozenset({*AUR_DIRS, "thumbnails"}),
        ),
        DirectoryCategory(
            "thumbnails", "Thumbnails", "Image previews generated by file managers",
            paths=(CACHE_DIR / "thumbnails",),
        ),
        DirectoryCategory(
            "dev", "Developer caches", "Downloaded packages for npm, Cargo, Gradle and Bun",
            paths=(
                HOME / ".npm" / "_cacache",
                HOME / ".cargo" / "registry" / "cache",
                HOME / ".gradle" / "caches",
                HOME / ".bun" / "install" / "cache",
            ),
        ),
        JournalLogs("journal", "System logs", "systemd journal", default_selected=False),
        OrphanPackages(
            "orphans", "Orphaned packages", "Dependencies nothing needs anymore",
            default_selected=False,
        ),
        Docker("docker", "Docker", "Unused Docker data (volumes are kept)", default_selected=False),
        DirectoryCategory(
            "trash", "Trash", "Files you've already deleted — this empties it for good",
            paths=(TRASH_DIR / "files", TRASH_DIR / "info"),
            default_selected=False,
        ),
    ]
