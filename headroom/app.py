"""The Headroom terminal UI: Cleanup, Large Files and Packages tabs."""

from __future__ import annotations

import subprocess
from datetime import datetime

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static, TabbedContent, TabPane
from textual.worker import get_current_worker

from headroom import __version__
from headroom.cleanup import Category, ScanResult, default_categories
from headroom.large_files import THRESHOLDS, LargeFile, find_large_files
from headroom.packages import Package, find_leftovers, installed_packages
from headroom.theme import FALLBACK, omarchy_theme
from headroom.util import HOME, human, move_to_trash, open_folder, tilde


def color(app: App, name: str) -> str:
    """A color from the active theme, for Rich text in table cells."""
    return app.theme_variables.get(name, "default")


class ConfirmScreen(ModalScreen[str]):
    """Ask before doing anything destructive. Dismisses with the chosen button's id, or ""."""

    BINDINGS = [Binding("escape", "dismiss('')", "Cancel")]

    def __init__(self, title: str, body: str, buttons: list[tuple[str, str, str]]):
        super().__init__()
        self.title_text = title
        self.body = body
        self.buttons = buttons  # (id, label, variant)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")
            with VerticalScroll(id="dialog-body"):
                yield Static(self.body)
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                for button_id, label, variant in self.buttons:
                    yield Button(label, id=button_id, variant=variant)

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss("" if event.button.id == "cancel" else event.button.id)


def run_in_terminal(app: App, title: str, commands: list[list[str]]) -> bool:
    """Leave the TUI and run commands in the real terminal, so sudo and pacman can prompt.

    Returns True if every command succeeded.
    """
    ok = True
    try:
        with app.suspend():
            print(f"\n\033[1m── Headroom: {title} ──\033[0m\n")
            for cmd in commands:
                print(f"\033[2m$ {' '.join(cmd)}\033[0m")
                try:
                    if subprocess.run(cmd).returncode != 0:
                        ok = False
                except (OSError, KeyboardInterrupt):
                    ok = False
                print()
            input("Press Enter to return to Headroom…")
    except Exception as error:  # e.g. SuspendNotSupported when not in a real terminal
        app.notify(f"Couldn't hand over the terminal: {error}", severity="error")
        return False
    return ok


class CleanupPane(Vertical):
    BINDINGS = [
        Binding("space", "toggle", "Select"),
        Binding("a", "toggle_all", "All/none"),
        Binding("c", "clean", "Clean selected"),
        Binding("r", "scan", "Rescan"),
    ]

    def __init__(self, categories: list[Category] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.categories = {c.key: c for c in (categories or default_categories())}
        self.selected = {c.key for c in self.categories.values() if c.default_selected}

    def compose(self) -> ComposeResult:
        yield Static("Safe-to-clear locations. Pick what to clean, then press [b]c[/].", classes="intro")
        yield DataTable(cursor_type="row", zebra_stripes=True, id="cleanup-table")
        yield Static("", id="cleanup-summary", classes="summary")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column(" ", key="check", width=3)
        table.add_column("Category", key="name", width=20)
        table.add_column("Size", key="size", width=10)
        table.add_column("Details", key="detail")
        for c in self.categories.values():
            table.add_row(self._check(c.key), c.name, Text("…", style="dim"), Text(c.description, style="dim"), key=c.key)
        self.action_scan()

    def _check(self, key: str) -> Text:
        return Text("✓", style=f"bold {color(self.app, 'success')}") if key in self.selected else Text("·", style="dim")

    def _row_key(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        return table.ordered_rows[table.cursor_row].key.value

    def _refresh_row(self, key: str) -> None:
        c = self.categories[key]
        table = self.query_one(DataTable)
        table.update_cell(key, "check", self._check(key))
        if c.result is None:
            table.update_cell(key, "size", Text("scanning", style="dim italic"))
            return
        r = c.result
        size = Text(human(r.size), style="bold" if r.size else "dim") if r.available else Text("—", style="dim")
        detail = Text(r.detail or c.description, style="dim" if not r.available else "")
        if c.runs_in_terminal and r.available:
            detail.append("  sudo", style=f"italic {color(self.app, 'warning')}")
        table.update_cell(key, "size", size)
        table.update_cell(key, "detail", detail)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        total = sum(c.result.size or 0 for c in self.categories.values() if c.result)
        chosen = sum(
            c.result.size or 0 for k, c in self.categories.items() if c.result and k in self.selected
        )
        self.query_one("#cleanup-summary", Static).update(
            f"Selected [b]{human(chosen)}[/] of {human(total)} found"
        )

    def action_toggle(self) -> None:
        key = self._row_key()
        if key is None:
            return
        self.selected ^= {key}
        self._refresh_row(key)

    def action_toggle_all(self) -> None:
        available = {k for k, c in self.categories.items() if not c.result or c.result.available}
        self.selected = set() if self.selected >= available else available
        for key in self.categories:
            self._refresh_row(key)

    @work(thread=True, exclusive=True, group="cleanup-scan")
    def action_scan(self) -> None:
        worker = get_current_worker()
        for key, c in self.categories.items():
            c.result = None
            self.app.call_from_thread(self._refresh_row, key)
        for key, c in self.categories.items():
            if worker.is_cancelled:
                return
            try:
                c.result = c.scan()
            except Exception as error:  # never let one category break the scan
                c.result = ScanResult(None, f"scan failed: {error}", available=False)
            if not c.result.available:
                self.selected.discard(key)
            self.app.call_from_thread(self._refresh_row, key)

    def action_clean(self) -> None:
        chosen = [
            c for k, c in self.categories.items()
            if k in self.selected and c.result and c.result.available and c.result.size != 0
        ]
        if not chosen:
            self.app.notify("Nothing selected to clean (or still scanning).", severity="warning")
            return
        lines = [f"  • [b]{escape(c.name)}[/]  {human(c.result.size)}" for c in chosen]
        if any(c.runs_in_terminal for c in chosen):
            lines.append(
                "\nSystem items run in the terminal — you may be asked for your sudo password,"
                " and pacman will ask you to confirm."
            )
        if any(c.key == "trash" for c in chosen):
            lines.append("\n[b $warning]Emptying the Trash can't be undone.[/]")
        total = sum(c.result.size or 0 for c in chosen)
        self.app.push_screen(
            ConfirmScreen(f"Clean up about {human(total)}?", "\n".join(lines), [("go", "Clean", "error")]),
            lambda answer: answer and self.call_after_refresh(self._clean, chosen),
        )

    def _clean(self, chosen: list[Category]) -> None:
        terminal = [c for c in chosen if c.runs_in_terminal]
        if terminal:
            commands = [cmd for c in terminal for cmd in c.commands()]
            if not run_in_terminal(self.app, "cleanup", commands):
                self.app.notify("Some system cleanup steps didn't finish.", severity="warning")
        self._clean_local([c for c in chosen if not c.runs_in_terminal])

    @work(thread=True, exclusive=True, group="cleanup-clean")
    def _clean_local(self, chosen: list[Category]) -> None:
        freed = sum(c.clean() for c in chosen)
        if chosen:
            self.app.call_from_thread(self.app.notify, f"Freed {human(freed)} from your caches.")
        self.app.call_from_thread(self.action_scan)


class LargeFilesPane(Vertical):
    BINDINGS = [
        Binding("t", "trash", "Move to Trash"),
        Binding("o", "open", "Open folder"),
        Binding("m", "threshold", "Min size"),
        Binding("r", "scan", "Rescan"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.threshold = THRESHOLDS[0]
        self.files: dict[str, LargeFile] = {}
        self.scanned = False

    def compose(self) -> ComposeResult:
        yield Static("", id="large-intro", classes="intro")
        yield DataTable(cursor_type="row", zebra_stripes=True, id="large-table")
        yield Static("", id="large-summary", classes="summary")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Size", key="size", width=10)
        table.add_column("Modified", key="modified", width=12)
        table.add_column("Path", key="path")
        self._update_intro()

    def _update_intro(self) -> None:
        self.query_one("#large-intro", Static).update(
            f"Files in your home folder over [b]{human(self.threshold)}[/] ([b]m[/] to change)."
            " Removing moves them to the Trash."
        )

    def ensure_scanned(self) -> None:
        if not self.scanned:
            self.action_scan()

    def action_threshold(self) -> None:
        index = (THRESHOLDS.index(self.threshold) + 1) % len(THRESHOLDS)
        self.threshold = THRESHOLDS[index]
        self._update_intro()
        self.action_scan()

    def _status(self, text: str) -> None:
        self.query_one("#large-summary", Static).update(text)

    @work(thread=True, exclusive=True, group="large-scan")
    def action_scan(self) -> None:
        self.scanned = True
        worker = get_current_worker()
        self.app.call_from_thread(self._status, "Scanning your home folder…")
        files = find_large_files(
            HOME,
            self.threshold,
            cancelled=lambda: worker.is_cancelled,
            progress=lambda n: self.app.call_from_thread(self._status, f"Scanning… {n:,} folders"),
        )
        if not worker.is_cancelled:
            self.app.call_from_thread(self._show, files)

    def _show(self, files: list[LargeFile]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self.files = {}
        for f in files:
            key = str(f.path)
            self.files[key] = f
            table.add_row(
                Text(human(f.size), style="bold"),
                datetime.fromtimestamp(f.modified).strftime("%Y-%m-%d"),
                tilde(f.path),
                key=key,
            )
        total = sum(f.size for f in files)
        self._status(f"{len(files)} files, {human(total)} in total" if files else "No files that big. Nice.")

    def _current(self) -> LargeFile | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        return self.files.get(table.ordered_rows[table.cursor_row].key.value)

    def action_open(self) -> None:
        if f := self._current():
            open_folder(f.path.parent)

    def action_trash(self) -> None:
        f = self._current()
        if f is None:
            return
        self.app.push_screen(
            ConfirmScreen(
                "Move to Trash?",
                f"[b]{escape(tilde(f.path))}[/]\n{human(f.size)}, last changed "
                f"{datetime.fromtimestamp(f.modified):%Y-%m-%d}",
                [("go", "Move to Trash", "error")],
            ),
            lambda answer: answer and self._trash(f),
        )

    def _trash(self, f: LargeFile) -> None:
        if move_to_trash(f.path):
            self.query_one(DataTable).remove_row(str(f.path))
            del self.files[str(f.path)]
            self.app.notify(f"Moved {f.path.name} to the Trash.")
        else:
            self.app.notify(f"Couldn't move {f.path.name} to the Trash.", severity="error")


class PackagesPane(Vertical):
    BINDINGS = [
        Binding("u", "uninstall", "Uninstall"),
        Binding("slash", "filter", "Filter"),
        Binding("r", "load", "Reload"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.packages: list[Package] = []
        self.loaded = False

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter packages…  (/ to focus, Esc to go back)", id="package-filter")
        yield DataTable(cursor_type="row", zebra_stripes=True, id="package-table")
        yield Static("", id="package-summary", classes="summary")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Package", key="name", width=28)
        table.add_column("Size", key="size", width=10)
        table.add_column("From", key="from", width=6)
        table.add_column("Description", key="description")

    def ensure_loaded(self) -> None:
        if not self.loaded:
            self.action_load()

    @work(thread=True, exclusive=True, group="packages")
    def action_load(self) -> None:
        self.loaded = True
        self.app.call_from_thread(self.query_one("#package-summary", Static).update, "Reading pacman database…")
        packages = installed_packages()
        self.app.call_from_thread(self._loaded, packages)

    def _loaded(self, packages: list[Package]) -> None:
        self.packages = packages
        self._fill()

    def _fill(self) -> None:
        needle = self.query_one(Input).value.strip().lower()
        table = self.query_one(DataTable)
        table.clear()
        shown = [p for p in self.packages if needle in p.name.lower() or needle in p.description.lower()]
        for p in shown:
            name = Text(p.name, style="dim" if p.protected else "")
            table.add_row(
                name,
                Text(human(p.size), style="bold"),
                Text("AUR", style=color(self.app, "accent")) if p.foreign else Text("repo", style="dim"),
                Text(p.description, style="dim"),
                key=p.name,
            )
        summary = f"{len(shown)} explicitly installed packages, {human(sum(p.size for p in shown))}"
        if not self.packages:
            summary = "No packages found (is this an Arch-based system?)"
        self.query_one("#package-summary", Static).update(summary + "  ·  Enter or [b]u[/] to uninstall")

    @on(Input.Changed, "#package-filter")
    def _filter_changed(self) -> None:
        self._fill()

    @on(Input.Submitted, "#package-filter")
    def _filter_done(self) -> None:
        self.query_one(DataTable).focus()

    def on_key(self, event) -> None:
        if event.key == "escape" and self.query_one(Input).has_focus:
            self.query_one(DataTable).focus()
            event.stop()

    def action_filter(self) -> None:
        self.query_one(Input).focus()

    @on(DataTable.RowSelected, "#package-table")
    def _row_selected(self) -> None:
        self.action_uninstall()

    def action_uninstall(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        name = table.ordered_rows[table.cursor_row].key.value
        package = next(p for p in self.packages if p.name == name)
        if package.protected:
            self.app.notify(f"{name} is part of the core system — Headroom won't remove it.", severity="warning")
            return
        self._prepare_uninstall(package)

    @work(thread=True, exclusive=True, group="leftovers")
    def _prepare_uninstall(self, package: Package) -> None:
        leftovers = find_leftovers(package.name)
        self.app.call_from_thread(self._confirm_uninstall, package, leftovers)

    def _confirm_uninstall(self, package: Package, leftovers) -> None:
        lines = [f"[b]{escape(package.name)}[/] {escape(package.version)}  ·  {human(package.size)}"]
        if package.description:
            lines.append(f"[dim]{escape(package.description)}[/]")
        if package.required_by:
            lines.append(f"\n[$warning]Needed by: {escape(', '.join(package.required_by))}[/] — pacman will refuse.")
        lines.append("\nRuns [b]sudo pacman -Rns[/] in the terminal; pacman shows what goes and asks first.")
        buttons = [("pkg", "Uninstall", "error")]
        if leftovers:
            total = sum(size for _, size in leftovers)
            lines.append(f"\nLeftovers in your home folder ({human(total)}):")
            lines += [f"  • {escape(tilde(path))}  [dim]{human(size)}[/]" for path, size in leftovers]
            lines.append("[dim]Check these are really this app's — they go to the Trash.[/]")
            buttons.append(("all", "Uninstall + leftovers", "error"))
        self.app.push_screen(
            ConfirmScreen(f"Uninstall {package.name}?", "\n".join(lines), buttons),
            lambda answer: answer and self.call_after_refresh(
                self._uninstall, package, [p for p, _ in leftovers] if answer == "all" else []
            ),
        )

    def _uninstall(self, package: Package, leftovers) -> None:
        if not run_in_terminal(self.app, f"uninstall {package.name}", [["sudo", "pacman", "-Rns", package.name]]):
            self.app.notify(f"{package.name} wasn't uninstalled.", severity="warning")
            self.action_load()
            return
        failed = [p for p in leftovers if not move_to_trash(p)]
        message = f"Uninstalled {package.name}"
        if leftovers:
            message += f" and moved {len(leftovers) - len(failed)} leftovers to the Trash"
        self.app.notify(message + ".")
        if failed:
            self.app.notify(f"Couldn't trash: {', '.join(tilde(p) for p in failed)}", severity="error")
        self.action_load()


class HeadroomApp(App):
    TITLE = "Headroom"
    SUB_TITLE = f"disk space for Linux · v{__version__}"
    CSS = """
    .intro { padding: 0 1; color: $text-muted; height: auto; }
    .summary { padding: 0 1; height: 1; background: $panel; }
    DataTable { height: 1fr; }
    #package-filter { margin: 0 0 1 0; }
    ConfirmScreen { align: center middle; }
    #dialog {
        width: 80; max-width: 95%; height: auto; max-height: 85%;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    #dialog-title { text-style: bold; margin-bottom: 1; }
    #dialog-body { height: auto; max-height: 20; }
    #dialog-buttons { height: auto; margin-top: 1; align-horizontal: right; }
    #dialog-buttons Button { margin-left: 1; }
    """
    BINDINGS = [
        Binding("1", "show_tab('cleanup')", "Cleanup", show=False),
        Binding("2", "show_tab('large')", "Large files", show=False),
        Binding("3", "show_tab('packages')", "Packages", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, categories: list[Category] | None = None):
        super().__init__()
        self._categories = categories

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="cleanup"):
            with TabPane("1 Cleanup", id="cleanup"):
                yield CleanupPane(self._categories)
            with TabPane("2 Large Files", id="large"):
                yield LargeFilesPane()
            with TabPane("3 Packages", id="packages"):
                yield PackagesPane()
        yield Footer()

    def on_mount(self) -> None:
        theme = omarchy_theme()
        if theme is not None:
            self.register_theme(theme)
            self.theme = theme.name
        else:
            self.theme = FALLBACK
        self.query_one("#cleanup-table").focus()

    def action_show_tab(self, tab: str) -> None:
        if isinstance(self.focused, Input):
            return
        self.query_one(TabbedContent).active = tab

    @on(TabbedContent.TabActivated)
    def _tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = event.pane.id
        if pane_id == "large":
            self.query_one(LargeFilesPane).ensure_scanned()
            self.query_one("#large-table").focus()
        elif pane_id == "packages":
            self.query_one(PackagesPane).ensure_loaded()
            self.query_one("#package-table").focus()
        else:
            self.query_one("#cleanup-table").focus()
