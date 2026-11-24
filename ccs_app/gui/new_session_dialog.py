"""Dialogue « Nouvelle session » : dossier, compte, fournisseur, modèle, effort et droits.

Mêmes champs, même ordre et mêmes valeurs par défaut que la feuille du web
(web/sessions-new.js) : les listes viennent de `chat_options.new_session_form`, les
fournisseurs de `providers.choices`. Deux boutons comme au web : « Terminal » (`on_term(dossier)`,
un terminal dans le dossier) et « Ouvrir un chat ».

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

from .. import chat_options, core, launch_options, project_accounts, providers, sessions, settings
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
    pas fournis, comme les réglages (`prefs`, pour les droits par défaut)."""

    def __init__(self, default_cwd, on_ok, profiles=None, recent=None, associations=None, paused=None,
                 on_term=None, prefs=None):
        super().__init__(title="Nouvelle session", content_width=520, content_height=700)
        self.on_ok = on_ok
        self.on_term = on_term
        self.form = chat_options.new_session_form(settings.load_settings() if prefs is None else prefs)
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
        self.ok_btn = Gtk.Button(label="Ouvrir un chat", css_classes=["suggested-action"])
        self.ok_btn.connect("clicked", self.on_open)
        header.pack_end(self.ok_btn)
        self.term_btn = Gtk.Button(label="Terminal", tooltip_text="Terminal dans ce dossier",
                                   visible=on_term is not None)
        self.term_btn.connect("clicked", self.on_terminal)
        header.pack_end(self.term_btn)

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

        how = Adw.PreferencesGroup(title="Options")
        # Fournisseur : Claude, ou un autre service (OpenRouter…) qui fournit le modèle
        self.providers = providers.choices()
        self.provider_row = Adw.ComboRow(title="Fournisseur", model=Gtk.StringList.new(
            [label for _n, label, _m in self.providers]))
        self.provider_row.set_visible(len(self.providers) > 1)
        self.provider_row.connect("notify::selected", lambda *_: self.provider_changed())
        how.add(self.provider_row)
        self.model_values = self.claude_models()
        self.model_row = Adw.ComboRow(title="Modèle", model=Gtk.StringList.new(
            [label for label, _v in self.model_values]))
        how.add(self.model_row)
        # Effort : propre aux modèles Claude (caché pour un autre fournisseur)
        self.efforts = [(v or None, label) for v, label in self.form["efforts"]]
        self.effort_row = Adw.ComboRow(title="Effort", model=Gtk.StringList.new(
            [label for _v, label in self.efforts]))
        how.add(self.effort_row)
        self.rights = [(v, label) for v, label in self.form["rights"]]
        self.mode_row = Adw.ComboRow(title="Droits", model=Gtk.StringList.new(
            [label for _v, label in self.rights]))
        values = [v for v, _l in self.rights]
        if self.form["default_rights"] in values:
            self.mode_row.set_selected(values.index(self.form["default_rights"]))
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

    def selected_provider(self):
        i = self.provider_row.get_selected()
        name = self.providers[i][0] if 0 <= i < len(self.providers) else "claude"
        return None if providers.is_claude(name) else name

    def claude_models(self):
        return [(label, v or None) for v, label in self.form["models"]]

    def provider_changed(self):
        i = self.provider_row.get_selected()
        models = self.providers[i][2] if 0 <= i < len(self.providers) else []
        self.model_values = list(models) if self.selected_provider() else self.claude_models()
        self.model_row.set_model(Gtk.StringList.new([label for label, _v in self.model_values]))
        self.model_row.set_selected(0)
        self.update()

    def provider_problem(self):
        if not hasattr(self, "provider_row"):
            return None          # update() appelé pendant la construction
        name = self.selected_provider()
        if not name:
            return None
        try:
            return providers.key_problem(providers.get(name))
        except ValueError as e:
            return str(e)

    def selected_model(self):
        i = self.model_row.get_selected()
        return self.model_values[i][1] if 0 <= i < len(self.model_values) else None

    def selected_effort(self):
        if self.selected_provider():
            return None
        i = self.effort_row.get_selected()
        return self.efforts[i][0] if 0 <= i < len(self.efforts) else None

    def selected_mode(self):
        i = self.mode_row.get_selected()
        return self.rights[i][0] if 0 <= i < len(self.rights) else None

    def spec(self):
        folder, profile = self.selected_folder(), self.selected_profile()
        origin = project_accounts.origin_for(folder, profile, self.assocs) if profile != self.active else None
        return LaunchSpec(cwd=folder, profile=profile, model=self.selected_model(),
                          permission_mode=self.selected_mode(), origin=origin,
                          provider=self.selected_provider(), effort=self.selected_effort())

    def update(self):
        folder = self.selected_folder()
        self.folder_row.set_tooltip_text(folder)
        ok = bool(folder) and os.path.isdir(folder)
        problem = self.provider_problem()
        if hasattr(self, "provider_row"):
            self.provider_row.set_subtitle(problem or "")
        self.ok_btn.set_sensitive(ok and not problem)
        self.term_btn.set_sensitive(ok)
        if hasattr(self, "effort_row"):
            self.effort_row.set_visible(not self.selected_provider())
        self.ok_btn.set_tooltip_text(problem if problem else None if ok else "Ce dossier n'existe pas")
        self.project_account(folder)
        profile = self.selected_profile()
        self.switch_row.set_visible(bool(profile) and profile != self.active)
        mode = self.selected_mode()
        self.mode_row.set_subtitle(launch_options.permission_help(mode))
        self.danger_row.set_visible(mode in self.form["dangerous"])

    def on_open(self, *_):
        if not self.ok_btn.get_sensitive():
            return
        spec = self.spec()
        self.close()
        self.on_ok(spec)

    def on_terminal(self, *_):
        """« Terminal » comme au web : un terminal dans le dossier, sans bascule ni options."""
        folder = self.selected_folder()
        if self.on_term is None or not folder or not os.path.isdir(folder):
            return
        self.close()
        self.on_term(folder)


def _recent_or_empty():
    try:
        return sessions.recent_projects()
    except OSError:
        return []


def ask_new_session(parent, default_cwd, on_ok, profiles=None, recent=None, associations=None, paused=None,
                    on_term=None, prefs=None):
    """Ouvre le dialogue ; `on_ok(LaunchSpec)` est appelé quand l'utilisateur valide,
    `on_term(dossier)` pour « Terminal ». Une fenêtre pas encore affichée (lancement par
    `--new-session`) reçoit le dialogue quand elle apparaît, jamais avant."""
    dialog = NewSessionDialog(default_cwd, on_ok, profiles, recent, associations, paused, on_term, prefs)
    present_when_mapped(dialog, parent)
    return dialog


def present_when_mapped(dialog, parent):
    if parent is None or parent.get_mapped():
        dialog.present(parent)
        return

    def mapped(widget):
        widget.disconnect(handler)
        dialog.present(widget)
    handler = parent.connect("map", mapped)
