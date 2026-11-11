"""« Conversations » (onglet Sessions, sous les sessions ouvertes) : l'historique Claude
Code du projet choisi (ou de tous), groupé par date, et sa reprise.

Pour des milliers de conversations, seules les PAGE_SIZE premières lignes sont
construites (« Afficher 60 de plus » ajoute les suivantes) ; le coût de chaque ligne
affichée est calculé ensuite hors de l'interface. Les menus « ⋮ » passent par les
actions « conv.* » de la page (paramètre : identifiant de la conversation)."""

import time
from dataclasses import replace

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .. import conversations, costs, sessions, terminal
from .. import session_hub as hub
from .common import cap, caption, clear, error_text, existing_parent, in_thread, short_path
from .project_account_dialog import confirm_switch

PAGE_SIZE = 60
RERENDER_S = 60                        # les « il y a … » vieillissent : re-rendu au moins chaque minute
RELOAD_AFTER_RESUME_MS = (2000, 8000)  # le temps que la session reprise apparaisse
TARGETS = {  # icône, libellé du bouton, infobulle, message après reprise
    "vscode": ("text-editor-symbolic", "VS Code", "Reprendre dans VS Code", "Conversation rouverte dans VS Code"),
    # « terminal » : terminal intégré à l'application s'il est disponible, sinon externe.
    "terminal": ("utilities-terminal-symbolic", "Terminal", "Reprendre dans l'application", None),
    "external": ("utilities-terminal-symbolic", "Terminal externe", "Reprendre dans un terminal externe",
                 "Conversation rouverte dans un nouveau terminal"),
}


def tooltip(c):
    lines = [f"Première demande : {c.first_prompt}"]
    if c.last_prompt and c.last_prompt != c.first_prompt:
        lines.append(f"Dernière demande : {c.last_prompt}")
    lines += [f"Dossier : {c.cwd or '?'}", f"Identifiant : {c.session_id}"]
    if c.archived:
        lines.append("Archivée : l'original a été effacé par Claude Code, CCS en garde une copie")
    return "\n".join(lines)


class ConversationList(Gtk.Box):
    """`page` fournit `window`, `opened` (conversations ouvertes dans une session),
    `suggestions` (dossier probable d'un projet déplacé), `by_id` et `load()`."""

    def __init__(self, page):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.page = page
        self.window = page.window
        self.limit = PAGE_SIZE
        self.menus = []
        self.signature = None
        self.rendered_at = 0.0
        self.shown = []
        # Coût de chaque ligne affichée, calculé après le rendu, un journal après l'autre.
        self.cost_loader = costs.Loader(compute=conversations.cost_for_path)  # lit aussi l'archive
        self.known_costs = {}      # identifiant -> ((taille, date), Cost)
        self.cost_rows = {}        # identifiant -> (ligne, libellé, texte, infobulle) des lignes affichées

        head = Gtk.Box(spacing=8, margin_top=6)
        self.title = Gtk.Label(label="Conversations", xalign=0, hexpand=True, css_classes=["title-4"])
        head.append(self.title)
        self.count = Gtk.Label(css_classes=["caption", "dim-label"], valign=Gtk.Align.BASELINE_CENTER)
        head.append(self.count)
        self.append(head)
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self.results)

    # ---- état ----------------------------------------------------------------------

    def busy(self):
        """Menu ouvert ou focus dans la liste : pas de re-rendu périodique."""
        if any(m.get_active() for m in self.menus):
            return True
        focus = self.window.get_focus() if hasattr(self.window, "get_focus") else None
        return focus is not None and focus.is_ancestor(self.results)

    def stale(self):
        return time.time() - self.rendered_at >= RERENDER_S

    def reset(self):
        """Autre projet, autre recherche : on repart des premières lignes."""
        self.limit = PAGE_SIZE

    def show_waiting(self):
        self.signature = None
        clear(self.results)
        self.count.set_label("")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, margin_top=36)
        box.append(Gtk.Spinner(spinning=True, width_request=32, height_request=32))
        box.append(Gtk.Label(label="Lecture de l'historique…", css_classes=["dim-label"]))
        self.results.append(box)

    def show_error(self, text):
        self.signature = None
        clear(self.results)
        self.results.append(Adw.StatusPage(icon_name="dialog-error-symbolic", title="Lecture impossible",
                                           description=text))

    # ---- rendu ---------------------------------------------------------------------

    def render(self, convs, total, filtering, show_project, compact, empty_all=False, force=False):
        """Lignes des conversations `convs` (déjà filtrées), groupées par date. `total` :
        conversations sans filtre ; `empty_all` : aucune session ni conversation sur le PC."""
        opened, suggestions = self.page.opened, self.page.suggestions
        shown = convs[:self.limit]
        signature = (tuple((c.session_id, c.cwd, c.title, c.prompts, c.updated_at, c.folder_exists, c.origin, c.archived)
                           for c in shown),
                     len(convs), total, filtering, show_project, compact, empty_all,
                     frozenset(c.session_id for c in shown if c.session_id in opened),
                     tuple(sorted((c.session_id, suggestions[c.session_id]) for c in shown
                                  if c.session_id in suggestions)))
        if not force and signature == self.signature and not self.stale():
            return
        self.signature = signature
        self.rendered_at = time.time()
        self.menus = []
        self.cost_rows = {}
        self.shown = shown
        self.cost_loader.cancel()
        clear(self.results)
        self.count.set_label(hub.count_text(len(convs), total) if total else "")
        if not convs:
            if empty_all:
                page = Adw.StatusPage(icon_name="utilities-terminal-symbolic", title="Aucune conversation",
                                      description="Les sessions et les conversations Claude Code de ce PC "
                                                  "apparaîtront ici.")
            elif filtering:
                page = Adw.StatusPage(icon_name="edit-find-symbolic", title="Aucun résultat",
                                      description="Essaie d'autres mots ou retire le filtre d'origine.")
            else:
                page = Adw.StatusPage(icon_name="chat-message-new-symbolic", title="Aucune conversation",
                                      description="Pas encore de conversation enregistrée dans ce projet.")
            page.add_css_class("compact")
            self.results.append(page)
            return
        code = conversations.vscode_bin()
        for label, group in conversations.group_by_day(shown):
            self.results.append(Gtk.Label(label=label, xalign=0, css_classes=["heading"], margin_top=6))
            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=False,
                                  css_classes=["boxed-list"])
            for c in group:
                listbox.append(self.row(c, code, show_project, compact))
            # Entrée ou double-clic : reprise là où la conversation est née.
            listbox.connect("row-activated", lambda _lb, row, g=group: self.activate(g[row.get_index()]))
            self.results.append(listbox)
        rest = len(convs) - self.limit
        if rest > 0:
            more = Gtk.Button(label=f"Afficher {min(PAGE_SIZE, rest)} de plus", css_classes=["pill"],
                              halign=Gtk.Align.CENTER, margin_top=6)
            more.connect("clicked", self.on_more)
            self.results.append(more)
        self.load_costs(shown)

    def on_more(self, *_):
        self.limit += PAGE_SIZE
        self.page.render_conversations(force=True)

    # ---- coûts -----------------------------------------------------------------------

    @staticmethod
    def stamp(c):
        return c.size, c.updated_at

    def show_cost(self, session_id, cost):
        shown = self.cost_rows.get(session_id)
        if shown is None:
            return
        row, label, text, tip = shown
        short = costs.format_short(cost)
        if short:
            label.set_label(f"{text} · {short}")
            row.set_tooltip_text(f"{tip}\nCoût (équivalent API) : {costs.format_cost(cost)}")

    def load_costs(self, shown):
        """Coûts des lignes affichées : ceux déjà connus tout de suite, les autres calculés
        hors de l'interface (les plus récentes d'abord), sans bloquer ni le défilement ni
        l'affichage."""
        todo = []
        for c in shown:
            known = self.known_costs.get(c.session_id)
            if known is not None:
                self.show_cost(c.session_id, known[1])
            if known is None or known[0] != self.stamp(c):
                todo.append((c.session_id, c.path))
        stamps = {c.session_id: self.stamp(c) for c in shown}

        def done(session_id, cost):
            self.known_costs[session_id] = (stamps[session_id], cost)
            self.show_cost(session_id, cost)
        self.cost_loader.request(todo, done)

    # ---- ligne -----------------------------------------------------------------------

    def row(self, c, code, show_project, compact):
        opened, suggestions = self.page.opened, self.page.suggestions
        row = Gtk.ListBoxRow(activatable=True, tooltip_text=tooltip(c))
        box = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=12, margin_end=8)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        top = Gtk.Box(spacing=8)
        top.append(Gtk.Label(label=c.title, xalign=0, ellipsize=Pango.EllipsizeMode.END))
        if c.session_id in opened:
            top.append(Gtk.Label(label="ouverte", valign=Gtk.Align.CENTER, css_classes=["badge", "active"]))
        if c.archived:
            top.append(Gtk.Label(label="archivée", valign=Gtk.Align.CENTER, css_classes=["badge"],
                                 tooltip_text="Original effacé : copie gardée par CCS, remise en place à la reprise"))
        info.append(top)
        meta = ([c.project] if show_project else []) + [c.origin_label]
        meta += ([c.git_branch] if c.git_branch else [])
        meta += [hub.plural(c.prompts, "demande"), conversations.ago(c.updated_at)]
        meta_label = caption(" · ".join(meta))
        info.append(meta_label)
        self.cost_rows[c.session_id] = (row, meta_label, " · ".join(meta), row.get_tooltip_text())
        suggestion = suggestions.get(c.session_id) if not c.folder_exists else None
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
            b = self.button("go-next-symbolic", "Afficher", "Ouverte dans l'application : aller à son onglet",
                            compact)
            b.connect("clicked", lambda *_: self.window.terminals.present(tab))
            buttons.append(b)
        for target in () if tab is not None else ("vscode", "terminal") if code else ("terminal",):
            icon, short, label, _toast = TARGETS[target]
            if target == "terminal" and not embedded:
                label = f"Reprendre dans un terminal externe (terminal intégré : {terminal.VTE_PACKAGE})"
            b = self.button(icon, short, cap(problem) if problem else label + where, compact)
            b.set_sensitive(problem is None)
            b.connect("clicked", lambda *_, t=target: self.resume(c, t))
            buttons.append(b)
        entries = [("Aperçu…", "conv.preview"), ("Copier la commande", "conv.copy")]
        if embedded and tab is None and problem is None:
            entries.append(("Reprendre dans un terminal externe", "conv.external"))
        entries.append(("Ouvrir le dossier", "conv.folder") if c.folder_exists
                       else ("Reprendre depuis un autre dossier…", "conv.relocate"))
        entries.append(("Renommer…", "conv.rename"))
        more = Gtk.MenuButton(icon_name="view-more-symbolic", css_classes=["flat"], tooltip_text="Autres actions")
        # Menu construit au premier clic : des dizaines de lignes s'affichent plus vite.
        more.set_create_popup_func(lambda b, e=entries, sid=c.session_id: self.make_menu(b, e, sid))
        self.menus.append(more)
        buttons.append(more)
        box.append(buttons)
        row.set_child(box)
        return row

    @staticmethod
    def make_menu(button, entries, session_id):
        if button.get_menu_model() is not None:
            return
        menu = Gio.Menu()
        for label, action in entries:
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(action, GLib.Variant.new_string(session_id))
            menu.append_item(item)
        button.set_menu_model(menu)

    @staticmethod
    def button(icon, label, tip, compact):
        """Bouton d'une ligne : icône et libellé, icône seule en fenêtre étroite."""
        child = None if compact else Adw.ButtonContent(icon_name=icon, label=label)
        b = Gtk.Button(css_classes=["flat"], tooltip_text=tip)
        if child is None:
            b.set_icon_name(icon)
        else:
            b.set_child(child)
        return b

    # ---- actions -------------------------------------------------------------

    def problem(self, conv, elsewhere=False):
        """Raison d'empêcher la reprise ; un dossier disparu ne bloque pas quand on sait
        d'où reprendre (dossier proposé, ou choisi si `elsewhere`)."""
        if not conv.folder_exists and (elsewhere or self.page.suggestions.get(conv.session_id)):
            conv = replace(conv, folder_exists=True)
        return conversations.resume_problem(conv, self.page.opened)

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
        suggestion = self.page.suggestions.get(conv.session_id)
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
        """Reprise ; si le projet utilise un autre compte que l'actif, la bascule est
        d'abord proposée (VS Code utilise aussi le compte actif)."""
        def go():
            if not conv.archived:
                self.launch_now(conv, target)
                return
            # Conversation archivée : remise en place (hors de l'interface) avant la reprise.
            def work():
                try:
                    return conversations.ensure_conversation(conv)
                except (OSError, ValueError) as e:
                    return e
            in_thread(work, lambda r: self.window.toast(error_text(r)) if isinstance(r, Exception)
                      else self.launch_now(r, target))
        confirm_switch(self.window, conv.cwd, go)

    def launch_now(self, conv, target):
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
            GLib.timeout_add(delay, lambda: (self.page.load(), False)[1])

    def copy_command(self, conv):
        Gdk.Display.get_default().get_clipboard().set(conversations.resume_command(conv))
        self.window.toast("Commande copiée")

    def open_folder(self, conv):
        sessions.open_folder(conv.cwd)

    def rename(self, conv):
        if conv.archived:   # le titre s'écrit dans le journal : on le remet d'abord en place
            def work():
                try:
                    return conversations.ensure_conversation(conv)
                except (OSError, ValueError) as e:
                    return e
            in_thread(work, lambda r: self.window.toast(error_text(r)) if isinstance(r, Exception)
                      else self.rename(r))
            return
        self.window.rename_conversation(conv.session_id, cwd=conv.cwd, path=conv.path, current=conv.title)

    def choose_folder(self, conv, target=None):
        """Reprise d'une conversation dont le dossier a disparu, depuis un dossier choisi."""
        problem = self.problem(conv, elsewhere=True)
        if problem:
            self.window.toast(cap(problem))
            return
        dialog = Gtk.FileDialog(title=f"Où se trouve maintenant « {conv.project} » ?",
                                accept_label="Reprendre ici", modal=True)
        start = self.page.suggestions.get(conv.session_id) or existing_parent(conv.cwd)
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
