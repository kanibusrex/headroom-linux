#!/usr/bin/env bash
# Install Headroom into its own virtualenv and put `headroom` on your PATH.
set -euo pipefail

src="$(cd "$(dirname "$0")" && pwd)"
venv="${XDG_DATA_HOME:-$HOME/.local/share}/headroom/venv"
bin="$HOME/.local/bin"

python3 -m venv "$venv"
"$venv/bin/pip" install --quiet --upgrade "$src"
mkdir -p "$bin"
ln -sf "$venv/bin/headroom" "$bin/headroom"

echo "Installed: $bin/headroom"
command -v paccache >/dev/null || echo "Tip: install pacman-contrib for package-cache cleanup (sudo pacman -S pacman-contrib)"
case ":$PATH:" in *":$bin:"*) ;; *) echo "Note: add $bin to your PATH" ;; esac
