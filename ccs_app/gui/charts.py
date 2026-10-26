"""Graphiques Cairo : courbes d'usage, sparkline, histogramme horaire."""

import math

from gi.repository import Gtk

from .geometry import series_to_points

SESSION_RGB = (0.21, 0.52, 0.89)   # bleu
WEEKLY_RGB = (0.90, 0.38, 0.0)     # orange
PALETTE = [SESSION_RGB, WEEKLY_RGB, (0.18, 0.76, 0.49), (0.57, 0.25, 0.67), (0.88, 0.11, 0.14)]


def _fg(widget):
    c = widget.get_color()
    return c.red, c.green, c.blue


class LineChart(Gtk.DrawingArea):
    """Séries (ts, %) sur [t0, t1] ; lignes pointillées et marqueurs verticaux optionnels."""

    def __init__(self, height=150):
        super().__init__(content_height=height, hexpand=True)
        self.series = []    # [(points, rgb, dashed, label)]
        self.markers = []   # [(ts, label)]
        self.t0 = self.t1 = 0
        self.set_draw_func(self._draw)

    def set_data(self, t0, t1, series, markers=()):
        self.t0, self.t1, self.series, self.markers = t0, t1, list(series), list(markers)
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        fg = _fg(self)
        left, bottom, top = 34, 18, 6
        w, h = max(1, width - left - 4), max(1, height - bottom - top)
        cr.set_font_size(10)
        # Grille 0 / 50 / 100 %.
        for pct in (0, 50, 100):
            y = top + h - pct / 100 * h
            cr.set_source_rgba(*fg, 0.12)
            cr.set_line_width(1)
            cr.move_to(left, y)
            cr.line_to(left + w, y)
            cr.stroke()
            cr.set_source_rgba(*fg, 0.55)
            cr.move_to(2, y + 3)
            cr.show_text(f"{pct} %")
        for ts, label in self.markers:
            if self.t1 <= self.t0 or not (self.t0 <= ts <= self.t1):
                continue
            x = left + (ts - self.t0) / (self.t1 - self.t0) * w
            cr.set_source_rgba(*fg, 0.35)
            cr.set_dash([2, 3])
            cr.move_to(x, top)
            cr.line_to(x, top + h)
            cr.stroke()
            cr.set_dash([])
            cr.move_to(x + 3, top + 10)
            cr.show_text(label)
        for series, rgb, dashed, _label in self.series:
            pts = series_to_points(series, self.t0, self.t1, w, h)
            if not pts:
                continue
            cr.set_source_rgba(*rgb, 0.9)
            cr.set_line_width(2)
            cr.set_dash([5, 4] if dashed else [])
            cr.move_to(left + pts[0][0], top + pts[0][1])
            for x, y in pts[1:]:
                cr.line_to(left + x, top + y)
            cr.stroke()
            if len(pts) == 1:
                cr.arc(left + pts[0][0], top + pts[0][1], 2.5, 0, 2 * math.pi)
                cr.fill()
        cr.set_dash([])


class Sparkline(Gtk.DrawingArea):
    def __init__(self):
        super().__init__(content_height=28, hexpand=True)
        self.points, self.t0, self.t1 = [], 0, 0
        self.set_draw_func(self._draw)

    def set_data(self, t0, t1, series):
        self.t0, self.t1, self.points = t0, t1, list(series)
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        pts = series_to_points(self.points, self.t0, self.t1, width, height - 2)
        cr.set_source_rgba(*_fg(self), 0.1)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        if len(pts) < 2:
            return
        cr.set_source_rgba(*SESSION_RGB, 0.25)
        cr.move_to(pts[0][0], height)
        for x, y in pts:
            cr.line_to(x, y + 1)
        cr.line_to(pts[-1][0], height)
        cr.close_path()
        cr.fill()
        cr.set_source_rgba(*SESSION_RGB, 1)
        cr.set_line_width(1.5)
        cr.move_to(pts[0][0], pts[0][1] + 1)
        for x, y in pts[1:]:
            cr.line_to(x, y + 1)
        cr.stroke()


class HourBars(Gtk.DrawingArea):
    """Histogramme sur 24 heures."""

    def __init__(self):
        super().__init__(content_height=120, hexpand=True)
        self.values = [0.0] * 24
        self.set_draw_func(self._draw)

    def set_data(self, values):
        self.values = list(values)
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        fg = _fg(self)
        peak = max(self.values) or 1
        bottom = 16
        slot = width / 24
        cr.set_font_size(9)
        for h, v in enumerate(self.values):
            bh = (height - bottom - 4) * v / peak
            cr.set_source_rgba(*SESSION_RGB, 0.85)
            cr.rectangle(h * slot + 1, height - bottom - bh, max(1, slot - 2), bh)
            cr.fill()
            if h % 3 == 0:
                cr.set_source_rgba(*fg, 0.6)
                cr.move_to(h * slot + 1, height - 3)
                cr.show_text(f"{h}h")
