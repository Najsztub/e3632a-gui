"""
GPIB transport backend for the E3632A over the NI GPIB-USB-HS adapter.

Uses the pure-Python user-space driver from
https://github.com/embeddedci-com/ni-gpib-usb-hs
(pyusb + libusb, no NI-488.2 / linux-gpib kernel module needed):

    from ni_gpib_usb_hs import NIUSBGPIB
    with NIUSBGPIB() as gpib:
        gpib.query(addr, "*IDN?")

One NIUSBGPIB session is kept open while connected; all access is
serialized with a lock because the monitor worker and the GUI thread
share the session.
"""

import logging
import time
import threading

log = logging.getLogger(__name__)


class GPIBBackend:
    """Thin thread-safe wrapper around NIUSBGPIB for a single address."""

    DEFAULT_ADDR = 1
    SETTLE_S = 0.05  # E3632A GPIB processing time between commands

    def __init__(self, addr: int = DEFAULT_ADDR):
        self._addr = int(addr)
        self._gpib = None
        self._lock = threading.RLock()
        self._connected = False
        self.last_error = ""

    # -- properties -----------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._connected and self._gpib is not None

    @property
    def addr(self) -> int:
        return self._addr

    # -- lifecycle ------------------------------------------------------
    def connect(self) -> bool:
        if self.connected:
            return True
        try:
            from ni_gpib_usb_hs import NIUSBGPIB
        except ImportError as e:
            self.last_error = f"ni-gpib-usb-hs not installed: {e}"
            log.error(self.last_error)
            return False
        try:
            with self._lock:
                self._gpib = NIUSBGPIB()
                # Session init performs the adapter handshake + TNT4882 setup.
                idn = self._gpib.query(self._addr, "*IDN?")
            self._connected = True
            log.info("GPIB connected, addr=%d idn=%r", self._addr, idn)
            return True
        except Exception as e:
            log.error("GPIB connect error (addr %d): %s", self._addr, e)
            # The adapter occasionally wedges on the bulk/control handshake
            # (observed on this host after several open/close cycles).
            # A libusb device reset usually revives it without a re-plug.
            if self._usb_reset():
                try:
                    time.sleep(1.0)
                    self._gpib = NIUSBGPIB()
                    idn = self._gpib.query(self._addr, "*IDN?")
                    self._connected = True
                    log.info("GPIB connected after USB reset, addr=%d idn=%r",
                             self._addr, idn)
                    return True
                except Exception as e2:
                    e = e2
                    log.error("GPIB connect after reset failed: %s", e2)
            self.last_error = str(e)
            self._gpib = None
            self._connected = False
            return False

    @staticmethod
    def _usb_reset() -> bool:
        """Soft-reset the NI adapter USB interface; False on any problem."""
        try:
            import usb.core
            import usb.util
            dev = usb.core.find(idVendor=0x3923, idProduct=0x709b)
            if dev is None:
                return False
            dev.reset()
            usb.util.dispose_resources(dev)
            return True
        except Exception as e:
            log.error("USB reset failed: %s", e)
            return False

    def disconnect(self):
        with self._lock:
            if self._gpib is not None:
                try:
                    self._gpib.close()
                except Exception:
                    pass
            self._gpib = None
            self._connected = False
        log.info("GPIB disconnected")

    # -- I/O ------------------------------------------------------------
    def _check(self) -> bool:
        if not self.connected:
            log.warning("GPIB not connected")
            return False
        return True

    def write(self, cmd: str):
        if not self._check():
            return
        with self._lock:
            try:
                self._gpib.write(self._addr, cmd)
                time.sleep(self.SETTLE_S)
            except Exception as e:
                self.last_error = str(e)
                log.error("GPIB write error %r: %s", cmd, e)

    def query(self, cmd: str, length: int = 512) -> str | None:
        if not self._check():
            return None
        with self._lock:
            try:
                resp = self._gpib.query(self._addr, cmd, length=length)
                time.sleep(self.SETTLE_S)
                return resp.strip() if resp is not None else None
            except Exception as e:
                self.last_error = str(e)
                log.error("GPIB query error %r: %s", cmd, e)
                return None

    def read(self, length: int = 512) -> str | None:
        if not self._check():
            return None
        with self._lock:
            try:
                raw = self._gpib.read(self._addr, length=length)
                if isinstance(raw, (bytes, bytearray)):
                    return bytes(raw).decode("ascii", errors="replace").strip()
                return str(raw).strip() if raw is not None else None
            except Exception as e:
                self.last_error = str(e)
                log.error("GPIB read error: %s", e)
                return None

    def write_with_err_check(self, cmd: str) -> bool:
        self.write(cmd)
        err = self.query("SYST:ERR?")
        if err and not err.startswith("+0"):
            log.warning("SYST:ERR after %r: %s", cmd, err)
            self.last_error = err
            return False
        return True

    # IEEE-488 command bytes: UNL (unlisten), LAD base (listen addr + pad),
    # GTL 0x01 (addressed "Go To Local").
    # NOTE: 0x11 is LLO (Local Lockout) — the exact command that disables
    # the front panel. Do not confuse it with GTL.
    _UNL = 0x3F
    _GTL = 0x01

    def go_to_local(self) -> bool:
        """Return the instrument to front-panel control (GTL).

        The adapter stays system controller, so REN remains asserted;
        the addressed GTL command (device listener-addressed, ATN
        asserted) puts the device back in local mode where it stays
        until the next addressed bus command, and also releases a
        previously set Local Lockout (LLO). A dead bus must never
        break disconnect, so failures return False instead of raising.
        """
        if not self.connected:
            return False
        with self._lock:
            try:
                self._gpib.command([self._UNL, 0x20 + self._addr, self._GTL])
                time.sleep(self.SETTLE_S)
                return True
            except Exception as e:
                self.last_error = str(e)
                log.error("GPIB GTL error (addr %d): %s", self._addr, e)
                return False
