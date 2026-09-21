"""
Dual-trace V/I strip-chart widget (QPainter).

Ports the interaction model of the adce7352a OpenGL plot
(`EnhancedGLPlot`) without the OpenGL dependency:

- Left axis (green): voltage. Right axis (cyan): current. Time axis.
- Crosshair with snapped V / I / t readout (mouse move).
- M1 marker (left click, snaps to nearest V sample, yellow).
- M2 marker (right click, snaps to nearest I sample, orange).
- Measurement box: ΔV, ΔI, Δt between markers.
- Middle-drag pan, wheel Y-zoom (left third = V, right third = I),
  Ctrl+wheel X-zoom, double-click / Auto button resets view.
- Toolbar: Auto, Clear, Fill toggle, V/I toggles, buffer size.
"""

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics, QBrush
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QCheckBox, QLabel, QSpinBox)


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


class VIPlot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ts, self._vs, self._is = [], [], []
        self._show_v = True
        self._show_i = True
        self._fill = False
        self._dark = True
        # view state
        self._zoom_yv = 1.0
        self._zoom_yi = 1.0
        self._pan_yv = 0.0
        self._pan_yi = 0.0
        self._zoom_x = 1.0
        self._x_pan = 0.0  # seconds, <= 0, offset of right edge from latest
        # interaction state
        self._mouse = None
        self._m1 = None  # (t, v)
        self._m2 = None  # (t, i)
        self._pan_origin = None
        self._pan_x0 = 0.0
        self._pan_yv0 = 0.0
        self._pan_yi0 = 0.0
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    # -- API ------------------------------------------------------------
    def set_theme(self, dark: bool):
        self._dark = dark
        self.update()

    def set_data(self, ts, vs, is_, outs=None):
        self._ts = list(ts); self._vs = list(vs); self._is = list(is_)
        self.update()

    def clear_data(self):
        self._ts.clear(); self._vs.clear(); self._is.clear()
        self._m1 = self._m2 = None
        self.reset_view()
        self.update()

    def reset_view(self):
        self._zoom_yv = self._zoom_yi = 1.0
        self._pan_yv = self._pan_yi = 0.0
        self._zoom_x = 1.0
        self._x_pan = 0.0
        self.update()

    # -- ranges ----------------------------------------------------------
    def _x_range(self):
        if not self._ts:
            return 0.0, 1.0
        t_last = self._ts[-1]
        total = max(t_last - self._ts[0], 1.0)
        vis = total / max(self._zoom_x, 1e-6)
        x1 = t_last + min(self._x_pan, 0.0)
        return x1 - vis, x1

    def _y_range(self, vals, is_current):
        lo = hi = None
        if self._ts:
            x0, x1 = self._x_range()
            for t, y in zip(self._ts, vals):
                if x0 <= t <= x1:
                    lo = y if lo is None else min(lo, y)
                    hi = y if hi is None else max(hi, y)
        if lo is None:
            lo, hi = 0.0, 1.0
        if hi - lo < (0.005 if is_current else 0.05):
            c = (hi + lo) / 2
            m = (0.005 if is_current else 0.05) / 2
            lo, hi = c - m, c + m
        m = (hi - lo) * 0.08
        return lo - m, hi + m

    def _view(self):
        """Return (x0, x1, yv0, yv1, yi0, yi1) in data coordinates."""
        x0, x1 = self._x_range()
        av0, av1 = self._y_range(self._vs, False)
        ai0, ai1 = self._y_range(self._is, True)
        cyv, hyv = (av0 + av1) / 2, (av1 - av0) / 2 / self._zoom_yv
        cyi, hyi = (ai0 + ai1) / 2, (ai1 - ai0) / 2 / self._zoom_yi
        return (x0, x1,
                cyv - hyv + self._pan_yv, cyv + hyv + self._pan_yv,
                cyi - hyi + self._pan_yi, cyi + hyi + self._pan_yi)

    def _geom(self):
        W, H = self.width(), self.height()
        ml, mr, mt, mb = 64, 64, 12, 40
        return ml, mt, max(10, W - ml - mr), max(10, H - mt - mb)

    def _snap_index(self, t):
        ts = self._ts
        lo, hi = 0, len(ts) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if ts[mid] < t:
                lo = mid + 1
            else:
                hi = mid
        best = lo
        if lo > 0 and abs(ts[lo - 1] - t) < abs(ts[lo] - t):
            best = lo - 1
        return best

    # -- paint -----------------------------------------------------------
    def _colors(self):
        if self._dark:
            return {"bg": QColor("#0d1117"), "grid": QColor("#21262d"),
                    "txt": QColor("#8b949e"), "bright": QColor("#c9d1d9"),
                    "v": QColor("#00ff80"), "i": QColor("#00d9ff"),
                    "m1": QColor("#ffd700"), "m2": QColor("#ff7f50"),
                    "tip": QColor("#161b22")}
        return {"bg": QColor("#ffffff"), "grid": QColor("#d0d7de"),
                "txt": QColor("#656d76"), "bright": QColor("#24292f"),
                "v": QColor("#00884d"), "i": QColor("#006b99"),
                "m1": QColor("#9a6700"), "m2": QColor("#cf222e"),
                "tip": QColor("#f6f8fa")}

    def paintEvent(self, event):  # noqa: N802
        c = self._colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), c["bg"])
        ml, mt, pw, ph = self._geom()
        font = QFont("Consolas", 8)
        p.setFont(font)
        fm = QFontMetrics(font)
        if not self._ts:
            p.setPen(c["txt"])
            p.drawText(self.rect(), Qt.AlignCenter, "No data — start monitoring")
            p.end()
            return

        x0, x1, yv0, yv1, yi0, yi1 = self._view()
        xspan = max(x1 - x0, 1e-9)
        yvspan = max(yv1 - yv0, 1e-9)
        yispan = max(yi1 - yi0, 1e-9)

        def X(t):
            return ml + (t - x0) / xspan * pw

        def YV(v):
            return mt + (1 - (v - yv0) / yvspan) * ph

        def YI(i):
            return mt + (1 - (i - yi0) / yispan) * ph

        # grid + axes
        p.setPen(QPen(c["grid"], 1))
        for k in range(6):
            y = mt + ph * k / 5
            p.drawLine(ml, int(y), ml + pw, int(y))
            p.setPen(c["v"])
            lbl = f"{yv1 - (yv1 - yv0) * k / 5:.3f}"
            p.drawText(ml - fm.horizontalAdvance(lbl) - 5, int(y) + 3, lbl)
            p.setPen(c["i"])
            lbl = f"{yi1 - (yi1 - yi0) * k / 5:.4f}"
            p.drawText(ml + pw + 5, int(y) + 3, lbl)
            p.setPen(QPen(c["grid"], 1))
        p.setPen(c["txt"])
        for k in range(7):
            t = x0 + xspan * k / 6
            x = ml + pw * k / 6
            lbl = f"{t:.1f}s"
            p.drawText(int(x) - fm.horizontalAdvance(lbl) // 2, mt + ph + 15, lbl)
        p.drawText(ml + pw // 2 - 30, mt + ph + 28, "Time (s)")
        p.save()
        p.translate(12, mt + ph // 2)
        p.rotate(-90)
        p.setPen(c["v"])
        p.drawText(-30, 0, "Voltage [V]")
        p.restore()
        p.save()
        p.translate(ml + pw + 44, mt + ph // 2)
        p.rotate(-90)
        p.setPen(c["i"])
        p.drawText(-32, 0, "Current [A]")
        p.restore()
        p.setPen(QPen(c["v"] if self._show_v else c["grid"], 1))
        p.drawRect(ml, mt, pw, ph)

        # traces (decimated to screen width)
        n = len(self._ts)
        step = max(1, n // max(pw, 1))
        idx = range(0, n, step)
        if self._show_v and self._vs:
            if self._fill:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(c["v"].red(), c["v"].green(),
                                         c["v"].blue(), 40)))
                poly = [QPointF(X(self._ts[k]), YV(self._vs[k])) for k in idx]
                base = YV(max(yv0, 0.0))
                poly.append(QPointF(X(self._ts[n - 1]), base))
                poly.append(QPointF(X(self._ts[0]), base))
                from PyQt5.QtGui import QPolygonF
                p.drawPolygon(QPolygonF(poly))
            p.setPen(QPen(c["v"], 1.5))
            p.setBrush(Qt.NoBrush)
            prev = None
            for k in idx:
                pt = (X(self._ts[k]), YV(self._vs[k]))
                if prev is not None:
                    p.drawLine(int(prev[0]), int(prev[1]), int(pt[0]), int(pt[1]))
                prev = pt
        if self._show_i and self._is:
            p.setPen(QPen(c["i"], 1.5))
            prev = None
            for k in idx:
                pt = (X(self._ts[k]), YI(self._is[k]))
                if prev is not None:
                    p.drawLine(int(prev[0]), int(prev[1]), int(pt[0]), int(pt[1]))
                prev = pt

        # legend
        p.setPen(c["v"] if self._show_v else c["grid"])
        p.drawText(ml + 6, mt + 12, "— V (left)")
        p.setPen(c["i"] if self._show_i else c["grid"])
        p.drawText(ml + 80, mt + 12, "— I (right)")
        p.setPen(c["txt"])
        p.drawText(ml + pw - 60, mt + 12, f"n={n}")

        # markers: (t, v, i) snapped samples; M1 labels V, M2 labels I
        bfont = QFont("Consolas", 8, QFont.Bold)
        p.setFont(bfont)
        bfm = QFontMetrics(bfont)

        def draw_marker(mark, label, col, ymap, val_idx, unit, stack):
            if mark is None:
                return
            t, v, i = mark
            val = v if val_idx == 1 else i
            sx, sy = X(t), ymap(val)
            p.setPen(QPen(col, 1, Qt.DashLine))
            p.drawLine(int(sx), mt, int(sx), mt + ph)
            p.setPen(QPen(col, 2))
            p.setBrush(QBrush(QColor(13, 17, 23) if self._dark else QColor(255, 255, 255)))
            p.drawEllipse(QPointF(sx, sy), 5, 5)
            lbl = f"{label}: {val:.4f}{unit}"
            tw, th = bfm.horizontalAdvance(lbl), bfm.height()
            bx = int(sx) + 8
            if bx + tw + 6 > ml + pw:
                bx = int(sx) - tw - 10
            by = mt + 6 + stack * (th + 6)
            p.fillRect(bx - 2, by - 1, tw + 6, th + 2, c["tip"])
            p.setPen(col)
            p.drawText(bx + 2, by + bfm.ascent(), lbl)

        draw_marker(self._m1, "M1", c["m1"], YV, 1, "V", 0)
        draw_marker(self._m2, "M2", c["m2"], YI, 2, "A", 1)
        if self._m1 and self._m2:
            lbl = (f"ΔV={self._m2[1] - self._m1[1]:+.4f}V  "
                   f"ΔI={self._m2[2] - self._m1[2]:+.4f}A  "
                   f"Δt={self._m2[0] - self._m1[0]:+.2f}s")
            p.setFont(font)
            dfm = QFontMetrics(font)
            tw, th = dfm.horizontalAdvance(lbl), dfm.height()
            bx = ml + pw // 2 - tw // 2
            by = mt + ph - th - 8
            p.fillRect(bx - 4, by - 2, tw + 8, th + 4, c["tip"])
            p.setPen(c["bright"])
            p.drawText(bx, by + dfm.ascent(), lbl)

        # crosshair
        if self._mouse is not None:
            mx, my = self._mouse.x(), self._mouse.y()
            if ml <= mx <= ml + pw and mt <= my <= mt + ph:
                p.setPen(QPen(QColor(100, 130, 160, 160), 1, Qt.DashLine))
                p.drawLine(ml, my, ml + pw, my)
                p.drawLine(mx, mt, mx, mt + ph)
                t = x0 + (mx - ml) / pw * xspan
                k = self._snap_index(_clip(t, self._ts[0], self._ts[-1]))
                lbl = (f"  V:{self._vs[k]:.4f}  I:{self._is[k]:.4f}  "
                       f"t={self._ts[k]:.1f}s")
                p.setFont(font)
                cfm = QFontMetrics(font)
                tw = cfm.horizontalAdvance(lbl)
                bx = mx + 8 if mx + tw + 12 < ml + pw else mx - tw - 12
                p.fillRect(bx - 2, my - cfm.height() - 4, tw + 4,
                           cfm.height() + 4, c["tip"])
                p.setPen(c["bright"])
                p.drawText(bx, my - 6, lbl)
        p.end()

    # -- interaction ------------------------------------------------------
    def mouseMoveEvent(self, event):  # noqa: N802
        self._mouse = event.pos()
        if self._pan_origin is not None and event.buttons() & Qt.MiddleButton:
            ml, mt, pw, ph = self._geom()
            x0, x1, yv0, yv1, yi0, yi1 = self._view()
            dx = event.pos().x() - self._pan_origin.x()
            dy = event.pos().y() - self._pan_origin.y()
            self._x_pan = min(0.0, self._pan_x0 - dx / max(pw, 1) * (x1 - x0))
            self._pan_yv = self._pan_yv0 + dy / max(ph, 1) * (yv1 - yv0)
            self._pan_yi = self._pan_yi0 + dy / max(ph, 1) * (yi1 - yi0)
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        ml, mt, pw, ph = self._geom()
        if not (ml <= event.x() <= ml + pw and mt <= event.y() <= mt + ph):
            return
        if not self._ts:
            return
        x0, x1, *_ = self._view()
        t = x0 + (event.x() - ml) / max(pw, 1) * max(x1 - x0, 1e-9)
        k = self._snap_index(_clip(t, self._ts[0], self._ts[-1]))
        if event.button() == Qt.LeftButton:
            self._m1 = (self._ts[k], self._vs[k], self._is[k])
        elif event.button() == Qt.RightButton:
            self._m2 = (self._ts[k], self._vs[k], self._is[k])
        elif event.button() == Qt.MiddleButton:
            self._pan_origin = event.pos()
            self._pan_x0 = self._x_pan
            self._pan_yv0 = self._pan_yv
            self._pan_yi0 = self._pan_yi
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MiddleButton:
            self._pan_origin = None

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.reset_view()

    def wheelEvent(self, event):  # noqa: N802
        ml, mt, pw, ph = self._geom()
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        if event.modifiers() & Qt.ControlModifier:
            self._zoom_x = _clip(self._zoom_x * factor, 1.0, 50.0)
        else:
            x0, x1, yv0, yv1, yi0, yi1 = self._view()
            mx = event.x()
            third = pw / 3
            if mx > ml + pw - third:
                chan = "I"
            else:
                chan = "V"  # left + middle thirds (adce maps middle to A)
            my = event.y()
            if chan == "V":
                self._zoom_yv = _clip(self._zoom_yv * factor, 0.2, 50.0)
                frac = ((mt + ph - my) / ph) if ph else 0.5
                frac = _clip(frac, 0.0, 1.0)
                c = (yv0 + yv1) / 2
                half = (yv1 - yv0) / 2 / self._zoom_yv
                # keep cursor-anchored value: solve pan so y(my) stays
                y_at = yv1 - (my - mt) / max(ph, 1) * (yv1 - yv0)
                self._pan_yv = y_at - (c - half + frac * 2 * half)
            else:
                self._zoom_yi = _clip(self._zoom_yi * factor, 0.2, 50.0)
                y_at = yi1 - (my - mt) / max(ph, 1) * (yi1 - yi0)
                c = (yi0 + yi1) / 2
                half = (yi1 - yi0) / 2 / self._zoom_yi
                frac = _clip((mt + ph - my) / max(ph, 1), 0.0, 1.0)
                self._pan_yi = y_at - (c - half + frac * 2 * half)
        self.update()
        event.accept()


class PlotTab(QWidget):
    """Plot tab with toolbar, mirroring the adce7352a plot tab UX."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.btn_auto = QPushButton("Auto")
        self.btn_clear = QPushButton("Clear")
        self.chk_fill = QCheckBox("Fill")
        self.chk_v = QCheckBox("Voltage")
        self.chk_v.setChecked(True)
        self.chk_i = QCheckBox("Current")
        self.chk_i.setChecked(True)
        buf_lbl = QLabel("Buffer:")
        self.buf_spin = QSpinBox()
        self.buf_spin.setRange(60, 5000)
        self.buf_spin.setValue(1200)
        hint = QLabel("L:M1  R:M2  M-drag:pan  wheel:zoom  dbl:reset")
        hint.setObjectName("idnLabel")
        bar.addWidget(self.btn_auto)
        bar.addWidget(self.btn_clear)
        bar.addWidget(self.chk_fill)
        bar.addWidget(self.chk_v)
        bar.addWidget(self.chk_i)
        bar.addWidget(buf_lbl)
        bar.addWidget(self.buf_spin)
        bar.addStretch()
        bar.addWidget(hint)
        layout.addLayout(bar)
        self.plot = VIPlot(self)
        layout.addWidget(self.plot, 1)
        self.btn_auto.clicked.connect(self.plot.reset_view)
        self.btn_clear.clicked.connect(self.plot.clear_data)
        self.chk_fill.toggled.connect(lambda on: (setattr(self.plot, "_fill", on),
                                                  self.plot.update()))
        self.chk_v.toggled.connect(lambda on: (setattr(self.plot, "_show_v", on),
                                               self.plot.update()))
        self.chk_i.toggled.connect(lambda on: (setattr(self.plot, "_show_i", on),
                                               self.plot.update()))

    def set_theme(self, dark: bool):
        self.plot.set_theme(dark)

    def set_data(self, ts, vs, is_, outs=None):
        self.plot.set_data(ts, vs, is_, outs)

    def clear_data(self):
        self.plot.clear_data()
