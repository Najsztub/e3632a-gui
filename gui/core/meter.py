"""Live power/energy accumulator.

Power P = V_meas * I_meas (W, instantaneous).
Energy is integrated with the trapezoid... rectangular rule over the
monitor timestamps: E += P * dt (J), reported in Wh (1 Wh = 3600 J).
"""

JOULES_PER_WH = 3600.0

#: Minimum current (A) for a meaningful resistance value.
R_I_MIN = 5e-4


def resistance(v: float, i: float):
    """Load resistance R = V / max(0, I); None when current is ~zero."""
    i = max(0.0, float(i))
    if i < R_I_MIN:
        return None
    return float(v) / i


def fmt_resistance(r):
    """Adaptive formatting: Ω below 1 kΩ, kΩ above; '—' when None."""
    if r is None:
        return "—"
    if r >= 1000.0:
        return f"{r / 1000.0:.3f}"
    if r >= 100.0:
        return f"{r:.2f}"
    return f"{r:.3f}"


def resistance_unit(r):
    return "kΩ" if r is not None and r >= 1000.0 else "Ω"


class EnergyMeter:
    """Accumulates delivered energy from timestamped V/I readings."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._last_t = None
        self.joules = 0.0

    def update(self, t: float, v: float, i: float):
        """Feed one reading; return (P_watts, E_watthours).

        Current is clamped at zero so noise around 0 A with the output
        off can never yield negative power/energy.
        """
        i = max(0.0, float(i))
        p = float(v) * i
        if self._last_t is not None and t >= self._last_t:
            self.joules += p * (t - self._last_t)
        self._last_t = float(t)
        return p, self.joules / JOULES_PER_WH

    @property
    def wh(self) -> float:
        return self.joules / JOULES_PER_WH
