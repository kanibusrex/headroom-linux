"""Command-line entry point: `headroom` opens the TUI, `headroom --summary` just prints a scan."""

from __future__ import annotations

import argparse

from headroom import __version__


def summary() -> None:
    from headroom.cleanup import default_categories
    from headroom.util import human

    total = 0
    for c in default_categories():
        result = c.scan()
        size = human(result.size) if result.available else "—"
        print(f"{c.name:<20} {size:>10}  {result.detail}")
        total += result.size or 0
    print(f"{'Total':<20} {human(total):>10}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="headroom",
        description="Clear caches, find large files, and uninstall packages cleanly.",
    )
    parser.add_argument("--summary", action="store_true", help="print what can be cleaned, then exit")
    parser.add_argument("--version", action="version", version=f"headroom {__version__}")
    args = parser.parse_args()

    if args.summary:
        summary()
        return

    from headroom.app import HeadroomApp

    HeadroomApp().run()
