"""Onglet Conversations : tout l'historique Claude Code du PC, recherche et reprise."""

import time
from dataclasses import replace
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .. import conversations, core, sessions, terminal
from .common import caption, clear, in_thread

PAGE_SIZE = 60
REFRESH_S = 30
RERENDER_S = 60                       # les « il y a … » vieillissent : re-rendu au moins chaque minute
RELOAD_AFTER_RESUME_MS = (2000, 8000)  # le temps que la session reprise apparaisse
ORIGIN_CHOICES = (("Toutes les origines", None), ("VS Code", "vscode"), ("Terminal", "terminal"))
TARGETS = {  # icône, libellé du bouton, infobulle, message après reprise
    "vscode": ("text-editor-symbolic", "VS Code", "Reprendre dans VS Code", "Conversation rouverte dans VS Code"),
    # « terminal » : terminal intégré à l'application s'il est disponible, sinon externe.
    "terminal": ("utilities-terminal-symbolic", "Terminal", "Reprendre dans l'application", None),
    "external": ("utilities-terminal-symbolic", "Terminal externe", "Reprendre dans un terminal externe",
                 "Conversation rouverte dans un nouveau terminal"),
}


def short_path(path):
    """Chemin avec ~ pour le dossier personnel."""
    home = str(core.paths().home)
    if path == home:
        return "~"
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def plural(n, word):
    return f"{n} {word}{'s' if n > 1 else ''}"


def cap(text):
    return text[:1].upper() + text[1:]


def error_text(e):
    if isinstance(e, FileNotFoundError) and e.filename:
        return f"Introuvable : {e.filename}"
    if e.strerror:
        return f"Échec : {e.strerror}" + (f" ({e.filename})" if e.filename else "")
    return cap(str(e))


def existing_parent(path):
    """Plus proche dossier existant en remontant depuis `path`, ou None."""
    p = Path(path) if path else None
    while p is not None and not p.is_dir():
        p = p.parent if p.parent != p else None
    return str(p) if p else None


def string_factory(ellipsize):
    """Fabrique de libellés pour un Gtk.DropDown de chaînes."""
    f = Gtk.SignalListItemFactory()
    mode = Pango.EllipsizeMode.END if ellipsize else Pango.EllipsizeMode.NONE
    f.connect("setup", lambda _f, item: item.set_child(Gtk.Label(xalign=0, ellipsize=mode)))
    f.connect("bind", lambda _f, item: item.get_child().set_label(item.get_item().get_string()))
    return f


class ConversationsPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.visible_page = False
        self.convs = None          # None tant que la première lecture n'est pas finie
        self.opened = set()
        self.suggestions = {}      # identifiant -> dossier probable (dossier d'origine disparu)
        self.by_id = {}
        self.limit = PAGE_SIZE
        self.loading = False
        self.again = None          # relecture demandée pendant une lecture (valeur de `quiet`)
        self.signature = None
        self.rendered_at = 0.0
        self.menus = []
        self.project_values = [None]
        self.syncing = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=18, margin_bottom=18, margin_start=12, margin_end=12)
        filters = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text="Rechercher dans les conversations…", hexpand=True)
        self.search.connect("search-changed", self.on_filter)
        self.search.set_key_capture_widget(self)  # taper n'importe où sur la page lance la recherche
        filters.append(self.search)
        self.project_model = Gtk.StringList.new(["Tous les projets"])
        self.project_drop = self.dropdown(self.project_model, "Filtrer par projet")
        self.project_drop.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self.project_drop.set_enable_search(True)
        self.project_drop.set_search_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
        filters.append(self.project_drop)
        self.origin_drop = self.dropdown(Gtk.StringList.new([label for label, _ in ORIGIN_CHOICES]),
                                         "Filtrer par origine")
        filters.append(self.origin_drop)
        box.append(filters)
        self.count = caption("")
        self.count.set_visible(False)
        box.append(self.count)
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self.results)
        self.set_child(Adw.Clamp(maximum_size=820, child=box))

        # Actions des menus « ⋮ » des lignes : conv.copy('<id>'), conv.folder, conv.relocate,
        # conv.rename, conv.external.
        actions = Gio.SimpleActionGroup()
        for name, handler in (("copy", self.copy_command), ("folder", self.open_folder),
                              ("relocate", self.choose_folder), ("rename", self.rename),
                              ("external", lambda c: self.resume(c, "external"))):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            a.connect("activate", lambda _a, v, h=handler: self.with_conv(v.get_string(), h))
            actions.add_action(a)
        self.insert_action_group("conv", actions)
        GLib.timeout_add_seconds(REFRESH_S, self._tick)

    def dropdown(self, model, tooltip):
        drop = Gtk.DropDown(model=model, tooltip_text=tooltip, valign=Gtk.Align.CENTER,
                            factory=string_factory(True), list_factory=string_factory(False))
        drop.connect("notify::selected", self.on_filter)
        return drop

    def _tick(self):
        if self.visible_page:
            self.load(quiet=True)
        return True

    # ---- données -------------------------------------------------------------

    def load(self, quiet=False):
        """Relit l'historique dans un thread. `quiet` (relecture périodique) : pas de
        re-rendu pendant que l'utilisateur a un menu ouvert ou le focus dans la liste."""
        if self.loading:
            self.again = quiet if self.again is None else (self.again and quiet)
            return
        self.loading = True
        if self.convs is None:
            self.show_waiting()

        def work():
            try:
                convs = conversations.scan()
                return convs, conversations.open_ids(), conversations.suggest_folders(convs)
            except Exception as e:  # noqa: BLE001 — affiché plutôt qu'un sablier sans fin
                return e
        in_thread(work, lambda result: self.loaded(result, quiet))

    def loaded(self, result, quiet):
        self.loading = False
        if isinstance(result, Exception):
            if self.convs is None:
                self.convs = []
                clear(self.results)
                self.results.append(Adw.StatusPage(icon_name="dialog-error-symbolic",
                                                   title="Lecture impossible", description=str(result)))
            # Relecture ratée : on garde la liste déjà affichée.
        else:
            convs, opened, suggestions = result
            first = self.convs is None
            self.convs, self.opened, self.suggestions = convs, opened, suggestions
            self.by_id = {c.session_id: c for c in convs}
            self.sync_projects()
            signature = (tuple((c.session_id, c.cwd, c.title, c.prompts, c.updated_at, c.folder_exists)
                               for c in convs), frozenset(opened), tuple(sorted(suggestions.items())))
            stale = signature != self.signature or time.time() - self.rendered_at >= RERENDER_S
            if first or (stale and not (quiet and self.user_busy())):
                self.signature = signature
                self.render()
        if self.again is not None:
            quiet, self.again = self.again, None
            self.load(quiet)

    def user_busy(self):
        if any(m.get_active() for m in self.menus):
            return True
        focus = self.window.get_focus() if hasattr(self.window, "get_focus") else None
        return focus is not None and focus.is_ancestor(self.results)

    def sync_projects(self):
        """Remplit la liste des projets en gardant le projet choisi."""
        found = conversations.projects(self.convs)
        names = {}
        for cwd, _n in found:
            names.setdefault(sessions.project_name(cwd), []).append(cwd)
        labels, values = ["Tous les projets"], [None]
        for cwd, n in found:
            name = sessions.project_name(cwd)
            if len(names[name]) > 1:  # deux projets du même nom : on montre le chemin
                name = short_path(cwd) or "?"
            labels.append(f"{name} ({n})")
            values.append(cwd)
        current = self.selected_project()
        old = [self.project_model.get_string(i) for i in range(self.project_model.get_n_items())]
        if labels == old and values == self.project_values:
            return
        self.syncing = True
        self.project_model.splice(0, self.project_model.get_n_items(), labels)
        self.project_values = values
        self.project_drop.set_selected(values.index(current) if current in values else 0)
        self.syncing = False

    def selected_project(self):
        i = self.project_drop.get_selected()
        return self.project_values[i] if i < len(self.project_values) else None

    def filtered(self):
        project = self.selected_project()
        i = self.origin_drop.get_selected()
        origin = ORIGIN_CHOICES[i][1] if i < len(ORIGIN_CHOICES) else None
        found = conversations.search(self.convs, self.search.get_text(), project or None, origin)
        if project == "":  # search() ne sait pas filtrer « dossier inconnu »
            found = [c for c in found if not c.cwd]
        return found

    def on_filter(self, *_):
        if self.syncing or not self.convs:
            return
        self.limit = PAGE_SIZE
        self.render()
        self.get_vadjustment().set_value(0)

    def on_more(self, *_):
        self.limit += PAGE_SIZE
        self.render()

    def rerender(self):
        """Re-rendu après un changement des onglets du terminal intégré (boutons « Afficher »)."""
        if self.convs and not self.user_busy():
            self.render()

    # ---- rendu ---------------------------------------------------------------

    def show_waiting(self):
        clear(self.results)
        self.count.set_visible(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      halign=Gtk.Align.CENTER, margin_top=48)
        spinner = Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True)
        spinner.set_size_request(32, 32)
        box.append(spinner)
        box.append(Gtk.Label(label="Lecture de l'historique…", css_classes=["dim-label"]))
        self.results.append(box)

    def render(self):
        self.rendered_at = time.time()
        self.menus = []
        clear(self.results)
        if not self.convs:
            self.count.set_visible(False)
            self.results.append(Adw.StatusPage(
                icon_name="chat-message-new-symbolic", title="Aucune conversation",
                description="Les conversations Claude Code de ce PC apparaîtront ici."))
            return
        found = self.filtered()
        total = len(self.convs)
        self.count.set_label(plural(len(found), "conversation") + (f" sur {total}" if len(found) != total else ""))
        self.count.set_visible(True)
        if not found:
            self.results.append(Adw.StatusPage(
                icon_name="edit-find-symbolic", title="Aucun résultat",
                description="Essaie d'autres mots ou retire les filtres."))
            return
        code = conversations.vscode_bin()
        for label, group in conversations.group_by_day(found[:self.limit]):
            self.results.append(Gtk.Label(label=label, xalign=0, css_classes=["heading"], margin_top=6))
            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=False,
                                  css_classes=["boxed-list"])
            for c in group:
                listbox.append(self.row(c, code))
            # Entrée ou double-clic : reprise là où la conversation est née.
            listbox.connect("row-activated", lambda _lb, row, g=group: self.activate(g[row.get_index()]))
            self.results.append(listbox)
        rest = len(found) - self.limit
        if rest > 0:
            more = Gtk.Button(label=f"Afficher {min(PAGE_SIZE, rest)} de plus", css_classes=["pill"],
                              halign=Gtk.Align.CENTER, margin_top=6)
            more.connect("clicked", self.on_more)
            self.results.append(more)

    def row(self, c, code):
        row = Gtk.ListBoxRow(activatable=True, tooltip_text=self.tooltip(c))
        box = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=12, margin_end=8)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True,
                       valign=Gtk.Align.CENTER)
        top = Gtk.Box(spacing=8)
        top.append(Gtk.Label(label=c.title, xalign=0, ellipsize=Pango.EllipsizeMode.END))
        if c.session_id in self.opened:
            top.append(Gtk.Label(label="ouverte", valign=Gtk.Align.CENTER, css_classes=["badge", "active"]))
        info.append(top)
        meta = [c.project, c.origin_label] + ([c.git_branch] if c.git_branch else [])
        meta += [plural(c.prompts, "demande"), conversations.ago(c.updated_at)]
        info.append(caption(" · ".join(meta)))
        suggestion = self.suggestions.get(c.session_id) if not c.folder_exists else None
        if not c.folder_exists:
            line = Gtk.Box()
            line.append(Gtk.Label(label="dossier introuvable", xalign=0, css_classes=["caption", "error"]))
            if suggestion:
                line.append(Gtk.Label(label=f" · déplacé vers {short_path(suggestion)} ?", xalign=0,
                                      hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE,
                                      css_classes=["caption", "dim-label"]))
            info.append(line)
        box.append(info)

        buttons = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER)
        tab = self.window.terminals.find(session_id=c.session_id)
        embedded = self.window.terminals.available
        problem = self.problem(c)
        where = f" depuis {short_path(suggestion)}" if suggestion else ""
        if tab is not None:
            b = Gtk.Button(child=Adw.ButtonContent(icon_name="go-next-symbolic", label="Afficher"),
                           css_classes=["flat"], tooltip_text="Ouverte dans l'application : aller à son onglet")
            b.connect("clicked", lambda *_: self.window.terminals.present(tab))
            buttons.append(b)
        for target in () if tab is not None else ("vscode", "terminal") if code else ("terminal",):
            icon, short, label, _toast = TARGETS[target]
            if target == "terminal" and not embedded:
                label = f"Reprendre dans un terminal externe (terminal intégré : {terminal.VTE_PACKAGE})"
            b = Gtk.Button(child=Adw.ButtonContent(icon_name=icon, label=short), css_classes=["flat"],
                           sensitive=problem is None, tooltip_text=cap(problem) if problem else label + where)
            b.connect("clicked", lambda *_, t=target: self.resume(c, t))
            buttons.append(b)
        menu = Gio.Menu()
        entries = [("Copier la commande", "conv.copy")]
        if embedded and tab is None and problem is None:
            entries.append(("Reprendre dans un terminal externe", "conv.external"))
        entries.append(("Ouvrir le dossier", "conv.folder") if c.folder_exists
                       else ("Reprendre depuis un autre dossier…", "conv.relocate"))
        entries.append(("Renommer…", "conv.rename"))
        for label, action in entries:
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(action, GLib.Variant.new_string(c.session_id))
            menu.append_item(item)
        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, css_classes=["flat"],
                              tooltip_text="Autres actions")
        self.menus.append(more)
        buttons.append(more)
        box.append(buttons)
        row.set_child(box)
        return row

    @staticmethod
    def tooltip(c):
        lines = [f"Première demande : {c.first_prompt}"]
        if c.last_prompt and c.last_prompt != c.first_prompt:
            lines.append(f"Dernière demande : {c.last_prompt}")
        lines += [f"Dossier : {c.cwd or '?'}", f"Identifiant : {c.session_id}"]
        return "\n".join(lines)

    # ---- actions -------------------------------------------------------------

    def with_conv(self, session_id, handler):
        conv = self.by_id.get(session_id)
        if conv is not None:
            handler(conv)

    def problem(self, conv, elsewhere=False):
        """Raison d'empêcher la reprise ; un dossier disparu ne bloque pas quand on sait
        d'où reprendre (dossier proposé, ou choisi si `elsewhere`)."""
        if not conv.folder_exists and (elsewhere or self.suggestions.get(conv.session_id)):
            conv = replace(conv, folder_exists=True)
        return conversations.resume_problem(conv, self.opened)

    def activate(self, conv):
        tab = self.window.terminals.find(session_id=conv.session_id)
        if tab is not None:
            self.window.terminals.present(tab)
            return
        self.resume(conv, conversations.preferred_target(conv))

    def resume(self, conv, target, folder=None):
        tab = self.window.terminals.find(session_id=conv.session_id)
        if tab is not None and target != "vscode":
            self.window.terminals.present(tab)  # déjà dans un onglet de l'application
            return
        problem = self.problem(conv, elsewhere=bool(folder))
        if problem:
            self.window.toast(cap(problem))
            return
        if conv.folder_exists:
            self.launch(conv, target)
        elif folder:
            self.relocate(conv, target, folder)
        else:
            self.confirm_suggestion(conv, target)

    def confirm_suggestion(self, conv, target):
        """Le dossier proposé n'est qu'une supposition (même nom) : on demande avant de copier."""
        suggestion = self.suggestions.get(conv.session_id)
        d = Adw.AlertDialog(heading="Reprendre depuis ce dossier ?",
                            body=f"Le dossier d'origine n'existe plus :\n{short_path(conv.cwd)}\n"
                                 f"CCS a trouvé un dossier du même nom :\n{short_path(suggestion)}\n"
                                 "Le journal y sera copié (l'original reste en place).")
        d.add_response("cancel", "Annuler")
        d.add_response("choose", "Choisir un autre dossier…")
        d.add_response("resume", "Reprendre")
        d.set_response_appearance("resume", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("resume")
        d.set_close_response("cancel")

        def on_response(_d, r):
            if r == "resume":
                self.relocate(conv, target, suggestion)
            elif r == "choose":
                self.choose_folder(conv, target)
        d.connect("response", on_response)
        d.present(self.window)

    def relocate(self, conv, target, folder):
        """Copie le journal là où Claude Code le cherchera depuis `folder`, puis reprend."""
        def work():
            try:
                return conversations.relocate(conv, folder)
            except OSError as e:
                return e
        in_thread(work, lambda r: self.window.toast(error_text(r)) if isinstance(r, Exception)
                  else self.launch(r, target))

    def launch(self, conv, target):
        try:
            if target == "vscode":
                conversations.resume_vscode(conv)
                where = "vscode"
            else:
                where = self.window.open_claude(conv.cwd, conv.session_id, conv.title,
                                                external=target == "external")
        except OSError as e:
            self.window.toast(error_text(e))
            return
        if where != "integre":
            self.window.toast(TARGETS["vscode" if where == "vscode" else "external"][3])
        for delay in RELOAD_AFTER_RESUME_MS:
            GLib.timeout_add(delay, lambda: (self.load(), False)[1])

    def copy_command(self, conv):
        Gdk.Display.get_default().get_clipboard().set(conversations.resume_command(conv))
        self.window.toast("Commande copiée")

    def open_folder(self, conv):
        sessions.open_folder(conv.cwd)

    def rename(self, conv):
        self.window.rename_conversation(conv.session_id, cwd=conv.cwd, path=conv.path, current=conv.title)

    def choose_folder(self, conv, target=None):
        """Reprise d'une conversation dont le dossier a disparu, depuis un dossier choisi."""
        problem = self.problem(conv, elsewhere=True)
        if problem:
            self.window.toast(cap(problem))
            return
        dialog = Gtk.FileDialog(title=f"Où se trouve maintenant « {conv.project} » ?",
                                accept_label="Reprendre ici", modal=True)
        start = self.suggestions.get(conv.session_id) or existing_parent(conv.cwd)
        if start:
            dialog.set_initial_folder(Gio.File.new_for_path(start))

        def done(d, result):
            try:
                chosen = d.select_folder_finish(result)
            except GLib.Error:
                return  # annulé
            if chosen is not None and chosen.get_path():
                self.resume(conv, target or conversations.preferred_target(conv), chosen.get_path())
        dialog.select_folder(self.window, None, done)
