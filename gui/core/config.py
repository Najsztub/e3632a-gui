"""Settings persistence via QSettings (mirrors adce7352a layout)."""

from PyQt5.QtCore import QSettings

ORGANIZATION = "Elektro"
APPLICATION = "E3632A"


class AppConfig:
    def __init__(self):
        self._s = QSettings(ORGANIZATION, APPLICATION)

    def save_window_geometry(self, geometry):
        self._s.setValue("window/geometry", geometry)

    def restore_window_geometry(self):
        return self._s.value("window/geometry")

    def save_window_state(self, state):
        self._s.setValue("window/state", state)

    def restore_window_state(self):
        return self._s.value("window/state")

    def save_gpib_addr(self, addr):
        self._s.setValue("connection/gpib_addr", int(addr))

    def restore_gpib_addr(self):
        return self._s.value("connection/gpib_addr", 1, type=int)

    def save_use_mock(self, use_mock):
        self._s.setValue("connection/use_mock", bool(use_mock))

    def restore_use_mock(self):
        return self._s.value("connection/use_mock", True, type=bool)

    def save_read_interval(self, ms):
        self._s.setValue("acquisition/read_interval", int(ms))

    def restore_read_interval(self):
        return self._s.value("acquisition/read_interval", 500, type=int)

    def save_range(self, rng):
        self._s.setValue("instrument/range", rng)

    def restore_range(self):
        return self._s.value("instrument/range", "P15V")

    def save_console_history(self, history):
        self._s.setValue("console/history", history)

    def restore_console_history(self):
        return self._s.value("console/history", [])

    def save_dark_theme(self, is_dark):
        self._s.setValue("theme/dark", bool(is_dark))

    def restore_dark_theme(self):
        return self._s.value("theme/dark", True, type=bool)

    def sync(self):
        self._s.sync()
