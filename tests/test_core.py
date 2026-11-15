import os
from pathlib import Path

from headroom import packages
from headroom.cleanup import DirectoryCategory
from headroom.large_files import find_large_files
from headroom.packages import leftover_names, parse_pacman_info
from headroom.util import human, parse_size


def test_parse_size_units():
    assert parse_size("Installed Size  : 1.50 MiB") == int(1.5 * 1024**2)
    assert parse_size("journals take up 32.0M in the file system.") == 32 * 1024**2
    assert parse_size("1.2GB (50%)") == int(1.2e9)
    assert parse_size("512kB") == 512_000
    assert parse_size("0B") == 0
    assert parse_size("nothing here") is None


def test_human():
    assert human(None) == "?"
    assert human(512) == "512 B"
    assert human(1536) == "1.5 KB"
    assert human(3 * 1024**3) == "3.0 GB"


PACMAN_QI = """\
Name            : firefox
Version         : 131.0-1
Description     : Fast, Private & Safe Web Browser
Installed Size  : 250.00 MiB
Required By     : None
Install Reason  : Explicitly installed

Name            : zlib
Version         : 1:1.3.1-2
Description     : Compression library implementing the deflate compression method found in gzip
                  and PKZIP
Installed Size  : 375.00 KiB
Required By     : curl  file  glibc
Install Reason  : Installed as a dependency for another package
"""


def test_parse_pacman_info():
    firefox, zlib = parse_pacman_info(PACMAN_QI)
    assert firefox.name == "firefox" and firefox.explicit and firefox.required_by == []
    assert firefox.size == 250 * 1024**2
    assert not zlib.explicit
    assert zlib.required_by == ["curl", "file", "glibc"]
    assert zlib.description.endswith("gzip and PKZIP")


def test_protected_packages():
    assert parse_pacman_info("Name : linux\n")[0].protected
    assert parse_pacman_info("Name : omarchy-nvim\n")[0].protected
    assert not parse_pacman_info("Name : firefox\n")[0].protected


def test_leftover_names_strip_aur_suffixes():
    assert leftover_names("Obsidian-bin") == {"obsidian-bin", "obsidian"}
    assert "microsoft-edge" in leftover_names("microsoft-edge-stable-bin")
    assert "sublime-text" in leftover_names("sublime-text-4")


def test_find_leftovers(tmp_path, monkeypatch):
    config, data = tmp_path / ".config", tmp_path / ".local/share"
    for d in (config / "obsidian", config / "obsidian-other", data / "Obsidian", tmp_path / ".obsidian"):
        d.mkdir(parents=True)
    (config / "obsidian.conf").write_text("x")
    for name, value in {"HOME": tmp_path, "CONFIG_DIR": config, "DATA_DIR": data,
                        "CACHE_DIR": tmp_path / "nope", "STATE_DIR": tmp_path / "nope"}.items():
        monkeypatch.setattr(packages, name, value)
    found = {p.relative_to(tmp_path).as_posix() for p, _ in packages.find_leftovers("obsidian-bin")}
    assert found == {".config/obsidian", ".config/obsidian.conf", ".local/share/Obsidian", ".obsidian"}


def test_directory_category_clears_contents_but_respects_excludes(tmp_path):
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep/file").write_bytes(b"x" * 10000)
    (tmp_path / "junk").mkdir()
    (tmp_path / "junk/file").write_bytes(b"x" * 10000)
    (tmp_path / "loose").write_bytes(b"x" * 10000)
    cat = DirectoryCategory("t", "Test", "", paths=(tmp_path,), exclude=frozenset({"keep"}))
    assert cat.scan().size > 0
    assert cat.clean() > 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep"]
    assert cat.scan().size == 0


def test_find_large_files_skips_small_and_symlinks(tmp_path):
    big = tmp_path / "a/b/big.bin"
    big.parent.mkdir(parents=True)
    with open(big, "wb") as f:
        f.write(os.urandom(2 * 1024 * 1024))
    (tmp_path / "small.txt").write_text("hi")
    (tmp_path / "link").symlink_to(big)
    (tmp_path / "repo/.git").mkdir(parents=True)
    (tmp_path / "repo/.git/pack").write_bytes(os.urandom(2 * 1024 * 1024))
    files = find_large_files(tmp_path, min_size=1024 * 1024)
    assert [f.path for f in files] == [big]


def test_crash_dump_name_parsing():
    from headroom.cleanup import CrashDumps
    parse = CrashDumps.parse_name
    boot = "468964b206344c26bf82dc6e61c80dad"
    assert parse(f"core.gdb.1000.{boot}.371612.1794355445000000.zst") == ("gdb", 1794355445000000)
    assert parse(f"core.SimpleHome\\x20Brow.1000.{boot}.42.17.lz4") == ("SimpleHome\\x20Brow", 17)
    assert parse(f"core.my.prog.1000.{boot}.42.17") == ("my.prog", 17)
    assert parse("README") is None
    assert parse(f"core.gdb.1000.{boot}.42.notatime.zst") is None


def test_crash_dumps_keep_newest_per_program(tmp_path):
    from headroom.cleanup import CrashDumps
    boot = "b" * 32
    names = [f"core.web.1000.{boot}.1.100.zst", f"core.web.1000.{boot}.2.300.zst",
             f"core.web.1000.{boot}.3.200.zst", f"core.gdb.1000.{boot}.4.50.zst", "unrelated"]
    for n in names:
        (tmp_path / n).write_bytes(b"x" * 5000)
    cat = CrashDumps("coredumps", "Crash dumps", "")
    cat.directory = tmp_path
    result = cat.scan()
    assert result.size > 0
    assert sorted(p.name for p in cat.doomed) == sorted(names[i] for i in (0, 2))
    assert cat.commands()[0][:4] == ["sudo", "rm", "-f", "--"]
    assert "2 of 4" in result.detail

    empty = CrashDumps("coredumps", "Crash dumps", "")
    empty.directory = tmp_path / "missing"
    assert empty.scan().size == 0 and empty.commands() == []


def test_mise_versions_scan(tmp_path, monkeypatch):
    import json
    import subprocess
    from headroom import cleanup
    old = tmp_path / "claude/1.0"
    old.mkdir(parents=True)
    (old / "bin").write_bytes(b"x" * 8192)
    payload = {"claude": [
        {"version": "1.0", "install_path": str(old), "installed": True, "active": False},
        {"version": "2.0", "install_path": str(tmp_path / "claude/2.0"), "installed": True, "active": True},
    ]}
    calls = []

    def fake_run(cmd, timeout=60):
        calls.append(cmd)
        if cmd[1] == "prune":
            import shutil
            shutil.rmtree(old)
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(cleanup, "run", fake_run)
    cat = cleanup.MiseVersions("mise", "Old tool versions", "")
    result = cat.scan()
    assert cat.paths == [old] and result.size >= 8192
    assert "claude ×1" in result.detail
    assert not cat.runs_in_terminal
    assert cat.clean() >= 8192
    assert calls[-1] == ["mise", "prune", "--tools", "--yes"]
