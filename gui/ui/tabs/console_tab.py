"""SCPI console tab with autocomplete and history.

IMPORTANT protocol note for GPIB: only commands ending in '?' produce a
response. Bare commands are sent with write(); a read after a bare
command would hang until the adapter timeout. After a write the error
queue is polled once so mistakes surface immediately.
"""

import logging
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QTextEdit, QCompleter)
from PyQt5.QtCore import Qt, QStringListModel
from ...commands.e3632a_commands import COMMANDS, COMMAND_NAMES

log = logging.getLogger(__name__)


class ConsoleTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._instrument = None
        self._history = []
        self._history_pos = -1

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setObjectName("consoleOutput")
        layout.addWidget(self._output, 1)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Enter SCPI command, e.g. APPL 5, 1  or  MEAS:VOLT?")
        self._input.setObjectName("consoleInput")
        self._model = QStringListModel(COMMAND_NAMES)
        completer = QCompleter(self._model)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(completer.PopupCompletion)
        self._input.setCompleter(completer)
        self._input.returnPressed.connect(self._send_command)
        input_row.addWidget(self._input, 1)

        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._send_command)
        input_row.addWidget(self._send_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._output.clear)
        input_row.addWidget(clear_btn)
        layout.addLayout(input_row)

        hint = QLabel("Queries end with '?'. Bare commands are written, then SYST:ERR? is checked.")
        hint.setObjectName("subtitleLabel")
        layout.addWidget(hint)

    def set_instrument(self, instrument):
        self._instrument = instrument

    def log(self, text):
        self._output.append(text)

    def _send_command(self):
        if not self._instrument or not self._instrument.connected:
            self._output.append("! Not connected")
            return
        cmd = self._input.text().strip()
        if not cmd:
            return
        self._history.append(cmd)
        self._history_pos = len(self._history)
        self._input.clear()
        self._output.append(f">> {cmd}")
        try:
            if cmd.rstrip().endswith("?"):
                reply = self._instrument.query(cmd)
                self._output.append(f"<< {reply if reply else '(no response)'}")
            else:
                self._instrument.write(cmd)
                err = self._instrument.get_error()
                if err and not err.startswith("+0"):
                    self._output.append(f"<< ERR {err}")
                else:
                    self._output.append("<< ok")
        except Exception as e:  # noqa: BLE001
            self._output.append(f"! Error: {e}")
            log.error("Console command failed: %s", e)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Up:
            if self._history_pos > 0:
                self._history_pos -= 1
                self._input.setText(self._history[self._history_pos])
        elif event.key() == Qt.Key_Down:
            if self._history_pos < len(self._history) - 1:
                self._history_pos += 1
                self._input.setText(self._history[self._history_pos])
            else:
                self._history_pos = len(self._history)
                self._input.clear()
        else:
            super().keyPressEvent(event)
