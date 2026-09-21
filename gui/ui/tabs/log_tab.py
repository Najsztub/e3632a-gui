"""CSV logging / export tab for monitor data."""

import csv
import logging
import os
import time
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QComboBox, QCheckBox, QTextEdit,
                             QFileDialog)

log = logging.getLogger(__name__)


class LogTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._file = None
        self._writer = None
        self._path = ""
        self._rows = 0

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["CSV", "TXT"])
        row.addWidget(self._fmt)
        self._ts_check = QCheckBox("Timestamp column")
        self._ts_check.setChecked(True)
        row.addWidget(self._ts_check)
        row.addStretch()
        layout.addLayout(row)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("START LOGGING")
        self._start_btn.clicked.connect(self.start_logging)
        btn_row.addWidget(self._start_btn)
        self._stop_btn = QPushButton("STOP")
        self._stop_btn.clicked.connect(self.stop_logging)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._stop_btn)
        layout.addLayout(btn_row)

        self._info = QLabel("Not logging")
        self._info.setObjectName("idnLabel")
        layout.addWidget(self._info)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setObjectName("exportLogDisplay")
        self._log_view.setMaximumHeight(160)
        layout.addWidget(self._log_view)
        layout.addStretch()

    @property
    def active(self):
        return self._file is not None

    def start_logging(self):
        if self._file:
            return
        default = time.strftime("e3632a_log_%Y%m%d_%H%M%S.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Log file", default,
                                              "CSV (*.csv);;Text (*.txt)")
        if not path:
            return
        try:
            self._file = open(path, "w", newline="")
            self._path = path
            if self._fmt.currentText() == "CSV":
                self._writer = csv.writer(self._file)
                hdr = ["t_s", "V_meas", "I_meas", "output_on", "P_W", "R_Ohm", "E_Wh"]
                if self._ts_check.isChecked():
                    hdr.append("wall_time")
                self._writer.writerow(hdr)
            else:
                self._writer = None
                self._file.write("# t_s V_meas I_meas output_on P_W R_Ohm E_Wh\n")
            self._rows = 0
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            self._info.setText(f"Logging → {os.path.basename(path)}")
            self._log_view.append(f"Opened {path}")
        except OSError as e:
            self._log_view.append(f"! Cannot open file: {e}")

    def stop_logging(self):
        self.close_file()

    def write_reading(self, t, v, i, out_on, p=None, e_wh=None, r_ohm=None):
        if not self._file:
            return
        i_c = max(0.0, i)
        p = v * i_c if p is None else p
        e_wh = 0.0 if e_wh is None else e_wh
        if r_ohm is None:
            r_ohm = v / i_c if i_c >= 5e-4 else None
        r_txt = f"{r_ohm:.6f}" if r_ohm is not None else ""
        try:
            if self._writer:
                row = [f"{t:.3f}", f"{v:.6f}", f"{i:.6f}", int(bool(out_on)),
                       f"{p:.6f}", r_txt, f"{e_wh:.9f}"]
                if self._ts_check.isChecked():
                    row.append(time.strftime("%Y-%m-%d %H:%M:%S"))
                self._writer.writerow(row)
            else:
                self._file.write(f"{t:.3f} {v:.6f} {i:.6f} {int(bool(out_on))} "
                                 f"{p:.6f} {r_txt} {e_wh:.9f}\n")
            self._rows += 1
            if self._rows % 10 == 0:
                self._file.flush()
                self._info.setText(f"Logging → {os.path.basename(self._path)} ({self._rows} rows)")
        except OSError as e:
            self._log_view.append(f"! Write error: {e}")
            self.close_file()

    def close_file(self):
        if self._file:
            try:
                self._file.close()
            except OSError:
                pass
            self._log_view.append(f"Closed {self._path} ({self._rows} rows)")
        self._file = None
        self._writer = None
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._info.setText("Not logging")

    def close(self):
        self.close_file()
