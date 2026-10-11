"""Installed packages, and the files they leave behind in your home folder."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from headroom.util import CACHE_DIR, CONFIG_DIR, DATA_DIR, HOME, STATE_DIR, disk_usage, parse_size, run

# Removing these breaks the system, so Headroom refuses even though pacman would let you.
PROTECTED = {
    "base", "base-devel", "bash", "coreutils", "filesystem", "glibc", "grub", "limine",
    "linux", "linux-firmware", "linux-hardened", "linux-lts", "linux-zen", "mkinitcpio",
    "pacman", "sudo", "systemd", "hyprland", "uwsm",
}
PROTECTED_PREFIXES = ("omarchy",)

# AUR naming conventions: "foo-bin" or "foo-git" usually stores its files as "foo".
_SUFFIXES = ("-bin", "-git", "-appimage", "-nightly", "-beta", "-stable")


@dataclass
class Package:
    name: str
    version: str = ""
    description: str = ""
    size: int = 0
    explicit: bool = False
    required_by: list[str] = field(default_factory=list)
    foreign: bool = False  # from the AUR (or installed by hand)

    @property
    def protected(self) -> bool:
        return self.name in PROTECTED or self.name.startswith(PROTECTED_PREFIXES)


def parse_pacman_info(text: str) -> list[Package]:
    """Parse `pacman -Qi` output (C locale) into packages."""
    packages = []
    for block in text.strip().split("\n\n"):
        fields: dict[str, str] = {}
        last = None
        for line in block.splitlines():
            if " : " in line and not line.startswith(" "):
                key, value = line.split(" : ", 1)
                last = key.strip()
                fields[last] = value.strip()
            elif last:  # wrapped continuation line
                fields[last] += " " + line.strip()
        if "Name" not in fields:
            continue
        required = fields.get("Required By", "None")
        packages.append(
            Package(
                name=fields["Name"],
                version=fields.get("Version", ""),
                description=fields.get("Description", ""),
                size=parse_size(fields.get("Installed Size", "")) or 0,
                explicit=fields.get("Install Reason", "").startswith("Explicitly"),
                required_by=[] if required == "None" else required.split(),
            )
        )
    return packages


def installed_packages() -> list[Package]:
    """Explicitly installed packages, biggest first."""
    info = run(["pacman", "-Qi"], timeout=120)
    if info is None or info.returncode != 0:
        return []
    foreign = run(["pacman", "-Qmq"])
    foreign_names = set(foreign.stdout.split()) if foreign else set()
    packages = [p for p in parse_pacman_info(info.stdout) if p.explicit]
    for package in packages:
        package.foreign = package.name in foreign_names
    return sorted(packages, key=lambda p: p.size, reverse=True)


def leftover_names(package: str) -> set[str]:
    name = package.lower()
    names = {name}
    stripped = True
    while stripped:  # "microsoft-edge-stable-bin" -> "microsoft-edge-stable" -> "microsoft-edge"
        stripped = False
        for suffix in _SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[: -len(suffix)]
                names.add(name)
                stripped = True
        if match := re.fullmatch(r"(.+)-\d+", name):  # "sublime-text-4" -> "sublime-text"
            name = match.group(1)
            names.add(name)
            stripped = True
    return names


def find_leftovers(package: str) -> list[tuple[Path, int]]:
    """Per-user config, data, cache and state the package's apps created, with sizes.

    Matches folder or file names exactly (ignoring case, extension and AUR suffixes), so
    it errs toward missing something rather than flagging someone else's files.
    """
    names = leftover_names(package)
    found = []
    for root in (CONFIG_DIR, DATA_DIR, CACHE_DIR, STATE_DIR):
        if root.is_dir():
            for child in root.iterdir():
                if child.name.lower() in names or child.stem.lower() in names:
                    found.append(child)
    if HOME.is_dir():
        for child in HOME.iterdir():
            if child.name.startswith(".") and child.name[1:].lower() in names:
                found.append(child)
    return [(path, disk_usage(path)) for path in sorted(set(found))]
