"""Match the current Omarchy theme, falling back to Tokyo Night (Omarchy's default)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from textual.theme import Theme

from headroom.util import CONFIG_DIR, STATE_DIR

FALLBACK = "tokyo-night"
_COLOR_FILES = (
    STATE_DIR / "omarchy" / "current" / "theme" / "colors.toml",
    CONFIG_DIR / "omarchy" / "current" / "theme" / "colors.toml",
)


def omarchy_theme() -> Theme | None:
    for path in _COLOR_FILES:
        try:
            colors = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        return _from_colors(colors, path)
    return None


def _from_colors(c: dict, path: Path) -> Theme | None:
    try:
        return Theme(
            name="omarchy",
            primary=c.get("accent") or c["blue"],
            secondary=c.get("blue"),
            accent=c.get("magenta"),
            foreground=c["foreground"],
            background=c["background"],
            surface=c.get("dark_background") or c["background"],
            panel=c.get("lighter_background"),
            success=c.get("green"),
            warning=c.get("yellow"),
            error=c.get("red"),
            dark=c.get("mode", "dark") != "light",
        )
    except (KeyError, ValueError, TypeError):
        return None
