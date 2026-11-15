"""Dialogue « Nouvelle session » : dossier, compte, modèle et mode de permissions.

Le dialogue ne bascule jamais de compte et ne lance rien : il renvoie un
`launch_options.LaunchSpec` à `on_ok`. Si `spec.needs_switch(compte actif)`, l'appelant
bascule (« ccs use <profil> ») puis ouvre la session (launch_options.launch ou
terminal intégré).

Compte présélectionné : celui du projet du dossier choisi (`project_accounts`), sauf
pendant une pause de CCS ou si le projet ne propose plus la bascule ; sinon le compte
actif. Un compte choisi à la main n'est plus changé par un changement de dossier.
"""

import os

from gi.repository import Adw, Gio, GLib, Gtk

from .. import core, launch_options, project_accounts, sessions
from ..launch_options import LaunchSpec
from .common import in_thread
from .doctor_dialog import plain_row
from .project_account_dialog import paused_now

SWITCH_WARNING = "La bascule s'applique à toutes les sessions ouvertes"


def short_path(path):
    home = str(core.paths().home)
    if path == home:
        return "~"
    return "~" + path[len(home):] if path.startswith(home + "/") else path


class NewSessionDialog(Adw.Dialog):
    """`profiles` (liste de core.Profile), `recent` ([(dossier, date)]), `associations`
    (comptes par projet) et `paused` (CCS en pause) sont lus sur le disque s'ils ne sont
    pas fournis."""

    def __init__(self, default_cwd, on_ok, profiles=None, recent=None, associations=None, paused=None):
        super().__init__(title="Nouvelle session", content_width=520, content_height=660)
        self.on_ok = on_ok
        self.folders = []
        self.profiles = list(core.list_profiles() if profiles is None else profiles)
        self.active = next((p.name for p in self.profiles if p.active), None)
        if associations is None:
            try:
                associations = project_accounts.all()
            except OSError:
                associations = []
        self.assocs = list(associations)
        self.paused = paused_now() if paused is None else paused
        self.profile_touched = False   # compte choisi à la main : plus de présélection
        self.selecting = False

        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label="Annuler")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self.ok_btn = Gtk.Button(label="Ouvrir", css_classes=["suggested-action"])
        self.ok_btn.connect("clicked", self.on_open)
        header.pack_end(self.ok_btn)

        page = Adw.PreferencesPage()
        where = Adw.PreferencesGroup(title="Où")
        self.folder_model = Gtk.StringList()
        self.folder_row = Adw.ComboRow(title="Dossier", model=self.folder_model)
        self.folder_row.connect("notify::selected", lambda *_: self.update())
        choose = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                            tooltip_text="Choisir un autre dossier…")
        choose.connect("clicked", self.on_choose_folder)
        self.folder_row.add_suffix(choose)
        where.add(self.folder_row)
        page.add(where)

        who = Adw.PreferencesGroup(title="Compte")
        self.profile_row = Adw.ComboRow(title="Compte Claude", use_markup=False, model=Gtk.StringList.new(
            [f"{p.name} — {p.email}" + (" (actif)" if p.active else "") for p in self.profiles]))
        if self.active:
            self.profile_row.set_selected(next(i for i, p in enumerate(self.profiles) if p.active))
        self.profile_row.connect("notify::selected", self.on_profile_chosen)
        who.add(self.profile_row)
        self.switch_row = plain_row(SWITCH_WARNING, "Les sessions déjà ouvertes passeront aussi sur ce "
                                                    "compte à leur prochaine requête.")
        self.switch_row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic", css_classes=["warning"]))
        who.add(self.switch_row)
        who.set_visible(bool(self.profiles))
        page.add(who)

        how = Adw.PreferencesGroup(title="Options de Claude Code")
        self.model_row = Adw.ComboRow(title="Modèle", model=Gtk.StringList.new(
            [label for label, _v in launch_options.MODELS]))
        how.add(self.model_row)
        self.mode_row = Adw.ComboRow(title="Permissions", model=Gtk.StringList.new(
            [label for label, _v in launch_options.PERMISSION_MODES]))
        self.mode_row.connect("notify::selected", lambda *_: self.update())
        how.add(self.mode_row)
        self.danger_row = plain_row("Claude pourra tout faire sans rien demander",
                                    "À réserver à un dossier jetable ou à une machine isolée.")
        self.danger_row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic", css_classes=["error"]))
        how.add(self.danger_row)
        page.add(how)

        view = Adw.ToolbarView(content=page)
        view.add_top_bar(header)
        self.set_child(view)
        self.set_default_widget(self.ok_btn)

        self.add_folder(default_cwd)
        self.folder_row.set_selected(0)
        if recent is None:
            in_thread(_recent_or_empty, self.add_recent)
        else:
            self.add_recent(recent)
        self.update()

    # ---- dossiers ----------------------------------------------------------------------

    def add_folder(self, path, select=False):
        if not path:
            return
        path = os.path.abspath(os.path.expanduser(path))
        if path not in self.folders:
            self.folders.append(path)
            self.folder_model.append(short_path(path))
        if select:
            self.folder_row.set_selected(self.folders.index(path))

    def add_recent(self, recent):
        selected = self.selected_folder()
        for cwd, _ts in recent or []:
            self.add_folder(cwd)
        if selected in self.folders:
            self.folder_row.set_selected(self.folders.index(selected))
        self.update()

    def selected_folder(self):
        i = self.folder_row.get_selected()
        return self.folders[i] if 0 <= i < len(self.folders) else None

    def on_choose_folder(self, *_):
        dialog = Gtk.FileDialog(title="Dossier de la session", accept_label="Choisir", modal=True)
        start = self.selected_folder()
        if start and os.path.isdir(start):
            dialog.set_initial_folder(Gio.File.new_for_path(start))

        def done(d, result):
            try:
                chosen = d.select_folder_finish(result)
            except GLib.Error:
                return  # annulé
            if chosen is not None and chosen.get_path():
                self.add_folder(chosen.get_path(), select=True)
                self.update()
        dialog.select_folder(self.get_root(), None, done)

    # ---- choix -------------------------------------------------------------------------

    def on_profile_chosen(self, *_):
        if self.selecting:
            return
        self.profile_touched = True
        self.update()

    def select_profile(self, name):
        names = [p.name for p in self.profiles]
        if name in names and self.profile_row.get_selected() != names.index(name):
            self.selecting = True
            self.profile_row.set_selected(names.index(name))
            self.selecting = False

    def project_account(self, folder):
        """Présélectionne le compte du projet (sauf choix fait à la main) et l'indique."""
        names = [p.name for p in self.profiles]
        hint = project_accounts.hint(folder, names, self.paused, self.assocs) if folder else None
        self.profile_row.set_subtitle(hint or "")
        if not self.profile_touched:
            self.select_profile(project_accounts.preferred_profile(folder, names, self.paused, self.assocs)
                                or self.active)

    def selected_profile(self):
        i = self.profile_row.get_selected()
        return self.profiles[i].name if 0 <= i < len(self.profiles) else None

    def selected_model(self):
        i = self.model_row.get_selected()
        return launch_options.MODELS[i][1] if 0 <= i < len(launch_options.MODELS) else None

    def selected_mode(self):
        i = self.mode_row.get_selected()
        return launch_options.PERMISSION_MODES[i][1] if 0 <= i < len(launch_options.PERMISSION_MODES) else None

    def spec(self):
        folder, profile = self.selected_folder(), self.selected_profile()
        origin = project_accounts.origin_for(folder, profile, self.assocs) if profile != self.active else None
        return LaunchSpec(cwd=folder, profile=profile, model=self.selected_model(),
                          permission_mode=self.selected_mode(), origin=origin)

    def update(self):
        folder = self.selected_folder()
        self.folder_row.set_tooltip_text(folder)
        ok = bool(folder) and os.path.isdir(folder)
        self.ok_btn.set_sensitive(ok)
        self.ok_btn.set_tooltip_text(None if ok else "Ce dossier n'existe pas")
        self.project_account(folder)
        profile = self.selected_profile()
        self.switch_row.set_visible(bool(profile) and profile != self.active)
        mode = self.selected_mode()
        self.mode_row.set_subtitle(launch_options.permission_help(mode))
        self.danger_row.set_visible(launch_options.is_dangerous(mode))

    def on_open(self, *_):
        if not self.ok_btn.get_sensitive():
            return
        spec = self.spec()
        self.close()
        self.on_ok(spec)


def _recent_or_empty():
    try:
        return sessions.recent_projects()
    except OSError:
        return []


def ask_new_session(parent, default_cwd, on_ok, profiles=None, recent=None, associations=None, paused=None):
    """Ouvre le dialogue ; `on_ok(LaunchSpec)` est appelé quand l'utilisateur valide."""
    dialog = NewSessionDialog(default_cwd, on_ok, profiles, recent, associations, paused)
    dialog.present(parent)
    return dialog
