"""
Agilent E3632A DC Power Supply Controller — Entry Point.

GPIB via the pure-Python user-space driver for the NI GPIB-USB-HS
(https://github.com/embeddedci-com/ni-gpib-usb-hs) — no NI-488.2,
no linux-gpib kernel module required.

Usage:
    python main.py             # GPIB address 1
    python main.py --addr 5    # another GPIB address
"""

import argparse
import os
import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt


def main():
    parser = argparse.ArgumentParser(description="Agilent E3632A Controller")
    parser.add_argument("--addr", type=int, default=1,
                        help="GPIB primary address (default: 1)")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("E3632A Controller")
    app.setOrganizationName("Elektro")
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    stylesheet_path = os.path.join(os.path.dirname(__file__), "gui",
                                   "resources", "styles.qss")
    if os.path.exists(stylesheet_path):
        with open(stylesheet_path) as f:
            app.setStyleSheet(f.read())

    # Late import so Qt is initialized first
    from gui.ui.main_window import MainWindow
    from gui.instruments.e3632a import E3632A

    instrument = E3632A(use_mock=False, gpib_addr=args.addr)

    win = MainWindow(app)
    win.setup_instrument(instrument)
    win.setWindowTitle(win.windowTitle() + f"  [GPIB::{args.addr}]")
    win._addr_spin.setValue(args.addr)

    win.show()

    if instrument.connect():
        win._console_tab.set_instrument(instrument)
        win.update_status(True)
        win._query_idn()
        win._sync_from_instrument()
    else:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(win, "Connection Error",
                            f"Could not open GPIB::{args.addr}.\n"
                            f"{instrument.last_error_text()}\n"
                            "Check the address, cabling and udev rule, then retry.")

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
