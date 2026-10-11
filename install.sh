#!/usr/bin/env bash
# Install Headroom into its own virtualenv, put `headroom` on your PATH, and add it to the app launcher.
set -euo pipefail

src="$(cd "$(dirname "$0")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
venv="$data/headroom/venv"
bin="$HOME/.local/bin"

python3 -m venv "$venv"
"$venv/bin/pip" install --quiet --upgrade "$src"
mkdir -p "$bin"
ln -sf "$venv/bin/headroom" "$bin/headroom"

# App launcher entry. On Omarchy it opens in its own floating terminal window
# (class TUI.headroom), and launching again focuses the open window.
mkdir -p "$data/icons/hicolor/256x256/apps" "$data/applications"
cp "$src/assets/headroom.png" "$data/icons/hicolor/256x256/apps/headroom.png"
gtk-update-icon-cache "$data/icons/hicolor" &>/dev/null || true

if command -v omarchy-launch-or-focus-tui >/dev/null; then
  exec_line="omarchy-launch-or-focus-tui --app-id=TUI.headroom $bin/headroom"
  terminal=false
else
  exec_line="$bin/headroom"
  terminal=true
fi

cat >"$data/applications/headroom.desktop" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Headroom
GenericName=Disk Cleanup
Comment=Clear caches, find large files, and uninstall packages cleanly
Exec=$exec_line
Terminal=$terminal
Icon=headroom
Categories=System;
Keywords=disk;space;clean;cache;storage;uninstall;
StartupWMClass=TUI.headroom
DESKTOP
update-desktop-database "$data/applications" &>/dev/null || true

echo "Installed: $bin/headroom (and Headroom in your app launcher)"
command -v paccache >/dev/null || echo "Tip: install pacman-contrib for package-cache cleanup (sudo pacman -S pacman-contrib)"
case ":$PATH:" in *":$bin:"*) ;; *) echo "Note: add $bin to your PATH" ;; esac
