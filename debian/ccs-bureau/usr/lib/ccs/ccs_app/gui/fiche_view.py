"""Encart « Où j'en étais » en haut de l'aperçu d'une conversation (voir `fiche.py`)."""

from datetime import datetime

from gi.repository import Gtk, Pango

from .. import fiche as fiche_mod
from .common import short_path

FILES_SHOWN = 6


def _line(label, text, selectable=True):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.append(Gtk.Label(label=label, xalign=0, css_classes=["caption-heading", "dim-label"]))
    box.append(Gtk.Label(label=text, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                         selectable=selectable))
    return box


class FicheView(Gtk.Frame):
    """Carte résumant la dernière demande, le début de la dernière réponse, les fichiers
    modifiés et la dernière liste de tâches. `fiche` : `fiche.Fiche`."""

    def __init__(self, fiche):
        super().__init__(css_classes=["ccs-card", "flat"])
        self.fiche = fiche
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      margin_top=10, margin_bottom=10, margin_start=12, margin_end=12)
        box.append(Gtk.Label(label="Où j'en étais", xalign=0, css_classes=["heading"]))
        when = datetime.fromtimestamp(fiche.when).strftime("%d/%m/%Y %H:%M") if fiche.when else ""
        meta = [m for m in (when, f"branche {fiche.branch}" if fiche.branch else "",
                            f"compte {fiche.account}" if fiche.account else "",
                            "archivée" if fiche.archived else "") if m]
        if meta:
            box.append(Gtk.Label(label=" · ".join(meta), xalign=0, css_classes=["caption", "dim-label"]))
        if fiche.last_request:
            box.append(_line("Ta dernière demande", fiche.last_request))
        if fiche.last_reply:
            box.append(_line("Début de la dernière réponse", fiche.last_reply))
        if fiche.files:
            shown = fiche.files[-FILES_SHOWN:]
            more = len(fiche.files) - len(shown)
            lines = [short_path(p) for p in shown]
            if more:
                lines.append(f"… et {more} autre{'s' if more > 1 else ''}")
            box.append(_line(f"Fichiers modifiés ({len(fiche.files)})", "\n".join(lines)))
        if fiche.todos:
            done = sum(1 for s, _t in fiche.todos if s == "completed")
            text = "\n".join(f"{fiche_mod.STATUS_MARKS[s]} {t}" for s, t in fiche.todos)
            box.append(_line(f"Liste de tâches ({done}/{len(fiche.todos)})", text))
        self.set_child(box)
