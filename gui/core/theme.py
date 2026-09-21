"""Dynamic color scheme per theme (mirrors adce7352a)."""


class ThemeColors:
    def __init__(self, is_dark=True):
        self._d = is_dark

    @property
    def conn_ok(self):
        return "#3fb950" if self._d else "#1a7f37"

    @property
    def conn_err(self):
        return "#f85149" if self._d else "#cf222e"

    @property
    def live_ok_v(self):
        return "#00ff80" if self._d else "#00884d"

    @property
    def live_ok_i(self):
        return "#00d9ff" if self._d else "#006b99"

    @property
    def live_warn(self):
        return "#e3b341" if self._d else "#9a6700"

    @property
    def live_ol(self):
        return "#f85149" if self._d else "#cf222e"

    @property
    def accent_a(self):
        return "#58a6ff" if self._d else "#0969da"

    @property
    def accent_b(self):
        return "#bc8cff" if self._d else "#8250df"

    @property
    def btn_start(self):
        return "#3fb950" if self._d else "#1a7f37"

    @property
    def btn_stop(self):
        return "#d29922" if self._d else "#9a6700"

    @property
    def btn_danger(self):
        return "#f85149" if self._d else "#cf222e"

    @property
    def btn_default(self):
        return "#8b949e" if self._d else "#656d76"

    @property
    def status_ok(self):
        return "#3fb950" if self._d else "#1a7f37"

    @property
    def status_err(self):
        return "#f85149" if self._d else "#cf222e"

    @property
    def plot_bg(self):
        return "#0d1117" if self._d else "#ffffff"

    @property
    def plot_grid(self):
        return "#21262d" if self._d else "#d0d7de"

    @property
    def plot_text(self):
        return "#8b949e" if self._d else "#656d76"
