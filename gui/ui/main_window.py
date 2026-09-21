"""
Agilent E3632A main application window.

NI InstrumentStudio-style 3-pane layout mirroring adce7352a:
  Left:   connection, range, setpoints, output, protection, trigger, system
  Center: live V/I bar + tabs (plot, log, console, status)
"""

import logging
import time
from collections import deque

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QGridLayout, QSplitter, QScrollArea, QLabel,
                             QMessageBox, QTabWidget, QPushButton, QGroupBox,
                             QComboBox, QCheckBox, QLineEdit, QSpinBox,
                             QDoubleSpinBox, QAbstractSpinBox, QTextEdit,
                             QStatusBar, QAction, QFrame, QRadioButton)

from ..core.config import AppConfig
from ..core.theme import ThemeColors
from ..core.meter import EnergyMeter, resistance, fmt_resistance, resistance_unit
from ..commands.e3632a_commands import RANGES

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self._app = app
        self._instrument = None
        self._worker = None
        self._t0 = None
        self._last_v = self._last_i = None
        self._last_out = False
        self._last_mode = "?"
        self._last_p = 0.0
        self._last_e_wh = 0.0
        self._last_r = None
        self._meter = EnergyMeter()

        self._config = AppConfig()
        self._theme = ThemeColors(True)

        self.setWindowTitle("Agilent E3632A  —  DC Power Supply Controller  [GPIB]")
        self.setMinimumSize(1100, 780)

        geo = self._config.restore_window_geometry()
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1380, 880)
        state = self._config.restore_window_state()
        if state:
            self.restoreState(state)

        self._load_themes()
        self._build_menu()
        self._build_central()
        self._build_status_bar()
        self._restore_ui_state()

    # -- setup ------------------------------------------------------------
    def setup_instrument(self, instrument):
        self._instrument = instrument

    def _load_themes(self):
        import os
        base = os.path.join(os.path.dirname(__file__), "..", "resources")
        self._dark_qss = self._light_qss = ""
        try:
            with open(os.path.join(base, "styles.qss")) as f:
                self._dark_qss = f.read()
            with open(os.path.join(base, "light.qss")) as f:
                self._light_qss = f.read()
        except OSError as e:
            log.warning("Could not load theme files: %s", e)

    def _toggle_theme(self, use_dark):
        self._theme = ThemeColors(use_dark)
        self._app.setStyleSheet(self._dark_qss if use_dark else self._light_qss)
        if hasattr(self, "_plot_tab"):
            self._plot_tab.set_theme(use_dark)
        self.update_status(self._instrument is not None
                           and self._instrument.connected)
        self._sb.showMessage("Dark theme" if use_dark else "Light theme")

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = self.menuBar().addMenu("&View")
        self._action_dark = QAction("Dark Theme", self, checkable=True)
        self._action_dark.setChecked(True)
        self._action_dark.triggered.connect(self._toggle_theme)
        view_menu.addAction(self._action_dark)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # -- layout --------------------------------------------------------------
    def _build_central(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(270)
        left_scroll.setMaximumWidth(410)
        left_scroll.setWidget(self._build_left_panel())

        right_panel = self._build_right_panel()
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(left_scroll)
        self._splitter.addWidget(right_panel)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([320, 1060])
        root.addWidget(self._splitter, 1)

    def _build_left_panel(self):
        panel = QWidget()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        title = QLabel("Agilent E3632A")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        subtitle = QLabel("DC Power Supply  [GPIB · SCPI]")
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(subtitle)

        dot_row = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_label = QLabel("DISCONNECTED")
        dot_row.addWidget(self._status_dot)
        dot_row.addWidget(self._status_label)
        dot_row.addStretch()
        layout.addLayout(dot_row)

        layout.addWidget(self._build_connection_section())
        layout.addWidget(self._build_range_section())
        layout.addWidget(self._build_setpoint_section())
        layout.addWidget(self._build_protection_section())
        layout.addWidget(self._build_trigger_section())
        layout.addWidget(self._build_system_section())
        layout.addStretch()
        return panel

    def _grp(self, title):
        return QGroupBox(title)

    def _btn(self, text, callback):
        b = QPushButton(text)
        b.clicked.connect(callback)
        return b

    # -- left sections ----------------------------------------------------------
    def _build_connection_section(self):
        g = self._grp("CONNECTION")
        layout = QVBoxLayout(g)

        layout.addWidget(QLabel("Backend:"))
        self._backend_label = QLabel("NI GPIB-USB-HS")
        self._backend_label.setObjectName("idnLabel")
        layout.addWidget(self._backend_label)

        addr_row = QHBoxLayout()
        addr_row.addWidget(QLabel("GPIB addr:"))
        self._addr_spin = QSpinBox()
        self._addr_spin.setRange(0, 30)
        self._addr_spin.setValue(1)
        addr_row.addWidget(self._addr_spin)
        addr_row.addStretch()
        layout.addLayout(addr_row)

        btn_row = QHBoxLayout()
        self._connect_btn = self._btn("CONNECT", self._toggle_connection)
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._btn("IDN?", self._query_idn))
        layout.addLayout(btn_row)

        self._idn_label = QLabel("—")
        self._idn_label.setObjectName("idnLabel")
        self._idn_label.setWordWrap(True)
        layout.addWidget(self._idn_label)
        return g

    def _build_range_section(self):
        g = self._grp("OUTPUT RANGE")
        layout = QVBoxLayout(g)
        self._range_p15 = QRadioButton("15V / 7A  (LOW)")
        self._range_p30 = QRadioButton("30V / 4A  (HIGH)")
        self._range_p15.setChecked(True)
        layout.addWidget(self._range_p15)
        layout.addWidget(self._range_p30)
        layout.addWidget(self._btn("SET RANGE", self._set_range))
        return g

    def _build_setpoint_section(self):
        g = self._grp("SETPOINTS  (APPLy)")
        layout = QVBoxLayout(g)

        v_row = QHBoxLayout()
        v_row.addWidget(QLabel("Voltage:"))
        self._v_spin = QDoubleSpinBox()
        self._v_spin.setDecimals(4)
        self._v_spin.setRange(0.0, 15.45)
        self._v_spin.setValue(5.0)
        self._v_spin.setSuffix(" V")
        v_row.addWidget(self._v_spin)
        layout.addLayout(v_row)

        i_row = QHBoxLayout()
        i_row.addWidget(QLabel("Current:"))
        self._i_spin = QDoubleSpinBox()
        self._i_spin.setDecimals(4)
        self._i_spin.setRange(0.0, 7.21)
        self._i_spin.setValue(1.0)
        self._i_spin.setSuffix(" A")
        i_row.addWidget(self._i_spin)
        layout.addLayout(i_row)

        layout.addWidget(self._btn("APPLY  V + I", self._apply_setpoints))

        step_row = QHBoxLayout()
        step_row.addWidget(self._btn("V −", lambda: self._step("V", -1)))
        step_row.addWidget(self._btn("V +", lambda: self._step("V", +1)))
        step_row.addWidget(self._btn("I −", lambda: self._step("I", -1)))
        step_row.addWidget(self._btn("I +", lambda: self._step("I", +1)))
        layout.addLayout(step_row)

        mon_row = QHBoxLayout()
        mon_row.addWidget(QLabel("Monitor (ms):"))
        self._interval_edit = QLineEdit("500")
        self._interval_edit.setMaximumWidth(70)
        mon_row.addWidget(self._interval_edit)
        mon_row.addStretch()
        layout.addLayout(mon_row)

        acq_row = QHBoxLayout()
        self._start_btn = self._btn("▶ START", self._start_mon)
        self._stop_btn = self._btn("■ STOP", self._stop_mon)
        self._stop_btn.setEnabled(False)
        acq_row.addWidget(self._start_btn)
        acq_row.addWidget(self._stop_btn)
        layout.addLayout(acq_row)
        layout.addWidget(self._btn("READ SETPOINTS (APPL?)", self._read_setpoints))
        keys_hint = QLabel("Keys: Space=ON/OFF   +/−=V±0.1   Ctrl++/−=I±0.1")
        keys_hint.setObjectName("idnLabel")
        layout.addWidget(keys_hint)
        return g

    def _build_protection_section(self):
        g = self._grp("PROTECTION  (OVP / OCP)")
        layout = QVBoxLayout(g)

        ovp_row = QHBoxLayout()
        ovp_row.addWidget(QLabel("OVP:"))
        self._ovp_spin = QDoubleSpinBox()
        self._ovp_spin.setDecimals(3)
        self._ovp_spin.setRange(0.0, 33.0)
        self._ovp_spin.setValue(5.75)
        self._ovp_spin.setSuffix(" V")
        ovp_row.addWidget(self._ovp_spin)
        self._ovp_state = QCheckBox("ON")
        self._ovp_state.setChecked(True)
        ovp_row.addWidget(self._ovp_state)
        layout.addLayout(ovp_row)
        ovp_btns = QHBoxLayout()
        ovp_btns.addWidget(self._btn("SET OVP", self._set_ovp))
        ovp_btns.addWidget(self._btn("CLEAR", self._clear_ovp))
        self._ovp_trip = QLabel("")
        ovp_btns.addWidget(self._ovp_trip)
        layout.addLayout(ovp_btns)

        ocp_row = QHBoxLayout()
        ocp_row.addWidget(QLabel("OCP:"))
        self._ocp_spin = QDoubleSpinBox()
        self._ocp_spin.setDecimals(4)
        self._ocp_spin.setRange(0.0, 7.5)
        self._ocp_spin.setValue(0.8)
        self._ocp_spin.setSuffix(" A")
        ocp_row.addWidget(self._ocp_spin)
        self._ocp_state = QCheckBox("ON")
        self._ocp_state.setChecked(True)
        ocp_row.addWidget(self._ocp_state)
        layout.addLayout(ocp_row)
        ocp_btns = QHBoxLayout()
        ocp_btns.addWidget(self._btn("SET OCP", self._set_ocp))
        ocp_btns.addWidget(self._btn("CLEAR", self._clear_ocp))
        self._ocp_trip = QLabel("")
        ocp_btns.addWidget(self._ocp_trip)
        layout.addLayout(ocp_btns)
        return g

    def _build_trigger_section(self):
        g = self._grp("TRIGGER")
        layout = QVBoxLayout(g)
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Source:"))
        self._trig_src = QComboBox()
        self._trig_src.addItems(["BUS", "IMM"])
        src_row.addWidget(self._trig_src)
        src_row.addWidget(QLabel("Delay s:"))
        self._trig_delay = QDoubleSpinBox()
        self._trig_delay.setRange(0.0, 3600.0)
        self._trig_delay.setDecimals(2)
        src_row.addWidget(self._trig_delay)
        layout.addLayout(src_row)

        lvl_row = QHBoxLayout()
        lvl_row.addWidget(QLabel("Vtrig:"))
        self._vtrig_spin = QDoubleSpinBox()
        self._vtrig_spin.setDecimals(4)
        self._vtrig_spin.setRange(0.0, 15.45)
        lvl_row.addWidget(self._vtrig_spin)
        lvl_row.addWidget(QLabel("Itrig:"))
        self._itrig_spin = QDoubleSpinBox()
        self._itrig_spin.setDecimals(4)
        self._itrig_spin.setRange(0.0, 7.21)
        lvl_row.addWidget(self._itrig_spin)
        layout.addLayout(lvl_row)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn("SET TRIG", self._set_trigger))
        btn_row.addWidget(self._btn("INIT", self._init_trig))
        btn_row.addWidget(self._btn("*TRG", self._bus_trig))
        layout.addLayout(btn_row)
        return g

    def _build_system_section(self):
        g = self._grp("SYSTEM")
        layout = QVBoxLayout(g)
        row1 = QHBoxLayout()
        row1.addWidget(self._btn("*RST", self._do_reset))
        row1.addWidget(self._btn("*TST?", self._do_selftest))
        row1.addWidget(self._btn("BEEP", self._do_beep))
        layout.addLayout(row1)
        row2 = QHBoxLayout()
        self._disp_check = QCheckBox("Display ON")
        self._disp_check.setChecked(True)
        self._disp_check.toggled.connect(self._toggle_display)
        row2.addWidget(self._disp_check)
        row2.addWidget(self._btn("ERR?", self._read_error))
        row2.addWidget(self._btn("GO TO LOCAL", self._go_to_local))
        layout.addLayout(row2)
        msg_row = QHBoxLayout()
        self._disp_msg = QLineEdit()
        self._disp_msg.setPlaceholderText("Display msg ≤12ch")
        self._disp_msg.setMaxLength(12)
        msg_row.addWidget(self._disp_msg)
        msg_row.addWidget(self._btn("SHOW", self._show_msg))
        layout.addLayout(msg_row)
        mem_row = QHBoxLayout()
        mem_row.addWidget(QLabel("Mem:"))
        self._mem_slot = QComboBox()
        self._mem_slot.addItems(["1", "2", "3"])
        mem_row.addWidget(self._mem_slot)
        mem_row.addWidget(self._btn("SAVE", self._save_state))
        mem_row.addWidget(self._btn("RECALL", self._recall_state))
        layout.addLayout(mem_row)
        return g

    # -- right panel ------------------------------------------------------------
    def _build_right_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        live_bar = QFrame()
        live_bar.setObjectName("liveBar")
        live_layout = QHBoxLayout(live_bar)
        live_layout.setContentsMargins(10, 6, 10, 6)

        # Left: 3 rows x 2 columns (V/I, setpoints, P/R/E)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(0)

        v_box = QHBoxLayout()
        v_box.addWidget(self._live_label("V:", "26px"))
        self._live_v = self._live_label("— — — —", "26px")
        self._live_v.setObjectName("liveValV")
        v_box.addWidget(self._live_v)
        self._unit_v = self._live_label("V", "26px")
        v_box.addWidget(self._unit_v)
        grid.addLayout(v_box, 0, 0)

        i_box = QHBoxLayout()
        i_box.addWidget(self._live_label("I:", "26px"))
        self._live_i = self._live_label("— — — —", "26px")
        self._live_i.setObjectName("liveValI")
        i_box.addWidget(self._live_i)
        self._unit_i = self._live_label("A", "26px")
        i_box.addWidget(self._unit_i)
        grid.addLayout(i_box, 0, 1)

        self._set_v_lbl = self._set_label("set —")
        grid.addWidget(self._set_v_lbl, 1, 0)
        self._set_i_lbl = self._set_label("set —")
        grid.addWidget(self._set_i_lbl, 1, 1)

        p_box = QHBoxLayout()
        p_box.addWidget(self._live_label("P:", "20px"))
        self._live_p = self._live_label("0.0000", "20px")
        self._live_p.setObjectName("liveValP")
        p_box.addWidget(self._live_p)
        p_box.addWidget(self._live_label("W", "20px"))
        grid.addLayout(p_box, 2, 0)

        r_box = QHBoxLayout()
        r_box.addWidget(self._live_label("R:", "20px"))
        self._live_r = self._live_label("—", "20px")
        self._live_r.setObjectName("liveValR")
        r_box.addWidget(self._live_r)
        self._unit_r = self._live_label("Ω", "20px")
        r_box.addWidget(self._unit_r)
        grid.addLayout(r_box, 2, 1)

        e_box = QHBoxLayout()
        e_box.addWidget(self._live_label("E:", "20px"))
        self._live_e = self._live_label("0.000000", "20px")
        self._live_e.setObjectName("liveValE")
        e_box.addWidget(self._live_e)
        e_box.addWidget(self._live_label("Wh", "20px"))
        self._energy_reset_btn = QPushButton("⟲")
        self._energy_reset_btn.setToolTip("Reset energy accumulator (Wh/J)")
        self._energy_reset_btn.setMaximumWidth(32)
        self._energy_reset_btn.clicked.connect(self._reset_energy)
        e_box.addWidget(self._energy_reset_btn)
        grid.addLayout(e_box, 2, 2)
        live_layout.addLayout(grid)

        live_layout.addStretch()

        # Right: output control column
        ctrl_box = QVBoxLayout()
        ctrl_box.setSpacing(2)
        self._output_btn = QPushButton("OUTPUT: OFF")
        self._output_btn.setObjectName("outputBtnOff")
        self._output_btn.clicked.connect(self._toggle_output)
        ctrl_box.addWidget(self._output_btn)
        badge_row = QHBoxLayout()
        self._mode_badge = QLabel("OFF")
        self._mode_badge.setObjectName("modeBadge")
        badge_row.addWidget(self._mode_badge)
        self._prot_badge = QLabel("OVP·OCP OK")
        self._prot_badge.setObjectName("protBadge")
        badge_row.addWidget(self._prot_badge)
        ctrl_box.addLayout(badge_row)
        self._live_sub = self._live_label("", "10px")
        self._live_sub.setObjectName("liveSubheader")
        ctrl_box.addWidget(self._live_sub)
        live_layout.addLayout(ctrl_box)
        layout.addWidget(live_bar)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        from .tabs.console_tab import ConsoleTab
        from .tabs.log_tab import LogTab
        from .tabs.status_tab import StatusTab
        from ..plotting.vi_plot import PlotTab

        self._plot_tab = PlotTab()
        self._tabs.addTab(self._plot_tab, "  Live Plot  ")
        self._log_tab = LogTab()
        self._tabs.addTab(self._log_tab, "  Log / Export  ")
        self._console_tab = ConsoleTab()
        self._tabs.addTab(self._console_tab, "  Console  ")
        self._status_tab = StatusTab()
        self._status_tab.bind(lambda: self._instrument, self)
        self._tabs.addTab(self._status_tab, "  Status  ")
        layout.addWidget(self._tabs, 1)
        return widget

    def _live_label(self, text, size="14px"):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: {size}; font-weight: bold;")
        return lbl

    def _set_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("setpointLabel")
        return lbl

    def _sep(self):
        s = QLabel("  |  ")
        s.setObjectName("liveSep")
        return s

    def _build_status_bar(self):
        self._sb = QStatusBar()
        self.setStatusBar(self._sb)
        self._sb.showMessage("Ready  |  GPIB  |  Disconnected")

    def _show_about(self):
        QMessageBox.about(
            self, "About E3632A Controller",
            "Agilent E3632A DC Power Supply Controller\n"
            "GPIB via ni-gpib-usb-hs (user-space NI GPIB-USB-HS driver)\n"
            "Version 1.0.0\n\n"
            "SCPI command set per E3632A User's Guide, Ch. 4.")

    # -- connection --------------------------------------------------------
    def update_status(self, connected):
        t = self._theme
        if connected:
            self._status_dot.setStyleSheet(f"color: {t.conn_ok}; font-size: 14px;")
            self._status_label.setText("CONNECTED")
            self._status_label.setStyleSheet(
                f"color: {t.conn_ok}; font-weight: bold; font-size: 10px;")
            self._connect_btn.setText("DISCONNECT")
            addr = self._addr_spin.value()
            self._sb.showMessage(f"Connected  |  GPIB::{addr}  |  NI GPIB-USB-HS")
        else:
            self._status_dot.setStyleSheet(f"color: {t.conn_err}; font-size: 14px;")
            self._status_label.setText("DISCONNECTED")
            self._status_label.setStyleSheet(
                f"color: {t.conn_err}; font-weight: bold; font-size: 10px;")
            self._connect_btn.setText("CONNECT")
            self._sb.showMessage("Disconnected  |  GPIB")

    def _toggle_connection(self):
        if self._instrument and self._instrument.connected:
            self._disconnect()
        else:
            self._connect()

    def _require(self):
        if not self._instrument or not self._instrument.connected:
            QMessageBox.warning(self, "Not Connected", "Connect to the instrument first")
            return None
        return self._instrument

    def _connect(self):
        from ..instruments.e3632a import E3632A
        addr = self._addr_spin.value()
        self._instrument = E3632A(use_mock=False, gpib_addr=addr)
        if self._instrument.connect():
            self._console_tab.set_instrument(self._instrument)
            self.update_status(True)
            self._query_idn()
            self._sync_from_instrument()
        else:
            err = self._instrument.last_error_text()
            QMessageBox.critical(self, "Connection Error",
                                 f"Failed to connect (GPIB::{addr}).\n{err}")
            self._instrument = None

    def _disconnect(self):
        self._stop_mon()
        if self._instrument:
            # Return the supply to front-panel control first: the adapter
            # keeps REN asserted after the USB session closes, otherwise
            # the instrument stays in Rmt with a locked panel.
            self._instrument.go_to_local()
            self._instrument.disconnect()
        self.update_status(False)

    def _query_idn(self):
        inst = self._require() if False else (self._instrument or None)
        if inst and inst.connected:
            idn = inst.get_idn()
            if idn:
                self._idn_label.setText(idn)

    # -- sync ------------------------------------------------------------------
    def _sync_from_instrument(self):
        inst = self._instrument
        if not inst:
            return
        rng = inst.get_range() or "P15V"
        self._set_range_ui(rng)
        appl = inst.get_apply()
        if appl:
            self._v_spin.setValue(min(appl[0], self._v_spin.maximum()))
            self._i_spin.setValue(min(appl[1], self._i_spin.maximum()))
        out = inst.is_output_on()
        self._paint_output(out)
        ovp = inst.get_ovp()
        if ovp is not None:
            self._ovp_spin.setValue(min(ovp, 33.0))
        self._ovp_state.setChecked(inst.get_ovp_state())
        ocp = inst.get_ocp()
        if ocp is not None:
            self._ocp_spin.setValue(min(ocp, 7.5))
        self._ocp_state.setChecked(inst.get_ocp_state())
        self._status_tab.refresh()

    def _set_range_ui(self, rng):
        if rng == "P30V":
            self._range_p30.setChecked(True)
        else:
            self._range_p15.setChecked(True)
        lim = RANGES[rng]
        for spin, key in ((self._v_spin, "v_max"), (self._i_spin, "i_max"),
                          (self._vtrig_spin, "v_max"), (self._itrig_spin, "i_max")):
            spin.setMaximum(lim[key])
        self._live_sub.setText(f"Range: {rng}  ({lim['label']})")

    # -- actions -------------------------------------------------------------------
    def _set_range(self):
        inst = self._require()
        if not inst:
            return
        rng = "P30V" if self._range_p30.isChecked() else "P15V"
        got = inst.set_range(rng)
        self._set_range_ui(got)
        self._sb.showMessage(f"Range → {got}")

    def _apply_setpoints(self):
        inst = self._require()
        if not inst:
            return
        v, i = inst.apply(self._v_spin.value(), self._i_spin.value())
        err = inst.get_error()
        if err and not err.startswith("+0"):
            QMessageBox.warning(self, "Instrument Error", err)
        self._sb.showMessage(f"APPL {v:.4f} V, {i:.4f} A")

    def _read_setpoints(self):
        inst = self._require()
        if not inst:
            return
        appl = inst.get_apply()
        if appl:
            self._v_spin.setValue(min(appl[0], self._v_spin.maximum()))
            self._i_spin.setValue(min(appl[1], self._i_spin.maximum()))
            self._sb.showMessage(f"Setpoints: {appl[0]:.5f} V, {appl[1]:.5f} A")

    def _step(self, which, direction):
        inst = self._require()
        if not inst:
            return
        if which == "V":
            inst.step_voltage(direction)
            v = inst.get_voltage_setting()
            if v is not None:
                self._v_spin.setValue(min(v, self._v_spin.maximum()))
        else:
            inst.step_current(direction)
            i = inst.get_current_setting()
            if i is not None:
                self._i_spin.setValue(min(i, self._i_spin.maximum()))

    def _paint_output(self, on):
        t = self._theme
        if on:
            self._output_btn.setText("OUTPUT: ON")
            self._output_btn.setStyleSheet(
                f"color: {t.btn_danger}; font-weight: bold; font-size: 13px;")
        else:
            self._output_btn.setText("OUTPUT: OFF")
            self._output_btn.setStyleSheet("")

    def _toggle_output(self):
        inst = self._require()
        if not inst:
            return
        turning_on = not inst.is_output_on()
        inst.output(turning_on)
        time.sleep(0.15)
        on = inst.is_output_on()
        self._paint_output(on)
        err = inst.get_error()
        if err and not err.startswith("+0"):
            QMessageBox.warning(self, "Instrument Error", err)
        self._sb.showMessage(f"Output {'ON' if on else 'OFF'}")
        # Starting the output also starts monitoring (if idle) so the
        # turn-on transient is captured; monitoring keeps running after
        # the output is switched off.
        if on and (self._worker is None or not self._worker.isRunning()):
            self._start_mon()

    # -- keyboard control -------------------------------------------------------
    # Space = output ON/OFF, +/− = V±0.1 V, Ctrl + +/− = I±0.1 A.
    # Applied to the instrument immediately on keypress (key autorepeat
    # gives continuous ramping). Typing in edits/spins/combos is never
    # hijacked.
    def keyPressEvent(self, event):  # noqa: N802
        focus = self.focusWidget()
        if isinstance(focus, (QLineEdit, QAbstractSpinBox, QTextEdit, QComboBox)):
            super().keyPressEvent(event)
            return
        mods = event.modifiers()
        if mods & (Qt.AltModifier | Qt.MetaModifier):
            super().keyPressEvent(event)
            return
        ctrl = bool(mods & Qt.ControlModifier)
        key = event.key()
        if key == Qt.Key_Space and not ctrl:
            if self._instrument and self._instrument.connected:
                self._toggle_output()
            else:
                self._sb.showMessage("Not connected — Space ignored")
            event.accept()
            return
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            self._nudge_current(+0.1) if ctrl else self._nudge_voltage(+0.1)
            event.accept()
            return
        if key in (Qt.Key_Minus, Qt.Key_Underscore):
            self._nudge_current(-0.1) if ctrl else self._nudge_voltage(-0.1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _nudge_voltage(self, dv):
        """Immediate V±0.1 step on keypress."""
        self._nudge(dv, None)

    def _nudge_current(self, di):
        """Immediate I±0.1 step on keypress (Ctrl modifier)."""
        self._nudge(None, di)

    def _nudge(self, dv, di):
        """Immediate ±0.1 step on keypress (dv for V, di for I)."""
        inst = self._instrument
        if not inst or not inst.connected:
            self._sb.showMessage("Not connected — key ignored")
            return
        if dv:
            v = inst.set_voltage(self._v_spin.value() + dv)
            self._v_spin.setValue(min(v, self._v_spin.maximum()))
            self._sb.showMessage(f"V → {v:.4f} V  (key)")
        if di:
            i = inst.set_current(self._i_spin.value() + di)
            self._i_spin.setValue(min(i, self._i_spin.maximum()))
            self._sb.showMessage(f"I → {i:.4f} A  (key)")

    def _set_ovp(self):
        inst = self._require()
        if not inst:
            return
        v = inst.set_ovp(self._ovp_spin.value())
        inst.set_ovp_state(self._ovp_state.isChecked())
        self._sb.showMessage(f"OVP {v:.3f} V {'ON' if self._ovp_state.isChecked() else 'OFF'}")

    def _clear_ovp(self):
        inst = self._require()
        if not inst:
            return
        inst.clear_ovp()
        self._ovp_trip.setText("cleared" if not inst.ovp_tripped() else "TRIPPED")

    def _set_ocp(self):
        inst = self._require()
        if not inst:
            return
        i = inst.set_ocp(self._ocp_spin.value())
        inst.set_ocp_state(self._ocp_state.isChecked())
        self._sb.showMessage(f"OCP {i:.4f} A {'ON' if self._ocp_state.isChecked() else 'OFF'}")

    def _clear_ocp(self):
        inst = self._require()
        if not inst:
            return
        inst.clear_ocp()
        self._ocp_trip.setText("cleared" if not inst.ocp_tripped() else "TRIPPED")

    def _set_trigger(self):
        inst = self._require()
        if not inst:
            return
        inst.set_trigger_source(self._trig_src.currentText())
        inst.set_trigger_delay(self._trig_delay.value())
        inst.set_triggered_levels(self._vtrig_spin.value(), self._itrig_spin.value())
        self._sb.showMessage("Trigger settings applied")

    def _init_trig(self):
        inst = self._require()
        if inst:
            inst.initiate()
            self._sb.showMessage("INIT sent")

    def _bus_trig(self):
        inst = self._require()
        if inst:
            inst.bus_trigger()
            self._sb.showMessage("*TRG sent")

    def _do_reset(self):
        inst = self._require()
        if not inst:
            return
        if QMessageBox.question(self, "Confirm *RST",
                                "*RST resets output, range and protection "
                                "to power-on state. Continue?") != QMessageBox.Yes:
            return
        inst.reset()
        self._sync_from_instrument()
        self._sb.showMessage("*RST done")

    def _do_selftest(self):
        inst = self._require()
        if inst:
            QMessageBox.information(self, "Self-Test", f"*TST? -> {inst.selftest()} (0 = pass)")

    def _do_beep(self):
        inst = self._require()
        if inst:
            inst.beep()

    def _toggle_display(self, on):
        inst = self._instrument
        if inst and inst.connected:
            inst.display(on)

    def _go_to_local(self):
        inst = self._require()
        if inst:
            if inst.go_to_local():
                self._sb.showMessage("GTL sent — front-panel control restored")
            else:
                self._sb.showMessage("Go-to-local failed (see log)")

    def _read_error(self):
        inst = self._require()
        if inst:
            QMessageBox.information(self, "Error Queue", inst.get_error() or "(no response)")

    def _show_msg(self):
        inst = self._require()
        if inst:
            inst.display_text(self._disp_msg.text())

    def _save_state(self):
        inst = self._require()
        if inst:
            inst.save(self._mem_slot.currentText())
            self._sb.showMessage(f"State saved to {self._mem_slot.currentText()}")

    def _recall_state(self):
        inst = self._require()
        if inst:
            inst.recall(self._mem_slot.currentText())
            self._sync_from_instrument()
            self._sb.showMessage(f"State recalled from {self._mem_slot.currentText()}")

    def _reset_energy(self):
        self._meter.reset()
        self._last_p, self._last_e_wh = 0.0, 0.0
        self._live_p.setText("0.0000")
        self._live_e.setText("0.000000")
        self._live_e.setToolTip("0.0 J")
        self._sb.showMessage("Energy accumulator reset")

    # -- monitoring ----------------------------------------------------------------------
    def _start_mon(self):
        inst = self._require()
        if not inst:
            return
        from ..core.worker import MonitorWorker
        try:
            iv = int(self._interval_edit.text())
        except ValueError:
            iv = 500
        iv = max(100, iv)
        self._t0 = time.time()
        self._meter.reset()
        self._worker = MonitorWorker(inst, self)
        self._worker.set_interval(iv)
        self._worker.set_buffer_size(self._plot_tab.buf_spin.value())
        self._worker.reading.connect(self._on_reading)
        self._worker.plot_data.connect(self._on_plot)
        self._worker.protection.connect(self._on_protection)
        self._worker.error_occurred.connect(self._on_worker_error)
        self._worker.start()
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._sb.showMessage(f"Monitoring  interval={iv} ms")

    def _stop_mon(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        self._worker = None
        if hasattr(self, "_start_btn"):
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)
            self._sb.showMessage("Monitoring stopped")

    def _on_reading(self, t, v, i, out_on, v_set, i_set):
        th = self._theme
        self._last_v, self._last_i, self._last_out = v, i, out_on
        p, e_wh = self._meter.update(t, v, i)
        self._last_p, self._last_e_wh = p, e_wh
        r_ohm = resistance(v, i)
        self._last_r = r_ohm
        self._live_v.setText(f"{v:.4f}")
        self._live_i.setText(f"{i:.4f}")
        self._live_v.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {th.live_ok_v};")
        self._live_i.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {th.live_ok_i};")
        self._live_p.setText(f"{p:.4f}")
        self._live_p.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {th.accent_a};")
        self._live_r.setText(fmt_resistance(r_ohm))
        self._live_r.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {th.live_warn};")
        self._unit_r.setText(resistance_unit(r_ohm))
        self._live_e.setText(f"{e_wh:.6f}")
        self._live_e.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {th.accent_b};")
        self._live_e.setToolTip(f"{self._meter.joules:.2f} J")
        self._set_v_lbl.setText(f"set {v_set:.4f} V" if v_set is not None else "set —")
        self._set_i_lbl.setText(f"set {i_set:.4f} A" if i_set is not None else "set —")
        self._log_tab.write_reading(t, v, i, out_on, p, e_wh, r_ohm)

    def _on_plot(self, ts, vs, is_, outs, modes):
        self._plot_tab.set_data(ts, vs, is_, outs)
        mode = modes[-1] if modes else "?"
        out_on = outs[-1] if outs else False
        self._last_mode = mode
        th = self._theme
        if out_on:
            self._mode_badge.setText(mode)
            color = th.conn_ok
        else:
            self._mode_badge.setText("OFF")
            color = th.live_warn
        self._mode_badge.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {color};")
        if vs and is_:
            self._status_tab.update_live(vs[-1], is_[-1], out_on, mode,
                                         self._last_p, self._last_e_wh,
                                         self._last_r)

    def _on_protection(self, ovp_trip, ocp_trip):
        th = self._theme
        self._ovp_trip.setText("TRIPPED" if ovp_trip else "")
        self._ocp_trip.setText("TRIPPED" if ocp_trip else "")
        if ovp_trip and ocp_trip:
            txt, color = "OVP+OCP TRIP", th.live_ol
        elif ovp_trip:
            txt, color = "OVP TRIPPED", th.live_ol
        elif ocp_trip:
            txt, color = "OCP TRIPPED", th.live_ol
        else:
            txt, color = "OVP·OCP OK", th.conn_ok
        self._prot_badge.setText(txt)
        self._prot_badge.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {color};")

    def _on_worker_error(self, msg):
        self._sb.showMessage(f"Monitor: {msg}")

    # -- persistence ---------------------------------------------------------------------------
    def _restore_ui_state(self):
        self._addr_spin.setValue(self._config.restore_gpib_addr())
        self._interval_edit.setText(str(self._config.restore_read_interval()))
        self._set_range_ui(self._config.restore_range())
        is_dark = self._config.restore_dark_theme()
        self._action_dark.setChecked(is_dark)
        self._toggle_theme(is_dark)

    def closeEvent(self, event):  # noqa: N802
        self._stop_mon()
        if hasattr(self, "_log_tab"):
            self._log_tab.close()
        if self._instrument:
            try:
                self._instrument.go_to_local()
                self._instrument.disconnect()
            except Exception:
                pass
        self._config.save_window_geometry(self.saveGeometry())
        self._config.save_window_state(self.saveState())
        self._config.save_gpib_addr(self._addr_spin.value())
        try:
            self._config.save_read_interval(int(self._interval_edit.text()))
        except ValueError:
            pass
        self._config.save_range("P30V" if self._range_p30.isChecked() else "P15V")
        self._config.save_dark_theme(self._action_dark.isChecked())
        self._config.sync()
        super().closeEvent(event)
