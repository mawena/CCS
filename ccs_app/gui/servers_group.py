"""Groupe « Serveurs CCS » des Réglages : les serveurs appairés (le VPS, par exemple) dont les
projets apparaissent dans la page Sessions.

« Ajouter un serveur… » : adresse, identifiant et mot de passe Ubuntu, code de double
authentification. L'appairage tourne dans un fil ; seul le jeton d'application obtenu est gardé
(`ccs_app.remote.servers`), jamais le mot de passe. Première connexion : le QR code à scanner
s'affiche, puis le premier code. « Retirer » demande confirmation.
"""

import os
import threading

from gi.repository import Adw, GLib, Gtk

from ..remote import servers
from .phone_group import qr_texture


def _threaded(work, done):
    def target():
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001 — l'erreur est montrée à l'utilisateur
            result, error = None, e
        GLib.idle_add(lambda: (done(result, error), False)[1])
    threading.Thread(target=target, daemon=True).start()


class ServersGroup(Adw.PreferencesGroup):
    def __init__(self, toast=None, runner=None, pair=None, finish=None, on_change=None):
        super().__init__(title="Serveurs CCS",
                         description="Pilote d'ici les projets d'un serveur où CCS est installé (ton VPS, "
                                     "par exemple) : ses projets apparaissent dans la page Sessions.")
        self.toast = toast or (lambda _t: None)
        self.runner = runner or _threaded
        self.pair = pair or servers.pair
        self.finish = finish or servers.finish_enroll
        self.on_change = on_change
        self.dialog = None
        self.last_alert = None
        self._pending = None
        self._rows = []
        add = Gtk.Button(label="Ajouter un serveur…", valign=Gtk.Align.CENTER)
        add.connect("clicked", lambda _b: self.open_add_dialog())
        self.set_header_suffix(add)
        self.refresh()

    # ---- liste ---------------------------------------------------------------------------

    def server_names(self):
        return [s.name for s in servers.load()]

    def refresh(self):
        for row in self._rows:
            self.remove(row)
        self._rows = []
        items = servers.load()
        if not items:
            row = Adw.ActionRow(title="Aucun serveur", subtitle="Ajoute ton VPS pour piloter ses projets d'ici.")
            self.add(row)
            self._rows.append(row)
        for s in items:
            row = Adw.ActionRow(title=s.name, subtitle=f"{s.url} · {s.user}")
            btn = Gtk.Button(label="Retirer", valign=Gtk.Align.CENTER, css_classes=["flat"])
            btn.connect("clicked", lambda _b, name=s.name: self.ask_remove(name))
            row.add_suffix(btn)
            self.add(row)
            self._rows.append(row)

    def ask_remove(self, name):
        alert = Adw.AlertDialog(heading=f"Retirer le serveur « {name} » ?",
                                body="Ses projets disparaissent de la page Sessions. Pour invalider aussi "
                                     "l'accès de ce PC, révoque-le dans les Réglages → Appareils de la "
                                     "version web du serveur.")
        alert.add_response("cancel", "Annuler")
        alert.add_response("remove", "Retirer")
        alert.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        alert.set_close_response("cancel")

        def answered(_d, response):
            if response == "remove":
                servers.remove(name)
                self.refresh()
                self.toast(f"Serveur {name} retiré")
                if self.on_change:
                    self.on_change()
        alert.connect("response", answered)
        self.last_alert = alert
        if self.get_root() is not None:
            alert.present(self)

    # ---- appairage -----------------------------------------------------------------------

    def open_add_dialog(self):
        self._pending = None
        self.f_url = Gtk.Entry(placeholder_text="ccs.mawena.cloud")
        self.f_user = Gtk.Entry(text=os.environ.get("USER", ""))
        self.f_password = Gtk.PasswordEntry(show_peek_icon=True)
        self.f_code = Gtk.Entry(placeholder_text="Code à 6 chiffres", input_purpose=Gtk.InputPurpose.DIGITS,
                                max_length=6, visible=False)
        self.qr = Gtk.Picture(visible=False, can_shrink=True, width_request=200, height_request=200)
        self.secret = Gtk.Label(visible=False, selectable=True, wrap=True)
        self.message = Gtk.Label(css_classes=["error"], wrap=True, xalign=0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for label, widget in (("Adresse du serveur", self.f_url), ("Identifiant Ubuntu", self.f_user),
                              ("Mot de passe", self.f_password)):
            box.append(Gtk.Label(label=label, xalign=0, css_classes=["caption-heading"]))
            box.append(widget)
        for w in (self.qr, self.secret, self.f_code, self.message):
            box.append(w)
        dialog = Adw.AlertDialog(heading="Ajouter un serveur CCS",
                                 body="Connexion avec ton compte Ubuntu du serveur. Le mot de passe sert une "
                                      "seule fois : seul un jeton révocable est gardé sur ce PC.")
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Annuler")
        dialog.add_response("pair", "Se connecter")
        dialog.set_response_appearance("pair", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("pair")
        dialog.set_close_response("cancel")
        dialog.set_response_enabled("pair", True)
        dialog.connect("response", self._on_response)
        self.dialog = dialog
        if self.get_root() is not None:
            dialog.present(self)

    def _on_response(self, dialog, response):
        if response == "pair":
            # le dialogue se ferme tout seul après une réponse : on le garde ouvert pendant l'appairage
            self.submit()
            if self.dialog is not None and self.get_root() is not None:
                GLib.idle_add(lambda: (self.dialog and self.dialog.present(self), False)[1])
        else:
            self._close()

    def _close(self):
        if self.dialog is not None:
            self.f_password.set_text("")
            self.dialog.force_close() if self.dialog.get_parent() else None
        self.dialog = None

    def submit(self):
        url, user = self.f_url.get_text().strip(), self.f_user.get_text().strip()
        password, code = self.f_password.get_text(), self.f_code.get_text().strip()
        self.message.set_text("")
        name = f"CCS sur {os.uname().nodename}"
        if self._pending:
            pending = self._pending
            work = lambda: self.finish(url, user, pending, code, name)  # noqa: E731
        else:
            work = lambda: self.pair(url, user, password, code, name)  # noqa: E731
        self.runner(work, self._paired)

    def _paired(self, result, error):
        if error is not None:
            self.message.set_text(str(error))
            return
        if isinstance(result, servers.Server):
            self.f_password.set_text("")
            self._close()
            self.refresh()
            self.toast(f"Serveur {result.name} ajouté")
            if self.on_change:
                self.on_change()
            return
        status = result.get("status")
        if status == "code":
            self.f_code.set_visible(True)
            self.f_code.grab_focus()
        elif status == "enroll":
            self._pending = result.get("pending")
            self.qr.set_paintable(qr_texture(f"otpauth://totp/CCS:{self.f_user.get_text()}?secret={result.get('secret')}&issuer=CCS"))
            self.qr.set_visible(True)
            self.secret.set_text(f"Première connexion : scanne ce QR code dans ton application de codes "
                                 f"(ou saisis la clé {result.get('secret')}), puis le code affiché.")
            self.secret.set_visible(True)
            self.f_code.set_visible(True)
        elif status == "blocked":
            self.message.set_text(f"Trop d'essais : réessaie dans {max(1, int(result.get('retry_after', 60)) // 60)} min.")
        else:
            self.message.set_text(result.get("message") or "Connexion impossible.")
