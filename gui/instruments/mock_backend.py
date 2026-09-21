"""
Mock backend simulating an Agilent E3632A power supply.

Implements the same surface as GPIBBackend (connect/disconnect/
connected/write/query/read/write_with_err_check) with a simple
CV/CC load model:

    I_out = min(Iset, Vset / Rload)      (when output ON)
    V_out = min(Vset, Iset * Rload)

OVP/OCP trip when the corresponding limit is exceeded while the
protection state is ON. An error queue emulates SYST:ERR?.
"""

import logging
import re

from ..commands.e3632a_commands import RANGES, range_of, OVP_RST, OCP_RST

log = logging.getLogger(__name__)


class MockBackend:
    def __init__(self, addr: int = 1):
        self._addr = int(addr)
        self._connected = False
        self.last_error = ""
        self.rload = 10.0  # simulated load in ohms

        self.v_set = 5.0
        self.i_set = 7.0
        self.range = "P15V"
        self.output = False
        self.ovp_level = 5.75
        self.ovp_state = True
        self.ovp_tripped = False
        self.ocp_level = 0.8
        self.ocp_state = True
        self.ocp_tripped = False
        self.v_trig = 0.0
        self.i_trig = 7.0
        self.trig_src = "BUS"
        self.trig_delay = 0.0
        self.v_step = 0.00055
        self.i_step = 0.00012
        self.display = True
        self.disp_text = ""
        self.relay = False
        self.mem = {}
        self.errors = []
        self.remote = False  # mirrors REN+addressing: any bus traffic -> remote
        self.idn = "HEWLETT-PACKARD,E3632A,0,1.2-5.0-1.0 (MOCK)"

    # -- lifecycle ------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def addr(self) -> int:
        return self._addr

    def connect(self) -> bool:
        self._connected = True
        log.info("Mock connected")
        return True

    def disconnect(self):
        self._connected = False
        log.info("Mock disconnected")

    # -- model ----------------------------------------------------------
    def _meas(self):
        if not self.output or self.ovp_tripped or self.ocp_tripped:
            return 0.0, 0.0
        v_oc, i_lim = self.v_set, self.i_set
        i_want = v_oc / self.rload if self.rload > 0 else i_lim
        if i_want <= i_lim:
            return v_oc, i_want
        return i_lim * self.rload, i_lim

    def _check_protection(self):
        v, i = self._meas_raw()
        if self.ovp_state and v > self.ovp_level:
            self.ovp_tripped = True
        if self.ocp_state and i > self.ocp_level:
            self.ocp_tripped = True

    def _meas_raw(self):
        if not self.output:
            return 0.0, 0.0
        i_want = self.v_set / self.rload if self.rload > 0 else self.i_set
        if i_want <= self.i_set:
            return self.v_set, i_want
        return self.i_set * self.rload, self.i_set

    def _push_err(self, code, msg):
        if len(self.errors) < 20:
            self.errors.append((code, msg))

    @staticmethod
    def _tail_after(token, text):
        """Return text after the first occurrence of token (stripped)."""
        idx = text.find(token)
        if idx < 0:
            return ""
        return text[idx + len(token):].strip().lstrip(":").strip()

    def _strip_kw(self, tail, *keywords):
        """Strip leading SCPI keywords (longest first) from tail."""
        t = tail.strip()
        changed = True
        while changed:
            changed = False
            for kw in sorted(keywords, key=len, reverse=True):
                if t.upper().startswith(kw):
                    t = t[len(kw):].strip().lstrip(":").strip()
                    changed = True
        return t

    # -- I/O ------------------------------------------------------------
    def write(self, cmd: str):
        if not self._connected:
            return
        self.remote = True
        self._exec(cmd.strip(), want_reply=False)

    def query(self, cmd: str, length: int = 512) -> str | None:
        if not self._connected:
            return None
        self.remote = True
        return self._exec(cmd.strip(), want_reply=True)

    def read(self, length: int = 512) -> str | None:
        return None

    def write_with_err_check(self, cmd: str) -> bool:
        self.write(cmd)
        err = self.query("SYST:ERR?")
        if err and not err.startswith("+0"):
            self.last_error = err
            return False
        return True

    def go_to_local(self) -> bool:
        """Emulate IEEE-488 GTL: front-panel control restored."""
        self.remote = False
        return True

    # -- command emulation ----------------------------------------------
    def _exec(self, cmd, want_reply):
        c = cmd.upper()
        r = RANGES[self.range]

        def num(tail):
            tail = tail.strip()
            if tail in ("MIN", "MINIMUM"):
                return 0.0
            if tail in ("MAX", "MAXIMUM"):
                return None  # caller resolves
            if tail == "DEF":
                return None
            try:
                return float(tail)
            except ValueError:
                self._push_err(-102, "Syntax error")
                return None

        # --- identification / system ------------------------------------
        if c == "*IDN?":
            return self.idn if want_reply else None
        if c == "SYST:VERS?":
            return "1996.0" if want_reply else None
        if c == "SYST:ERR?":
            if self.errors:
                code, msg = self.errors.pop(0)
                return f'{code},"{msg}"'
            return '+0,"No error"'
        if c == "SYST:BEEP":
            return None
        if c in ("SYST:LOC", "SYST:REM", "SYST:RWLOCK",
                 "SYSTEM:LOCAL", "SYSTEM:REMOTE"):
            return None
        if c == "*CLS":
            self.errors.clear()
            return None
        if c == "*RST":
            self.v_set, self.i_set = 0.0, 7.0
            self.range = "P15V"
            self.output = False
            self.ovp_level, self.ovp_state = OVP_RST, True
            self.ocp_level, self.ocp_state = OCP_RST, True
            self.ovp_tripped = self.ocp_tripped = False
            self.trig_src, self.trig_delay = "BUS", 0.0
            self.display = True
            return None
        if c == "*TST?":
            return "0" if want_reply else None
        if c == "*OPC?":
            return "1" if want_reply else None
        if c in ("*OPC", "*WAI", "*TRG"):
            if c == "*TRG" and self.trig_src == "BUS":
                self.v_set = min(self.v_trig, r["v_max"])
                self.i_set = min(self.i_trig, r["i_max"])
            return "1" if (want_reply and c == "*OPC") else None
        m = re.match(r"\*(SAV|RCL)\s+([123])", c)
        if m:
            slot = m.group(2)
            if m.group(1) == "SAV":
                self.mem[slot] = (self.v_set, self.i_set, self.range)
            elif slot in self.mem:
                self.v_set, self.i_set, self.range = self.mem[slot]
            else:
                self._push_err(-225, "Out of memory")
            return None

        # --- APPLy -------------------------------------------------------
        if c.startswith("APPL"):
            if c == "APPL?":
                return f'"{self.v_set:.5f},{self.i_set:.5f}"'
            tail = cmd[4:].strip()
            if tail:
                parts = [p.strip() for p in tail.split(",")]
                v = self._appl_val(parts[0], r["v_max"], 0.0 if len(parts) == 1 else None)
                if v is not None:
                    self.v_set = min(v, r["v_max"])
                if len(parts) > 1:
                    i = self._appl_val(parts[1], r["i_max"], None)
                    if i is not None:
                        self.i_set = min(i, r["i_max"])
                self._check_protection()
            return None

        # --- range --------------------------------------------------------
        if c.startswith("VOLT:RANG"):
            tail = c.split("VOLT:RANG", 1)[1].strip()
            if tail.startswith("?"):
                return self.range
            alias = range_of(tail)
            self.range = alias
            r = RANGES[alias]
            self.v_set = min(self.v_set, r["v_max"])
            self.i_set = min(self.i_set, r["i_max"])
            return None

        # --- VOLT / CURR immediate ----------------------------------------
        for prefix in ("VOLT", "CURR"):
            if (c == prefix or c.startswith(prefix + " ")
                    or c.startswith(prefix + ":") or c.startswith(prefix + "?")):
                return self._immediate(prefix, c, cmd, r, want_reply)
        # --- MEASure -------------------------------------------------------
        if c in ("MEAS:VOLT?", "MEAS:VOLT:DC?", "MEAS?", "MEAS:VOLTAGE?"):
            v, _ = self._meas()
            return f"{v:+.8E}" if want_reply else None
        if c in ("MEAS:CURR?", "MEAS:CURR:DC?", "MEAS:CURRENT?"):
            _, i = self._meas()
            return f"{i:+.8E}" if want_reply else None

        # --- output ---------------------------------------------------------
        if c.startswith("OUTP"):
            if ":REL" in c:
                if c.endswith("?"):
                    return "1" if self.relay else "0"
                self.relay = c.rsplit(" ", 1)[-1] in ("1", "ON")
                return None
            if c.endswith("?") or c == "OUTP?":
                return ("1" if self.output else "0") if want_reply else None
            tail = c.rsplit(" ", 1)[-1] if " " in c else c[4:]
            if tail in ("1", "ON"):
                self.output = True
                self._check_protection()
            elif tail in ("0", "OFF"):
                self.output = False
            return None

        # --- display ---------------------------------------------------------
        if c.startswith("DISP"):
            if ":TEXT:CLE" in c:
                self.disp_text = ""
                return None
            if ":TEXT" in c:
                if c.endswith("?"):
                    return f'"{self.disp_text}"'
                m2 = re.search(r'"([^"]{0,40})"', cmd)
                if m2:
                    self.disp_text = m2.group(1)[:DISP_LEN]
                return None
            if c.endswith("?") or c == "DISP?":
                return ("1" if self.display else "0") if want_reply else None
            tail = c.rsplit(" ", 1)[-1] if " " in c else ""
            if tail in ("1", "ON"):
                self.display = True
            elif tail in ("0", "OFF"):
                self.display = False
            return None

        # --- trigger ----------------------------------------------------------
        if c.startswith("TRIG"):
            if ":DEL" in c:
                rest = self._strip_kw(self._tail_after(":DEL", c), "AY", "DELay")
                if c.rstrip().endswith("?"):
                    return f"{self.trig_delay:+.3E}" if want_reply else None
                v = num(rest)
                if v is not None:
                    self.trig_delay = max(0.0, min(3600.0, v))
                return None
            if ":SOUR" in c:
                if c.rstrip().endswith("?"):
                    return self.trig_src if want_reply else None
                rest = self._strip_kw(self._tail_after(":SOUR", c), "CE", "SOURce")
                if rest.startswith("IMM"):
                    self.trig_src = "IMM"
                elif rest.startswith("BUS"):
                    self.trig_src = "BUS"
                return None
            return None
        if c == "INIT" or c.startswith("INIT"):
            if self.trig_src == "IMM":
                self.v_set = min(self.v_trig, r["v_max"])
                self.i_set = min(self.i_trig, r["i_max"])
            return None

        # --- status ------------------------------------------------------------
        if c in ("*STB?", "*ESR?", "*ESE?", "*SRE?", "*PSC?",
                 "STAT:QUES:COND?", "STAT:QUES:EVEN?"):
            return "0" if want_reply else None
        if c.startswith("*ESE ") or c.startswith("*SRE ") or c.startswith("*PSC "):
            return None
        if c == "CAL:COUN?":
            return "1" if want_reply else None
        if c == "CAL:STR?":
            return '"MOCK CAL"' if want_reply else None

        self._push_err(-101, "Invalid character")
        return "+0,\"No error\"" if (want_reply and "ERR" in c) else None

    def _appl_val(self, token, vmax, _unused):
        t = token.strip().upper()
        if t in ("DEF", "DEFAULT"):
            return 0.0
        if t in ("MIN", "MINIMUM"):
            return 0.0
        if t in ("MAX", "MAXIMUM"):
            return vmax
        try:
            return float(t)
        except ValueError:
            self._push_err(-102, "Syntax error")
            return None

    def _immediate(self, prefix, c, cmd, r, want_reply):
        lim = r["v_max"] if prefix == "VOLT" else r["i_max"]
        cur = self.v_set if prefix == "VOLT" else self.i_set
        after = c[len(prefix):]
        # STEP
        if ":STEP" in after:
            rest = self._strip_kw(self._tail_after(":STEP", after),
                                  "INCRement", "INCR", "EMENT")
            if after.rstrip().endswith("?"):
                if "DEF" in after:
                    return (f"{0.00055:+.5E}" if prefix == "VOLT"
                            else f"{0.00012:+.5E}")
                step = self.v_step if prefix == "VOLT" else self.i_step
                return f"{step:+.5E}"
            tail = rest
            if tail in ("DEF", "DEFAULT", "DEFAUL", "DEFault".upper()):
                step = 0.00055 if prefix == "VOLT" else 0.00012
            else:
                try:
                    step = float(tail)
                except ValueError:
                    self._push_err(-102, "Syntax error")
                    return None
            if prefix == "VOLT":
                self.v_step = step
            else:
                self.i_step = step
            return None
        # TRIGgered
        if ":TRIG" in after:
            rest = self._strip_kw(self._tail_after(":TRIG", after),
                                  "GERED", "TRIGgered", ":AMPLitude",
                                  ":AMPL", "ITUDE", "AMPL")
            if after.rstrip().endswith("?"):
                t = self.v_trig if prefix == "VOLT" else self.i_trig
                if rest.startswith("MAX"):
                    return f"{lim:+.8E}"
                if rest.startswith("MIN"):
                    return "+0.00000000E+00"
                return f"{t:+.8E}"
            tail = rest
            try:
                v = {"MINIMUM": 0.0, "MIN": 0.0}.get(tail, None)
                if v is None:
                    v = lim if tail in ("MAXIMUM", "MAX") else float(tail)
            except ValueError:
                self._push_err(-102, "Syntax error")
                return None
            if prefix == "VOLT":
                self.v_trig = v
            else:
                self.i_trig = v
            return None
        # PROTection
        if ":PROT" in after:
            prot = self._tail_after(":PROT", after)
            prot = self._strip_kw(prot, "ECTION", "PROTection", "LEVEL", "LEV")
            if ":STAT" in prot or prot.startswith("STAT"):
                st = self.ovp_state if prefix == "VOLT" else self.ocp_state
                if prot.rstrip().endswith("?"):
                    return "1" if st else "0"
                tail = prot.rsplit(" ", 1)[-1]
                val = tail in ("1", "ON")
                if prefix == "VOLT":
                    self.ovp_state = val
                else:
                    self.ocp_state = val
                return None
            if "TRIP" in prot or prot.startswith("CLE"):
                if "TRIP" in prot:
                    t = self.ovp_tripped if prefix == "VOLT" else self.ocp_tripped
                    return "1" if t else "0"
                if prefix == "VOLT":
                    self.ovp_tripped = False
                else:
                    self.ocp_tripped = False
                return None
            if prot.rstrip().endswith("?"):
                tail = prot.rstrip()[:-1].strip()
                lvl = self.ovp_level if prefix == "VOLT" else self.ocp_level
                mx = 33.0 if prefix == "VOLT" else 7.5
                if tail.endswith("MAX"):
                    return f"{mx:+.8E}"
                if tail.endswith("MIN"):
                    return "+0.00000000E+00"
                return f"{lvl:+.8E}"
            tail = prot.strip().lstrip(":").strip()
            try:
                v = {"MINIMUM": 0.0, "MIN": 0.0}.get(tail)
                if v is None:
                    mx = 33.0 if prefix == "VOLT" else 7.5
                    v = mx if tail in ("MAXIMUM", "MAX") else float(tail)
            except ValueError:
                self._push_err(-102, "Syntax error")
                return None
            if prefix == "VOLT":
                self.ovp_level = v
            else:
                self.ocp_level = v
            return None
        # plain immediate value / query
        if after.rstrip().endswith("?"):
            tail = after.rstrip()[:-1].strip()
            if tail.endswith("MAX"):
                return f"{lim:+.8E}"
            if tail.endswith("MIN"):
                return "+0.00000000E+00"
            return f"{cur:+.8E}"
        tail = after.strip()
        if not tail:
            return None
        step = self.v_step if prefix == "VOLT" else self.i_step
        if tail == "UP":
            v = cur + step
        elif tail == "DOWN":
            v = cur - step
        elif tail in ("MINIMUM", "MIN"):
            v = 0.0
        elif tail in ("MAXIMUM", "MAX"):
            v = lim
        else:
            try:
                v = float(tail)
            except ValueError:
                self._push_err(-102, "Syntax error")
                return None
        if not (0.0 <= v <= lim):
            self._push_err(-222, "Data out of range")
            return None
        if prefix == "VOLT":
            self.v_set = v
        else:
            self.i_set = v
        self._check_protection()
        return None


DISP_LEN = 12
