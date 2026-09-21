"""Status tab: protection state, error queue, status registers, self-test."""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextEdit, QGridLayout)


class StatusTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._instrument = None
        self._main = None

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        grid = QGridLayout()
        grid.setSpacing(4)
        self._rows = {}
        for r, key in enumerate(["OUTP", "MODE", "RANGE", "Vset", "Iset",
                                 "P (W)", "R (Ω)", "Energy (Wh)",
                                 "OVP", "OVP state", "OVP trip",
                                 "OCP", "OCP state", "OCP trip",
                                 "TRIG src", "TRIG delay"]):
            lbl = QLabel(key + ":")
            val = QLabel("—")
            val.setProperty("statChannel", "a")
            grid.addWidget(lbl, r, 0)
            grid.addWidget(val, r, 1)
            self._rows[key] = val
        layout.addLayout(grid)

        btn_row = QHBoxLayout()
        self._refresh_btn = QPushButton("REFRESH")
        self._refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self._refresh_btn)
        self._err_btn = QPushButton("DRAIN ERRORS")
        self._err_btn.clicked.connect(self.drain_errors)
        btn_row.addWidget(self._err_btn)
        self._tst_btn = QPushButton("SELF-TEST")
        self._tst_btn.clicked.connect(self.selftest)
        btn_row.addWidget(self._tst_btn)
        self._regs_btn = QPushButton("REGISTERS")
        self._regs_btn.clicked.connect(self.read_registers)
        btn_row.addWidget(self._regs_btn)
        layout.addLayout(btn_row)

        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setObjectName("exportLogDisplay")
        layout.addWidget(self._view, 1)

    def bind(self, instrument_getter, main_window):
        self._instrument = instrument_getter
        self._main = main_window

    def _inst(self):
        return self._instrument() if self._instrument else None

    def _set(self, key, text):
        if key in self._rows:
            self._rows[key].setText(text)

    def refresh(self):
        inst = self._inst()
        if not inst or not inst.connected:
            self._view.append("! Not connected")
            return
        try:
            out = inst.is_output_on()
            appl = inst.get_apply() or (None, None)
            ovp, ocp = inst.get_ovp(), inst.get_ocp()
            self._set("OUTP", "ON" if out else "OFF")
            self._set("RANGE", inst.get_range())
            self._set("Vset", f"{appl[0]:.5f} V" if appl[0] is not None else "—")
            self._set("Iset", f"{appl[1]:.5f} A" if appl[1] is not None else "—")
            self._set("OVP", f"{ovp:.3f} V" if ovp is not None else "—")
            self._set("OVP state", "ON" if inst.get_ovp_state() else "OFF")
            self._set("OVP trip", "TRIPPED" if inst.ovp_tripped() else "ok")
            self._set("OCP", f"{ocp:.4f} A" if ocp is not None else "—")
            self._set("OCP state", "ON" if inst.get_ocp_state() else "OFF")
            self._set("OCP trip", "TRIPPED" if inst.ocp_tripped() else "ok")
            self._set("TRIG src", str(inst.get_trigger_source() or "—"))
            td = inst.get_trigger_delay()
            self._set("TRIG delay", f"{td:.3f} s" if td is not None else "—")
            self._view.append("Status refreshed")
        except Exception as e:  # noqa: BLE001
            self._view.append(f"! Refresh failed: {e}")

    def drain_errors(self):
        inst = self._inst()
        if not inst or not inst.connected:
            self._view.append("! Not connected")
            return
        for e in inst.drain_errors():
            self._view.append(f"ERR {e}")

    def selftest(self):
        inst = self._inst()
        if not inst or not inst.connected:
            self._view.append("! Not connected")
            return
        self._view.append(f"*TST? -> {inst.selftest()}  (0 = pass)")

    def read_registers(self):
        inst = self._inst()
        if not inst or not inst.connected:
            self._view.append("! Not connected")
            return
        self._view.append(f"*IDN?  -> {inst.get_idn()}")
        self._view.append(f"SYST:VERS? -> {inst.get_version()}")
        self._view.append(f"*STB? -> {inst.status_byte()}")
        self._view.append(f"*ESR? -> {inst.event_status()}")
        self._view.append(f"STAT:QUES:COND? -> {inst.questionable_condition()}")
        self._view.append(f"STAT:QUES:EVEN? -> {inst.questionable_event()}")
        self._view.append(f"CAL:COUN? -> {inst.calibration_count()}")

    def update_live(self, v, i, out_on, mode, p=None, e_wh=None, r_ohm=None):
        self._set("MODE", f"{mode}  ({'ON' if out_on else 'OFF'})")
        if p is not None:
            self._set("P (W)", f"{p:.4f}")
        if r_ohm is not None:
            from ...core.meter import fmt_resistance, resistance_unit
            self._set("R (Ω)", f"{fmt_resistance(r_ohm)} {resistance_unit(r_ohm)}")
        elif r_ohm is None and p is not None:
            self._set("R (Ω)", "—")
        if e_wh is not None:
            self._set("Energy (Wh)", f"{e_wh:.6f}  ({e_wh * 3600.0:.1f} J)")
