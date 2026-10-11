from textual.widgets import DataTable

from headroom.app import CleanupPane, ConfirmScreen, HeadroomApp
from headroom.cleanup import Category, ScanResult


class FakeCategory(Category):
    def __init__(self, key, size, terminal=False):
        super().__init__(key, key.title(), "fake")
        self.size, self.terminal, self.cleaned = size, terminal, False

    def scan(self):
        return ScanResult(0 if self.cleaned else self.size, "fake detail")

    def commands(self):
        return [["true"]] if self.terminal else []

    def clean(self):
        self.cleaned = True
        return self.size


async def wait_for_scan(pilot, pane):
    for _ in range(50):
        await pilot.pause(0.05)
        if all(c.result for c in pane.categories.values()):
            return


async def test_cleanup_flow():
    cats = [FakeCategory("alpha", 1024**2), FakeCategory("beta", 2 * 1024**2)]
    app = HeadroomApp(categories=cats)
    async with app.run_test(size=(120, 40)) as pilot:
        pane = app.query_one(CleanupPane)
        await wait_for_scan(pilot, pane)
        assert pane.selected == {"alpha", "beta"}

        await pilot.press("space")  # deselect alpha (cursor on first row)
        assert pane.selected == {"beta"}

        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("escape")  # cancel does nothing
        assert not any(c.cleaned for c in cats)

        await pilot.press("c")
        await pilot.pause()
        await pilot.click("#go")
        for _ in range(50):
            await pilot.pause(0.05)
            if cats[1].cleaned:
                break
        assert cats[1].cleaned and not cats[0].cleaned


async def test_tabs_open_without_crashing(tmp_path, monkeypatch):
    import headroom.app as app_module

    monkeypatch.setattr(app_module, "HOME", tmp_path)
    monkeypatch.setattr(app_module, "installed_packages", lambda: [])
    app = HeadroomApp(categories=[FakeCategory("alpha", 0)])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("2")
        await pilot.pause(0.3)
        assert app.focused is app.query_one("#large-table", DataTable)
        await pilot.press("m", "3")
        await pilot.pause(0.3)
        assert app.focused is app.query_one("#package-table", DataTable)
        await pilot.press("slash")
        await pilot.press("f", "o", "o")  # typing in the filter must not switch tabs
        await pilot.press("escape", "1")
        await pilot.pause()
        assert app.focused is app.query_one("#cleanup-table", DataTable)
