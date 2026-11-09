"""Onglet Planning : fenêtres de 5 h de chaque compte et recharges à venir."""

import time
from datetime import datetime

from gi.repository import Adw, Gtk

from .. import best_time, daemon
from ..settings import load_settings, save_settings
from .charts import PALETTE, _fg
from .accounts import pause_box
from .common import caption, clear, now_utc, parse_ts
from .geometry import span_to_x

ROW_H = 34
LABEL_W = 110


class Timeline(Gtk.DrawingArea):
    """Une ligne par compte : fenêtre en cours (remplie selon l'usage), fenêtres prévues."""

    def __init__(self):
        super().__init__(hexpand=True)
        self.rows, self.t0, self.t1 = [], 0, 1
        self.set_draw_func(self._draw)

    def set_data(self, t0, t1, rows):
        self.t0, self.t1, self.rows = t0, t1, rows
        self.set_content_height(28 + ROW_H * max(1, len(rows)))
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        fg = _fg(self)
        w = max(1, width - LABEL_W - 8)
        x0 = LABEL_W
        cr.set_font_size(10)
        # Graduations horaires.
        first_hour = int(self.t0 // 3600 + 1) * 3600
        for ts in range(first_hour, int(self.t1), 3600):
            x = x0 + span_to_x(ts, self.t0, self.t1, w)
            hour = datetime.fromtimestamp(ts).hour
            cr.set_source_rgba(*fg, 0.10 if hour % 3 else 0.22)
            cr.move_to(x, 18)
            cr.line_to(x, height)
            cr.stroke()
            if hour % 3 == 0:
                cr.set_source_rgba(*fg, 0.6)
                cr.move_to(x + 2, 12)
                cr.show_text(f"{hour} h")
        for i, (name, windows, reserve) in enumerate(self.rows):
            y = 24 + i * ROW_H
            rgb = PALETTE[i % len(PALETTE)]
            cr.set_source_rgba(*fg, 0.9)
            cr.set_font_size(12)
            cr.move_to(4, y + ROW_H / 2 + 4)
            cr.show_text(name)
            if reserve:
                cr.set_font_size(9)
                cr.set_source_rgba(*fg, 0.6)
                cr.move_to(4, y + ROW_H / 2 + 15)
                cr.show_text("réserve")
            cr.set_font_size(10)
            for start, end, kind, used in windows:
                xa = x0 + span_to_x(start, self.t0, self.t1, w)
                xb = x0 + span_to_x(end, self.t0, self.t1, w)
                if xb - xa < 1:
                    continue
                top, h = y + 4, ROW_H - 10
                if kind == "current":
                    cr.set_source_rgba(*rgb, 0.25)
                    cr.rectangle(xa, top, xb - xa, h)
                    cr.fill()
                    cr.set_source_rgba(*rgb, 0.85)
                    cr.rectangle(xa, top, (xb - xa) * min(1, used / 100), h)
                    cr.fill()
                else:
                    cr.set_source_rgba(*rgb, 0.12)
                    cr.rectangle(xa, top, xb - xa, h)
                    cr.fill()
                    cr.set_source_rgba(*rgb, 0.7)
                    cr.set_dash([4, 3])
                    cr.rectangle(xa + 0.5, top + 0.5, xb - xa - 1, h - 1)
                    cr.stroke()
                    cr.set_dash([])
                # Recharge à la fin de la fenêtre.
                cr.set_source_rgba(*rgb, 1)
                cr.rectangle(xb - 2, top - 2, 3, h + 4)
                cr.fill()
        now_x = x0 + span_to_x(time.time(), self.t0, self.t1, w)
        cr.set_source_rgba(0.88, 0.11, 0.14, 0.9)
        cr.set_line_width(2)
        cr.move_to(now_x, 16)
        cr.line_to(now_x, height)
        cr.stroke()


FRIEZE_H = 52
MOMENT_CHOICES = (1, 2, 3, 4, 6, 8)


class Frieze(Gtk.DrawingArea):
    """Frise des départs possibles : plus la zone est foncée, plus le quota cumulé est grand."""

    def __init__(self):
        super().__init__(hexpand=True)
        self.curve, self.best, self.t0, self.t1 = [], None, 0, 1
        self.set_content_height(FRIEZE_H)
        self.set_draw_func(self._draw)

    def set_data(self, curve, best, step_s):
        self.curve, self.best, self.step = curve, best, step_s
        if curve:
            self.t0 = curve[0].start.timestamp()
            self.t1 = curve[-1].start.timestamp() + step_s
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        if not self.curve:
            return
        fg = _fg(self)
        top = max(s.score for s in self.curve) or 1
        low = min(min(s.score for s in self.curve), top / 2)
        bar_top, bar_h = 16, height - 22
        for i, s in enumerate(self.curve):
            a = s.start.timestamp()
            b = self.curve[i + 1].start.timestamp() if i + 1 < len(self.curve) else self.t1
            xa, xb = (span_to_x(v, self.t0, self.t1, width) for v in (a, b))
            cr.set_source_rgba(0.15, 0.64, 0.41, 0.08 + 0.85 * (s.score - low) / ((top - low) or 1))
            cr.rectangle(xa, bar_top, max(1.0, xb - xa), bar_h)
            cr.fill()
        cr.set_font_size(10)
        first = int(self.t0 // 3600 + 1) * 3600
        for ts in range(first, int(self.t1), 3600):
            hour = datetime.fromtimestamp(ts).hour
            if hour % 3:
                continue
            x = span_to_x(ts, self.t0, self.t1, width)
            cr.set_source_rgba(*fg, 0.25)
            cr.move_to(x, bar_top)
            cr.line_to(x, bar_top + bar_h)
            cr.stroke()
            cr.set_source_rgba(*fg, 0.65)
            cr.move_to(min(x + 2, width - 24), 11)
            cr.show_text(f"{hour} h")
        if self.best is not None:
            x = span_to_x(self.best.start.timestamp(), self.t0, self.t1, width)
            cr.set_source_rgba(0.88, 0.11, 0.14, 0.95)
            cr.set_line_width(3)
            cr.move_to(x, bar_top - 3)
            cr.line_to(x, bar_top + bar_h + 3)
            cr.stroke()


class PlanningPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                           margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        self.set_child(Adw.Clamp(maximum_size=900, child=self.box))
        self.moment_hours = 3
        self.state = {}

    def toggle(self, sw, _p):
        s = load_settings()
        if s["orchestrator"]["enabled"] != sw.get_active():
            s["orchestrator"]["enabled"] = sw.get_active()
            save_settings(s)
            daemon.request_refresh()
            self.window.toast("Orchestrateur " + ("activé" if sw.get_active() else "désactivé"))

    def choose_hours(self, button, hours):
        if button.get_active() and hours != self.moment_hours:
            self.moment_hours = hours
            self.render(self.state)

    def moment_card(self, state):
        """Carte « Meilleur moment pour une grosse tâche » : durée, conseil, frise des 24 h."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "profile-card"])
        card.append(Gtk.Label(label="Meilleur moment pour une grosse tâche", xalign=0,
                              css_classes=["heading"]))
        choices = Gtk.Box(spacing=0, css_classes=["linked"], halign=Gtk.Align.START)
        first = None
        for h in MOMENT_CHOICES:
            b = Gtk.ToggleButton(label=f"{h} h", group=first)
            first = first or b
            b.set_active(h == self.moment_hours)
            b.connect("toggled", self.choose_hours, h)
            choices.append(b)
        card.append(choices)
        res = best_time.compute(state, duration_h=self.moment_hours, now=now_utc())
        if res.best is None:
            card.append(caption("Aucun compte utilisable." if res.accounts == 0 else
                                "Aucun quota disponible sur les prochaines 24 h."))
        else:
            lead = ("Lance-la maintenant" if res.now_is_best
                    else f"Meilleur départ : {best_time.label(res.best, res.now)}")
            card.append(Gtk.Label(label=lead, xalign=0, wrap=True, css_classes=["title-4"]))
            card.append(caption(res.best.text))
            frieze = Frieze()
            frieze.set_data(res.curve, res.best, best_time.STEP.total_seconds())
            card.append(frieze)
            for s in res.alternatives:
                card.append(caption(f"Sinon {best_time.label(s, res.now)} : {s.text}"))
        if res.paused:
            card.append(caption("Orchestrateur en pause : le calcul suppose que tu lances la tâche toi-même."))
        card.append(caption("Frise : plus la zone est verte, plus le quota cumulé est grand si tu "
                            "démarres à cette heure ; trait rouge : meilleur départ. Unité : fenêtres "
                            "de 5 h de quota disponible, pas une durée de travail garantie."))
        return card

    def render(self, state):
        self.state = state
        clear(self.box)
        s = load_settings()["orchestrator"]
        o = state.get("orchestrator") or {}

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "best-card"])
        row = Gtk.Box(spacing=12)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        text.append(Gtk.Label(label="Orchestrateur", xalign=0, css_classes=["heading"]))
        h = s["active_hours"]
        detail = f"Plage {h['start']} → {h['end']}"
        if s["enabled"] and o.get("next_wake"):
            detail += f" · prochaine action {parse_ts(o['next_wake']).astimezone():%H:%M}"
        elif s["enabled"] and o and not o.get("active_now"):
            detail += " · hors plage : rien n'est démarré"
        text.append(caption(detail))
        text.append(caption("Démarre les fenêtres de 5 h au bon moment, les décale entre comptes "
                            "et bascule vers le quota qui va expirer."))
        row.append(text)
        sw = Gtk.Switch(active=s["enabled"], valign=Gtk.Align.CENTER)
        sw.connect("notify::active", self.toggle)
        row.append(sw)
        head.append(row)
        paused = pause_box(self.window, now_utc(), offer=False)
        if paused is not None:
            head.append(paused)
        self.box.append(head)

        plan = o.get("plan") or []
        accounts = state.get("accounts") or []
        if not accounts:
            self.box.append(Adw.StatusPage(icon_name="x-office-calendar-symbolic",
                                           title="Pas encore de données"))
            return
        used = {a["name"]: next((l["percent"] for l in a.get("limits") or []
                                 if l["kind"] == "session"), 0) for a in accounts}
        reserve = set(o.get("reserve") or [])
        now = time.time()
        end = max([parse_ts(w["end"]).timestamp() for w in plan] + [now + 6 * 3600])
        t0, t1 = now - 2 * 3600, min(end, now + 18 * 3600)
        rows = []
        for a in accounts:
            wins = [(parse_ts(w["start"]).timestamp(), parse_ts(w["end"]).timestamp(), w["kind"],
                     used.get(a["name"], 0)) for w in plan if w["name"] == a["name"]]
            rows.append((a["name"], wins, a["name"] in reserve))
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "profile-card"])
        timeline = Timeline()
        timeline.set_data(t0, t1, rows)
        card.append(timeline)
        card.append(caption("Plein : fenêtre en cours (partie foncée = quota utilisé) · "
                            "pointillés : fenêtres prévues · trait rouge : maintenant · "
                            "« réserve » : semaine en avance, compte utilisé en dernier"))
        self.box.append(card)

        ends = sorted((parse_ts(w["end"]), w["name"]) for w in plan if parse_ts(w["end"]).timestamp() > now)
        recharge = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "profile-card"])
        recharge.append(Gtk.Label(label="Recharges à venir", xalign=0, css_classes=["heading"]))
        if not ends:
            recharge.append(caption("Aucune fenêtre en cours ni prévue."))
        for end_dt, name in ends[:10]:
            line = Gtk.Box()
            line.append(Gtk.Label(label=f"{end_dt.astimezone():%H:%M}", css_classes=["pct"], width_chars=6, xalign=0))
            line.append(Gtk.Label(label=f"{name} retrouve 100 % de sa session", xalign=0))
            recharge.append(line)
        self.box.append(recharge)
        self.box.append(self.moment_card(state))
        if not s["enabled"]:
            self.box.append(caption("Orchestrateur désactivé : seules les fenêtres en cours sont "
                                    "affichées. Active-le pour enchaîner et décaler les fenêtres."))
