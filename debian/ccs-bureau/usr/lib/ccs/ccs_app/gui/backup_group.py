"""Groupe « Sauvegarde » des Réglages : sauvegarde chiffrée des comptes et réglages.

Deux lignes : « Sauvegarder… » (choix du fichier, puis gpg demande la phrase de passe dans
sa propre fenêtre) et « Restaurer… » (choix du fichier, phrase de passe, puis un dialogue
liste le contenu et les profils que la restauration écraserait). gpg tourne dans un fil :
l'interface ne se fige pas pendant la saisie de la phrase de passe.

    from .backup_group import BackupGroup
    page.add(BackupGroup(toast=window.toast))

Tout passe par `ccs_app.backup`. `runner(work, done)` (injectable, pour les tests) lance
`work()` hors du fil de l'interface et appelle `done(résultat, erreur)` dans celui-ci.
"""

import threading

from gi.repository import Adw, GLib, Gtk

from .. import backup


def _threaded(work, done):
    def target():
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001 — l'erreur est montrée à l'utilisateur
            result, error = None, e
        GLib.idle_add(lambda: (done(result, error), False)[1])
    threading.Thread(target=target, daemon=True).start()


def _message(error):
    return str(error) if isinstance(error, backup.BackupError) else f"Sauvegarde impossible : {error}"


class BackupGroup(Adw.PreferencesGroup):
    def __init__(self, toast=None, runner=None, backend=None):
        super().__init__(title="Sauvegarde",
                         description="Comptes (jetons compris), réglages, comptes par projet, budgets "
                                     "et raccourcis, chiffrés par gpg (AES256). La phrase de passe est "
                                     "demandée par gpg : sans elle, la sauvegarde est perdue.")
        self._toast, self._runner, self.backend = toast, runner or _threaded, backend
        self.dialog = None   # dernier dialogue de confirmation (tests)
        self.busy = False
        self.save_row = self._row("Sauvegarder…", "Crée un fichier chiffré", "document-save-symbolic",
                                  self.choose_save)
        self.restore_row = self._row("Restaurer…", "Relit une sauvegarde et remet les comptes en place",
                                     "document-open-symbolic", self.choose_open)
        self.add(self.save_row)
        self.add(self.restore_row)

    def _row(self, title, subtitle, icon, callback):
        row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True, use_markup=False)
        row.add_prefix(Gtk.Image(icon_name=icon))
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda *_: callback())
        return row

    # ---- sorties ---------------------------------------------------------------------

    def toast(self, text):
        show = self._toast or getattr(self.get_root(), "toast", None)
        if show:
            show(text)

    def _set_busy(self, busy, text=None):
        self.busy = busy
        for row, default in ((self.save_row, "Crée un fichier chiffré"),
                             (self.restore_row, "Relit une sauvegarde et remet les comptes en place")):
            row.set_sensitive(not busy)
            row.set_subtitle(text if busy and text else default)

    def _run(self, text, work, done):
        if self.busy:
            return
        self._set_busy(True, text)

        def finished(result, error):
            self._set_busy(False)
            done(result, error)
        self._runner(work, finished)

    # ---- sauvegarder -----------------------------------------------------------------

    def choose_save(self):
        dialog = Gtk.FileDialog(title="Sauvegarder les comptes", accept_label="Sauvegarder",
                                initial_name=backup.default_name(), modal=True)

        def done(d, result):
            try:
                chosen = d.save_finish(result)
            except GLib.Error:
                return  # annulé
            if chosen is not None and chosen.get_path():
                self.start_save(chosen.get_path())
        dialog.save(self.get_root(), None, done)

    def start_save(self, path):
        """Crée la sauvegarde `path` ; gpg demande la phrase de passe dans sa fenêtre."""
        def finished(contents, error):
            if error is not None:
                self.toast(_message(error))
            else:
                self.toast(f"Sauvegarde écrite : {len(contents.profiles)} profil(s), "
                           f"{len(contents.files)} fichier(s) de réglages")
        self._run("Saisis la phrase de passe dans la fenêtre de gpg…",
                  lambda: backup.create(path, backend=self.backend), finished)

    # ---- restaurer -------------------------------------------------------------------

    def choose_open(self):
        dialog = Gtk.FileDialog(title="Restaurer une sauvegarde", accept_label="Ouvrir", modal=True)

        def done(d, result):
            try:
                chosen = d.open_finish(result)
            except GLib.Error:
                return
            if chosen is not None and chosen.get_path():
                self.start_restore(chosen.get_path())
        dialog.open(self.get_root(), None, done)

    def start_restore(self, path):
        """Déchiffre `path` (phrase de passe dans la fenêtre de gpg), puis demande confirmation."""
        def finished(bak, error):
            if error is not None:
                self.toast(_message(error))
            else:
                self.confirm(bak)
        self._run("Saisis la phrase de passe dans la fenêtre de gpg…",
                  lambda: backup.open_backup(path), finished)

    def confirm(self, bak):
        """Dialogue de confirmation : contenu de la sauvegarde et profils écrasés."""
        over = bak.conflicts()
        body = backup.describe(bak.contents)
        if over:
            body += "\n\nSeront remplacés : " + ", ".join(over) + "."
        else:
            body += "\n\nRien d'existant ne sera écrasé."
        body += "\nLe compte actif ne change pas."
        d = Adw.AlertDialog(heading="Restaurer cette sauvegarde ?", body=body)
        d.add_response("cancel", "Annuler")
        d.add_response("restore", "Restaurer")
        if over:
            d.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "restore" and self.restore(bak))
        self.dialog = d
        d.present(self.get_root())

    def restore(self, bak):
        """Écrit les profils et réglages (après la confirmation du dialogue)."""
        def finished(result, error):
            if error is not None:
                self.toast(_message(error))
                return
            self.toast("Sauvegarde restaurée : " + (", ".join(result.profiles) or "aucun profil"))
            root = self.get_root()
            refresh = getattr(root, "refresh", None)
            if callable(refresh):
                refresh()
        self._run("Restauration…",
                  lambda: bak.restore(assume_yes=True, backend=self.backend), finished)
