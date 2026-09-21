"""
E3632A SCPI command registry.

Derived from the Agilent E3632A User's Guide, Chapter 4
"Remote Interface Reference" (manual.pdf in this directory).

Covers: APPLy, SOURce (VOLT/CURR + PROT + RANG), MEASure,
trigger subsystem, DISPlay/OUTPut/SYSTem, IEEE-488.2 common
commands and STATus. Calibration commands are intentionally
excluded from the GUI (see Service Guide) but a few read-only
queries are kept for the Status tab.
"""

# ----------------------------------------------------------------------------
# Output ranges (Table 4-1, manual p. 80)
# ----------------------------------------------------------------------------
RANGES = {
    "P15V": {
        "label": "15V / 7A  (LOW)",
        "v_max": 15.45, "v_def": 0.0, "v_rst": 0.0,
        "i_max": 7.21, "i_def": 7.0, "i_rst": 7.0,
    },
    "P30V": {
        "label": "30V / 4A  (HIGH)",
        "v_max": 30.90, "v_def": 0.0, "v_rst": 0.0,
        "i_max": 4.12, "i_def": 4.0, "i_rst": 7.0,
    },
}

RANGE_ALIASES = {"P15V": "P15V", "LOW": "P15V",
                 "P30V": "P30V", "HIGH": "P30V"}

# Protection limits (*RST: OVP=32 V, OCP=7.5 A, both ON)
OVP_MAX = 33.0
OVP_RST = 32.0
OCP_MAX = 7.5
OCP_RST = 7.5

# DISPlay:TEXT holds up to 12 characters (manual p. 92)
DISP_TEXT_MAX = 12

# Trigger delay range in seconds (manual p. 91)
TRIG_DELAY_MIN = 0.0
TRIG_DELAY_MAX = 3600.0

# Step resolution at *RST (manual pp. 83/86)
VOLT_STEP_DEF = 0.00055
CURR_STEP_DEF = 0.00012


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def range_of(alias):
    """Normalize P15V/LOW/P30V/HIGH to P15V/P30V."""
    return RANGE_ALIASES.get(str(alias).upper(), "P15V")


def valid_voltage(v, rng):
    r = RANGES[range_of(rng)]
    return 0.0 <= v <= r["v_max"]


def valid_current(i, rng):
    r = RANGES[range_of(rng)]
    return 0.0 <= i <= r["i_max"]


# ----------------------------------------------------------------------------
# Autocomplete / console registry: (command, description)
# ----------------------------------------------------------------------------
COMMANDS = [
    ("APPLy <V>[,<I>]", "Set V and I in one command (p. 81)"),
    ("APPLy?", "Query programmed V,I as \"v,i\" (p. 81)"),
    ("VOLTage <V>|MIN|MAX|UP|DOWN", "Immediate voltage level (p. 85)"),
    ("VOLTage?", "Programmed voltage level (p. 85)"),
    ("VOLTage? MAX", "Highest programmable voltage for range"),
    ("VOLTage? MIN", "Lowest programmable voltage (0)"),
    ("VOLTage:STEP <V>|DEF", "Step size for VOLT UP/DOWN (p. 86)"),
    ("VOLTage:STEP? [DEF]", "Step size (DEF = min resolution)"),
    ("VOLTage:TRIGgered <V>|MIN|MAX", "Pending triggered voltage (p. 86)"),
    ("VOLTage:TRIGgered?", "Triggered voltage level"),
    ("VOLTage:PROTection <V>|MIN|MAX", "OVP trip level (p. 86)"),
    ("VOLTage:PROTection?", "OVP trip level"),
    ("VOLTage:PROTection:STATe 0|1|OFF|ON", "Enable/disable OVP (*RST=ON)"),
    ("VOLTage:PROTection:STATe?", "OVP state 0/1"),
    ("VOLTage:PROTection:TRIPped?", "1 if OVP tripped, else 0"),
    ("VOLTage:PROTection:CLEar", "Clear OVP trip"),
    ("VOLTage:RANGe P15V|P30V|LOW|HIGH", "Select output range (p. 87)"),
    ("VOLTage:RANGe?", "Selected range P15V/P30V"),
    ("CURRent <I>|MIN|MAX|UP|DOWN", "Immediate current level (p. 82)"),
    ("CURRent?", "Programmed current level (p. 83)"),
    ("CURRent? MAX", "Highest programmable current for range"),
    ("CURRent? MIN", "Lowest programmable current (0)"),
    ("CURRent:STEP <I>|DEF", "Step size for CURR UP/DOWN (p. 83)"),
    ("CURRent:STEP? [DEF]", "Step size (DEF = min resolution)"),
    ("CURRent:TRIGgered <I>|MIN|MAX", "Pending triggered current (p. 83)"),
    ("CURRent:TRIGgered?", "Triggered current level"),
    ("CURRent:PROTection <I>|MIN|MAX", "OCP trip level (p. 84)"),
    ("CURRent:PROTection?", "OCP trip level"),
    ("CURRent:PROTection:STATe 0|1|OFF|ON", "Enable/disable OCP (*RST=ON)"),
    ("CURRent:PROTection:STATe?", "OCP state 0/1"),
    ("CURRent:PROTection:TRIPped?", "1 if OCP tripped, else 0"),
    ("CURRent:PROTection:CLEar", "Clear OCP trip"),
    ("MEASure:VOLTage?", "Measured output voltage (p. 88)"),
    ("MEASure:CURRent?", "Measured output current (p. 88)"),
    ("INITiate", "Initiate trigger system (p. 91)"),
    ("TRIGger:DELay <s>|MIN|MAX", "Trigger delay 0-3600 s (p. 91)"),
    ("TRIGger:DELay?", "Trigger delay"),
    ("TRIGger:SOURce BUS|IMM", "Trigger source (*RST=BUS)"),
    ("TRIGger:SOURce?", "Trigger source BUS/IMM"),
    ("DISPlay OFF|ON", "Front-panel display (*RST=ON)"),
    ("DISPlay?", "Display state 0/1"),
    ("DISPlay:TEXT \"<msg>\"", "Show message, max 12 chars (p. 92)"),
    ("DISPlay:TEXT?", "Displayed message"),
    ("DISPlay:TEXT:CLEar", "Clear displayed message"),
    ("OUTPut OFF|ON", "Output enable (*RST=OFF)"),
    ("OUTPut?", "Output state 0/1"),
    ("OUTPut:RELay OFF|ON", "TTL relay control on RS-232 port (p. 93)"),
    ("OUTPut:RELay?", "Relay state 0/1"),
    ("SYSTem:BEEPer", "Single beep"),
    ("SYSTem:ERRor?", "Error queue FIFO (p. 93)"),
    ("SYSTem:VERSion?", "SCPI version, e.g. 1996.0"),
    ("SYSTem:LOCal", "Return to front-panel (local) control"),
    ("SYSTem:REMote", "Remote control (RS-232)"),
    ("SYSTem:RWLock", "Remote with front-panel lockout"),
    ("STATus:QUEStionable:CONDition?", "Questionable condition register"),
    ("STATus:QUEStionable:EVENt?", "Questionable event register"),
    ("STATus:QUEStionable:ENABle <n>", "Questionable enable mask"),
    ("*IDN?", "Identification string (p. 94)"),
    ("*RST", "Reset to power-on state (p. 94)"),
    ("*TST?", "Self-test, 0=pass (p. 95)"),
    ("*SAV 1|2|3", "Store state to non-volatile memory"),
    ("*RCL 1|2|3", "Recall stored state"),
    ("*CLS", "Clear status data structures"),
    ("*ESE <n>", "Standard event status enable"),
    ("*ESE?", "ESE register"),
    ("*ESR?", "Standard event status register"),
    ("*OPC", "Set OPC bit on completion"),
    ("*OPC?", "1 when all operations complete"),
    ("*PSC 0|1", "Power-on status clear flag"),
    ("*PSC?", "PSC flag"),
    ("*SRE <n>", "Service request enable"),
    ("*SRE?", "SRE register"),
    ("*STB?", "Status byte register"),
    ("*TRG", "Bus trigger (=GET)"),
    ("*WAI", "Wait for pending operations"),
    ("CALibration:COUNt?", "Number of calibrations (read-only)"),
    ("CALibration:STRing?", "Calibration message (read-only)"),
]

COMMAND_NAMES = sorted({c.split()[0].rstrip("?") for c, _ in COMMANDS}
                       | {c for c, _ in COMMANDS})
