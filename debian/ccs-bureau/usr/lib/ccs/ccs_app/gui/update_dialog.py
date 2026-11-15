"""Dialogue « Mise à jour » : notes de la release, progression, installation en un clic.

Tout le travail (réseau, vérifications, pkexec) tourne hors du fil de l'interface ;
la logique est dans `ccs_app.installer`.
"""

import os
import subprocess
import sys

from gi.repository import Adw, GLib, Gtk

from .. import installer
from .common import in_thread

PHASE_LABELS = {
    "download": "Téléchargement du paquet…",
    "verify": "Vérification de la somme SHA-256 et du paquet…",
    "install": "Installation… saisis ton mot de passe dans la fenêtre qui s'ouvre.",
}


def relaunch_command():
    """Même interpréteur, mêmes arguments, lancé après la fermeture de l'application
    (le nom D-Bus de l'application doit être libéré avant le nouveau lancement)."""
    return ["sh", "-c", 'sleep 1; exec "$@"', "ccs-relance", sys.executable, *sys.orig_argv[1:]]


class UpdateDialog(Adw.Dialog):
    def __init__(self, version, url, on_restart=None, fetch=None, do_install=None):
        super().__init__(title=f"CCS {version}", content_width=560, content_height=560)
        self.version = version
        self.url = url
        self.plan = None
        self.busy = False
        self.parent = None
        self._pulse = None
        self.progress_pulsing = False
        self.on_restart = on_restart or self.restart
        self.fetch = fetch or installer.fetch_plan
        self.do_install = do_install or installer.install

        header = Adw.HeaderBar()
        self.notes = Gtk.Label(wrap=True, xalign=0, selectable=True, valign=Gtk.Align.START,
                               margin_top=12, margin_bottom=12, margin_start=16, margin_end=16,
                               label="Chargement des notes de la version…")
        self.notes.add_css_class("dim-label")
        scroll = Gtk.ScrolledWindow(child=self.notes, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.add_css_class("card")

        self.status = Gtk.Label(wrap=True, xalign=0, selectable=True, label="")
        self.progress = Gtk.ProgressBar(visible=False)
        self.command_entry = Gtk.Entry(editable=False, visible=False)
        self.button = Gtk.Button(label="Installer", sensitive=False, halign=Gtk.Align.END)
        self.button.add_css_class("suggested-action")
        self.button.connect("clicked", self.on_button)
        link = Gtk.LinkButton(uri=url, label="Voir sur GitHub", halign=Gtk.Align.START)
        bottom = Gtk.Box(spacing=8)
        link.set_hexpand(True)
        bottom.append(link)
        bottom.append(self.button)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12,
                      margin_bottom=16, margin_start=16, margin_end=16)
        for w in (scroll, self.status, self.progress, self.command_entry, bottom):
            box.append(w)
        view = Adw.ToolbarView(content=box)
        view.add_top_bar(header)
        self.set_child(view)
        self.set_can_close(True)
        in_thread(self._load, self.loaded)

    # ---- notes -------------------------------------------------------------------

    def _load(self):
        try:
            return self.fetch(self.version)
        except installer.InstallError as e:
            return e
        except Exception as e:  # noqa: BLE001 — affiché plutôt qu'un chargement sans fin
            return installer.InstallError(str(e))

    def loaded(self, result):
        if isinstance(result, installer.InstallError):
            self.notes.set_label("Notes de la version indisponibles.")
            self.fail(result)
            return
        self.plan = result
        text = installer.plain_notes(result.notes) or "Aucune note pour cette version."
        self.notes.set_label(text)
        self.notes.remove_css_class("dim-label")
        self.button.set_sensitive(True)

    # ---- installation --------------------------------------------------------------

    def on_button(self, _btn):
        if self.button.get_label() == "Redémarrer l'application":
            self.on_restart()
            self.close()
        elif self.plan is not None and not self.busy:
            self.start()

    def start(self):
        self.busy = True
        self.set_can_close(False)
        self.button.set_sensitive(False)
        self.command_entry.set_visible(False)
        self.progress.set_visible(True)
        self.progress.set_fraction(0)
        self.show_phase("download", 0.0)
        plan = self.plan

        def work():
            def progress(phase, fraction):
                GLib.idle_add(self.show_phase, phase, fraction)
            try:
                return self.do_install(plan, progress=progress)
            except installer.InstallError as e:
                return e
            except Exception as e:  # noqa: BLE001
                return installer.InstallError(f"Erreur inattendue : {e}")
        in_thread(work, self.finished)

    def show_phase(self, phase, fraction):
        self.status.set_label(PHASE_LABELS.get(phase, ""))
        self.progress_pulsing = fraction is None
        if fraction is None:
            self.progress.pulse()
            if not self._pulse:
                self._pulse = GLib.timeout_add(150, self._pulse_tick)
        else:
            self.progress.set_fraction(max(0.0, min(1.0, fraction)))
        return False

    def _pulse_tick(self):
        if not self.busy:
            self._pulse = None
            return False
        if self.progress_pulsing:
            self.progress.pulse()
        return True

    def finished(self, result):
        self.busy = False
        self.set_can_close(True)
        self.progress.set_visible(False)
        if isinstance(result, installer.InstallError):
            self.fail(result)
            return
        self.status.set_label(result.message)
        self.button.set_label("Redémarrer l'application")
        self.button.set_sensitive(True)

    def fail(self, error):
        self.progress.set_visible(False)
        self.status.set_label(str(error))
        self.button.set_label("Réessayer")
        self.button.set_sensitive(self.plan is not None)
        if error.fallback:
            self.command_entry.set_text(error.fallback)
            self.command_entry.set_visible(True)

    def restart(self):
        subprocess.Popen(relaunch_command(), start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=os.environ)
        app = self.parent.get_application() if self.parent else None
        if app:
            app.quit()


def show_update(parent, version, url, **kwargs):
    dialog = UpdateDialog(version, url, **kwargs)
    dialog.parent = parent
    dialog.present(parent)
    return dialog
