# Headroom for Linux

**A disk-space utility for Arch and Omarchy.** Clear caches, hunt down large files, and uninstall packages cleanly — in a fast, keyboard-driven terminal app that picks up your Omarchy theme.

The Linux sibling of [Headroom for macOS](https://github.com/kanibusrex/headroom).

![Cleanup](docs/screenshots/cleanup.svg)

## Features

### 🧹 Cleanup
Scan first, see how much each category holds, pick what to clean, and confirm before anything is removed.

| Category | What it clears |
|---|---|
| Package cache | Old package downloads in `/var/cache/pacman/pkg` (keeps the 2 newest versions so you can roll back) |
| AUR build cache | Sources and builds left in `~/.cache/yay` and `~/.cache/paru` |
| App caches | Everything else in `~/.cache` |
| Thumbnails | File-manager image previews |
| Developer caches | npm, Cargo, Gradle and Bun download caches |
| Old tool versions | Versions [mise](https://mise.jdx.dev) installed that no config uses anymore (`mise prune`) — Omarchy adds a new version of claude, codex & co. on every update and never removes the old one |
| System logs | systemd journal older than 2 weeks |
| Crash dumps | Repeat core dumps in `/var/lib/systemd/coredump` — keeps the newest dump of each program so crashes can still be diagnosed |
| Orphaned packages | Dependencies nothing needs anymore (`pacman -Qdt`) |
| Docker | Stopped containers, unused images and build cache — never volumes |
| Trash | Empties `~/.local/share/Trash` |

### 📄 Large Files
Finds the biggest files in your home folder (100 MB+, 500 MB+ or 1 GB+) with size and last-modified date. Open the containing folder before deciding; removal goes to the Trash.

### 🗑 Packages
Lists your explicitly installed packages by size (repo or AUR), with a filter. Uninstalling runs `sudo pacman -Rns`, and Headroom also finds the leftovers the app scattered across `~/.config`, `~/.local/share`, `~/.cache`, `~/.local/state` and `~/.<name>` — you choose whether to trash those too.

## Safety

- **Scan before clean** — nothing is removed without an explicit confirmation.
- Cleanup only deletes the *contents* of well-known regenerable locations, never your documents or app data.
- Anything system-level (pacman, journal, crash dumps, Docker) runs in your terminal, where you see the exact command and pacman asks before removing packages.
- Large Files and package leftovers go to the **Trash**, not permanent deletion. `.git` folders are never offered.
- Core packages (`base`, `linux`, `systemd`, `pacman`, `hyprland`, `omarchy*`, …) can't be uninstalled from Headroom.
- Files that are locked or in use are skipped, never forced.

## Install

### From the AUR

```sh
yay -S headroom-linux    # or: paru -S headroom-linux
```

This installs `headroom` system-wide with its app-launcher entry and icon. Optional extras: `pacman-contrib` (package-cache cleanup), `mise`, `docker`.

### From source

Needs Python 3.11+. `pacman-contrib` (for `paccache`) enables package-cache cleanup.

```sh
git clone https://github.com/kanibusrex/headroom-linux
cd headroom-linux
./install.sh
headroom
```

`install.sh` also adds **Headroom** to your app launcher (`Super + Space` on Omarchy), with an icon. On Omarchy it opens in its own terminal window, and launching it again focuses the open one. `headroom --summary` prints what can be cleaned without opening the app.

### Floating window on Omarchy

The launcher opens Headroom with the window class `TUI.headroom`. To make it float, add this to `~/.config/hypr/hyprland.lua`:

```lua
o.window("TUI.headroom", {
  float = true,
  center = true,
  size = { 1200, 720 },
})
```

## Keys

| Key | Action |
|---|---|
| `1` `2` `3` | Switch tabs |
| `space` / `a` | Select a cleanup category / all or none |
| `c` | Clean selected |
| `t` / `o` / `m` | Trash file / open its folder / change minimum size |
| `u` or `Enter` · `/` | Uninstall package · filter |
| `r` · `q` | Rescan · quit |

## License

MIT — see [LICENSE](LICENSE).

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/headroom
```
