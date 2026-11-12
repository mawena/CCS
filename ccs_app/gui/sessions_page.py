"""Onglet Sessions : les sessions Claude Code ouvertes et l'historique des conversations,
réunis.

    ┌ [☰] [Rechercher…………………………] [Toutes les origines ▾] [Nouvelle session…] ┐
    │ Tous les projets 12 │ GiGit                         [Nouvelle session ▾] │
    │ ● GiGit          4  │ ~/Work/GiGit · compte du projet  [Compte de ce…]   │
    │   Autre          8  │ Ouvertes maintenant : cartes des sessions          │
    │   …                 │ Conversations : aujourd'hui, hier, 7 derniers jours│
    └─────────────────────┴────────────────────────────────────────────────────┘

À gauche les projets (`ProjectList`) ; à droite le projet choisi, ou tous : en-tête,
« Ouvertes maintenant » (`SessionCards`) puis « Conversations » (`ConversationList`).
La recherche et le filtre d'origine s'appliquent à tout. En fenêtre étroite, la liste
des projets se replie (bouton « Projets ») ; plus étroite encore, les boutons des
lignes passent en icônes. Tri, recherche et filtres : `session_hub` (pur, testé).

Deux lectures, chacune dans un fil :
- sessions ouvertes, consommation, titres, comptes par projet, mémoire (RAM et inactivité,
  `session_memory`) et contexte (`context_alert`) : toutes les 15 s quand
  l'onglet est affiché (sinon les seules fiches de session, pour le badge) ;
- historique (`conversations.scan`, index incrémental) : toutes les 30 s.
"""

import os
import time

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango

from .. import attention, context_alert, conversations, core, project_accounts, session_memory, sessions, \
    terminal
from .. import session_hub as hub
from .common import caption, clear, in_thread, short_path, string_factory
from .conversation_list import ConversationList
from .project_account_dialog import MENU_LABEL, account_action, account_label, confirm_switch, \
    load_associations, paused_now
from ..settings import load_settings
from .project_list import ProjectList
from .session_cards import SessionCards, pair, stamp

REFRESH_S = 15
HISTORY_S = 30
HIGHLIGHT_S = 12      # mise en évidence de la session désignée par une notification
COLLAPSE_SP = 800     # en dessous, la liste des projets se replie
COMPACT_SP = 560      # en dessous, boutons en icônes et boutons des cartes sous le texte
ORIGIN_CHOICES = (("Toutes les origines", None), ("VS Code", "vscode"), ("Terminal", "terminal"))
# Bouton du filtre en mode compact (la liste garde les libellés complets).
ORIGIN_SHORT = {"Toutes les origines": "Toutes"}


class SessionsPage(Adw.BreakpointBin):
    def __init__(self, window):
        super().__init__(width_request=360, height_request=300)
        self.window = window
        self.visible_page = False
        self.selected = hub.ALL       # dossier du projet choisi
        self.compact = False
        self.view = None
        self.filter_state = ("", None)
        self.header_signature = None
        # Sessions ouvertes (None tant que la première lecture n'est pas finie).
        self.found = None
        self.usage, self.titles, self.stamps, self.assocs = {}, {}, {}, []
        self.memory, self.contexts, self.heavy_tokens = {}, {}, None
        self.loading_sessions = False
        self.sessions_again = False
        self.counting = False
        # Historique (None tant que la première lecture n'est pas finie).
        self.convs = None
        self.opened = set()
        self.suggestions = {}         # identifiant -> dossier probable (dossier d'origine disparu)
        self.by_id = {}
        self.loading = False
        self.again = None             # relecture demandée pendant une lecture (valeur de `quiet`)
        # Session désignée par une notification : (pid, identifiant, jusqu'à).
        self.highlighted = None
        self.highlight_new = False    # premier relevé après la demande : choisir son projet

        self.build()
        self.install_actions()
        GLib.timeout_add_seconds(REFRESH_S, self._tick_sessions)
        GLib.timeout_add_seconds(HISTORY_S, self._tick_history)

    # ---- construction ------------------------------------------------------------

    def build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=8, margin_top=12, margin_bottom=8, margin_start=12, margin_end=12)
        self.sidebar_btn = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", valign=Gtk.Align.CENTER,
                                            tooltip_text="Afficher ou masquer la liste des projets")
        bar.append(self.sidebar_btn)
        self.search = Gtk.SearchEntry(placeholder_text="Rechercher (titre, demandes, projet)…", hexpand=True,
                                      valign=Gtk.Align.CENTER)
        self.search.connect("search-changed", self.on_filter)
        self.search.set_key_capture_widget(self)  # taper n'importe où sur la page lance la recherche
        bar.append(self.search)
        self.origin_drop = Gtk.DropDown(model=Gtk.StringList.new([label for label, _ in ORIGIN_CHOICES]),
                                        tooltip_text="Filtrer par origine", valign=Gtk.Align.CENTER,
                                        factory=string_factory(True), list_factory=string_factory(False))
        self.origin_drop.connect("notify::selected", self.on_filter)
        bar.append(self.origin_drop)
        tip = "Nouvelle session : dossier, compte, modèle et permissions au choix"
        self.new_btn = Gtk.Button(label="Nouvelle session…", css_classes=["suggested-action"],
                                  valign=Gtk.Align.CENTER, tooltip_text=tip)
        self.new_icon = Gtk.Button(icon_name="list-add-symbolic", css_classes=["suggested-action"],
                                   valign=Gtk.Align.CENTER, tooltip_text=tip, visible=False)
        for b in (self.new_btn, self.new_icon):
            b.connect("clicked", lambda *_: self.window.new_session())
            bar.append(b)
        root.append(bar)
        self.vte_hint = caption(terminal.VTE_HINT)
        self.vte_hint.set_margin_start(12)
        self.vte_hint.set_margin_end(12)
        self.vte_hint.set_margin_bottom(6)
        self.vte_hint.set_visible(False)
        root.append(self.vte_hint)

        self.split = Adw.OverlaySplitView(vexpand=True, min_sidebar_width=210, max_sidebar_width=300,
                                          sidebar_width_fraction=0.27)
        self.split.bind_property("show-sidebar", self.sidebar_btn, "active",
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.projects = ProjectList(self.select)
        self.split.set_sidebar(self.projects)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=10, margin_bottom=18,
                          margin_start=12, margin_end=12)
        self.header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.append(self.header)
        self.cards = SessionCards(self.window, self.load_sessions)
        content.append(self.cards)
        self.conv_list = ConversationList(self)
        content.append(self.conv_list)
        self.clamp = Adw.Clamp(maximum_size=900, tightening_threshold=600, child=content)
        self.scroller.set_child(self.clamp)
        self.split.set_content(self.scroller)
        root.append(self.split)
        self.set_child(root)

        # Fenêtre étroite : liste des projets repliée (en surimpression, bouton ☰) ; plus
        # étroite : boutons en icônes. Un seul point de rupture s'applique à la fois.
        collapse = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(f"max-width: {COLLAPSE_SP}sp"))
        compact = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(f"max-width: {COMPACT_SP}sp"))
        for bp in (collapse, compact):
            bp.add_setter(self.split, "collapsed", True)
            bp.add_setter(self.split, "show-sidebar", False)
        compact.add_setter(self.new_btn, "visible", False)
        compact.add_setter(self.new_icon, "visible", True)
        # Filtre d'origine : « Toutes » au lieu de « Toutes les orig… » ; même sélection.
        compact.add_setter(self.origin_drop, "factory", string_factory(True, ORIGIN_SHORT))
        compact.connect("apply", lambda *_: self.set_compact(True))
        compact.connect("unapply", lambda *_: self.set_compact(False))
        self.add_breakpoint(collapse)
        self.add_breakpoint(compact)

    def install_actions(self):
        # Menus et boutons : sess.external((dossier, conversation)), sess.shell('dossier')
        # (terminal externe), sess.terminal('dossier'), sess.folder('dossier'),
        # sess.rename((dossier, conversation)), sess.preview((dossier, conversation)),
        # sess.new('dossier') (avec des options), sess.account('dossier') (compte du projet).
        actions = Gio.SimpleActionGroup()
        for name, kind, handler in (
                ("external", "(ss)", lambda v: self.start(v.unpack()[0], v.unpack()[1] or None, external=True)),
                ("shell", "s", lambda v: self.window.open_shell(v.get_string(), external=True)),
                ("terminal", "s", lambda v: self.window.open_shell(v.get_string())),
                ("folder", "s", lambda v: sessions.open_folder(v.get_string())),
                ("rename", "(ss)", lambda v: self.rename(*v.unpack())),
                ("preview", "(ss)", lambda v: self.preview(*v.unpack())),
                ("new", "s", lambda v: self.window.new_session(v.get_string()))):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new(kind))
            a.connect("activate", lambda _a, v, h=handler: h(v))
            actions.add_action(a)
        actions.add_action(account_action(self.window, self.load_sessions))
        self.insert_action_group("sess", actions)

        # Menus « ⋮ » des conversations : conv.preview('<id>'), conv.copy, conv.folder,
        # conv.relocate, conv.rename, conv.external.
        cl = self.conv_list
        conv_actions = Gio.SimpleActionGroup()
        for name, handler in (("preview", self.window.preview), ("copy", cl.copy_command),
                              ("folder", cl.open_folder), ("relocate", cl.choose_folder),
                              ("rename", cl.rename), ("external", lambda c: cl.resume(c, "external"))):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            a.connect("activate", lambda _a, v, h=handler: self.with_conv(v.get_string(), h))
            conv_actions.add_action(a)
        self.insert_action_group("conv", conv_actions)

    # ---- lectures ------------------------------------------------------------------

    def _tick_sessions(self):
        if self.visible_page:
            self.load_sessions()
        else:
            self.count_waiting()  # badge de l'onglet : fiches de session seules, sans journaux
        return True

    def _tick_history(self):
        if self.visible_page:
            self.load_history(quiet=True)
        return True

    def load(self):
        """Relit les sessions ouvertes et l'historique (onglet affiché, renommage…)."""
        self.load_sessions()
        self.load_history()

    def load_sessions(self):
        if self.loading_sessions:
            self.sessions_again = True
            return
        self.loading_sessions = True

        def work():
            try:
                found = sessions.list_sessions()
                usage = {s.pid: sessions.conversation_usage(s) for s in found}
                titles = {s.session_id: sessions.conversation_title(s.cwd, s.session_id) for s in found}
                journals = [sessions.transcript_path(s.cwd, s.session_id) for s in found if s.session_id]
                stamps = {str(p): stamp(p) for p in journals}
                # Lectures de /proc et des journaux : ici, jamais dans le fil principal.
                settings = load_settings()
                memory = session_memory.snapshot(found, settings=settings)
                cfg = context_alert.config(settings)
                contexts = context_alert.contexts_for(found) if cfg["enabled"] else {}
                heavy = cfg["threshold_tokens"] if cfg["enabled"] else None
                return found, usage, titles, stamps, load_associations(), (memory, contexts, heavy)
            except Exception:  # noqa: BLE001 — relevé raté : on garde le précédent
                return None
        in_thread(work, self.sessions_loaded)

    def sessions_loaded(self, result):
        self.loading_sessions = False
        if result is not None:
            self.found, self.usage, titles, self.stamps, self.assocs, extra = result
            self.memory, self.contexts, self.heavy_tokens = extra
            self.titles = {sid: t for sid, t in titles.items() if t}   # titre seul, sans repli
            self.opened = {s.session_id for s in self.found if s.session_id}
            self.set_badge(self.found)
            self.apply_highlight()
            self.update(quiet=True)
        if self.sessions_again:
            self.sessions_again = False
            self.load_sessions()

    def load_history(self, quiet=False):
        """Relit l'historique dans un fil. `quiet` (relecture périodique) : pas de re-rendu
        pendant que l'utilisateur a un menu ouvert ou le focus dans la liste."""
        if self.loading:
            self.again = quiet if self.again is None else (self.again and quiet)
            return
        self.loading = True
        if self.convs is None:
            self.conv_list.show_waiting()

        def work():
            try:
                convs = conversations.scan()
                return convs, conversations.open_ids(), conversations.suggest_folders(convs)
            except Exception as e:  # noqa: BLE001 — affiché plutôt qu'un sablier sans fin
                return e
        in_thread(work, lambda result: self.history_loaded(result, quiet))

    def history_loaded(self, result, quiet):
        self.loading = False
        if isinstance(result, Exception):
            if self.convs is None:   # relecture ratée : on garde la liste déjà affichée
                self.convs = []
                self.conv_list.show_error(str(result))
                self.update(convs=False)
        else:
            self.convs, self.opened, self.suggestions = result
            self.by_id = {c.session_id: c for c in self.convs}
            self.update(cards=False, quiet=quiet)
        if self.again is not None:
            quiet, self.again = self.again, None
            self.load_history(quiet)

    # ---- badge et mise en évidence ------------------------------------------------

    def count_waiting(self):
        if self.counting:
            return
        self.counting = True

        def done(found):
            self.counting = False
            self.set_badge(found)
        in_thread(sessions.list_sessions, done)

    def set_badge(self, found):
        """Nombre de sessions qui attendent une réponse sur l'onglet (point d'attention s'il
        n'est pas affiché)."""
        page = self.window.stack.get_page(self.window.stack.get_child_by_name("sessions"))
        if page is None:
            return
        n = attention.waiting_count(found)
        page.set_badge_number(n)
        page.set_needs_attention(n > 0 and not self.visible_page)

    def highlight(self, pid, session_id):
        """Met en évidence la carte de cette session (clic sur une notification) : son projet
        est choisi au prochain relevé."""
        self.highlighted = (pid, session_id, time.time() + HIGHLIGHT_S)
        self.highlight_new = True
        self.load_sessions()

    def apply_highlight(self):
        """Premier relevé après la demande : choisit le projet de la session (et retire les
        filtres qui la cacheraient), ou prévient qu'elle est fermée et montre son projet."""
        if not self.highlight_new or self.highlighted is None:
            return
        self.highlight_new = False
        pid, sid, _until = self.highlighted
        target = attention.match_session(self.found, pid, sid)
        if target is None:
            self.highlighted = None
            self.window.toast("Cette session n'est plus ouverte")
            ref = f"{pid}:{sid}" if pid and sid else str(pid or sid or "")
            cwd = hub.project_for_ref(ref, [], self.convs or [])
            if cwd is not None:
                self.choose(cwd)
            return
        query, origin = self.filter_state
        if not hub.filter_sessions([target], query, origin, titles=self.titles):
            self.clear_filters()
        self.choose(target.cwd)

    def highlight_target(self):
        if self.highlighted is None or self.found is None:
            return None
        pid, sid, until = self.highlighted
        if time.time() > until:
            self.highlighted = None
            return None
        return attention.match_session(self.found, pid, sid)

    def scroll_to(self, widget):
        ok, rect = widget.compute_bounds(self.clamp)
        if ok:
            self.scroller.get_vadjustment().set_value(max(0.0, rect.get_y() - 12))
        return False

    def default_folder(self):
        """Dossier proposé pour une nouvelle session : projet choisi, sinon le plus récent."""
        if self.selected and os.path.isdir(self.selected):
            return self.selected
        for e in (self.view.entries[1:] if self.view is not None else ()):
            if e.cwd and e.exists:
                return e.cwd
        return str(core.paths().home)

    # ---- choix du projet, filtres ----------------------------------------------------

    def origin(self):
        i = self.origin_drop.get_selected()
        return ORIGIN_CHOICES[i][1] if i < len(ORIGIN_CHOICES) else None

    def on_filter(self, *_):
        state = (self.search.get_text(), self.origin())
        if state == self.filter_state:
            return
        self.filter_state = state
        self.conv_list.reset()
        self.update(force=True)
        self.scroller.get_vadjustment().set_value(0)

    def clear_filters(self):
        self.filter_state = ("", None)
        self.search.set_text("")
        self.origin_drop.set_selected(0)

    def choose(self, cwd):
        """Choisit un projet sans redessiner (le rendu suit)."""
        if cwd != self.selected:
            self.selected = cwd
            self.conv_list.reset()

    def select(self, cwd):
        """Projet choisi dans la liste (hub.ALL : tous)."""
        if self.split.get_collapsed():
            self.split.set_show_sidebar(False)
        if cwd == self.selected:
            return
        self.choose(cwd)
        self.update(force=True)
        self.scroller.get_vadjustment().set_value(0)

    def set_compact(self, compact):
        if compact != self.compact:
            self.compact = compact
            # Appelé pendant l'allocation de la fenêtre : rendu au tour suivant.
            GLib.idle_add(lambda: (self.view is not None and self.update(force=True), False)[1])

    def rerender(self):
        """Re-rendu après un changement des onglets du terminal intégré (boutons « Afficher »)."""
        if self.view is not None:
            self.update(force=True, quiet=True)

    # ---- rendu ---------------------------------------------------------------

    def update(self, cards=True, convs=True, force=False, quiet=False):
        """Recalcule ce qui est affiché et redessine les parties demandées. `quiet` : pas de
        re-rendu d'une partie dont un menu est ouvert."""
        if self.found is None and self.convs is None:
            return
        query, origin = self.filter_state
        self.view = hub.build(self.convs or [], self.found or [], self.selected, query, origin, self.titles,
                              self.suggestions, self.assocs)
        self.selected = self.view.selected.cwd
        self.vte_hint.set_visible(not self.window.terminals.available)
        self.projects.show(self.view.entries, self.selected)
        self.render_header()
        if cards and self.found is not None and not (quiet and self.cards.busy()):
            card = self.cards.render(self.view.sessions, self.usage, self.titles, self.stamps,
                                     self.view.selected.cwd is hub.ALL, self.highlight_target(), self.compact,
                                     memory=self.memory, contexts=self.contexts, on_close=self.close_session,
                                     heavy_tokens=self.heavy_tokens)
            if card is not None:
                GLib.timeout_add(80, self.scroll_to, card)
        if convs and self.convs is not None and not (quiet and self.conv_list.busy()):
            self.render_conversations(force)

    def render_conversations(self, force=False):
        v = self.view
        empty_all = not self.convs and not self.found and not v.filtering
        self.conv_list.render(v.conversations, v.total, v.filtering, v.selected.cwd is hub.ALL, self.compact,
                              empty_all, force)

    def render_header(self):
        e = self.view.selected
        active = core.active_profile_name()
        embedded = self.window.terminals.available
        # « Nouvelle session… » de la barre : action principale tant qu'aucun projet n'est choisi.
        for b in (self.new_btn, self.new_icon):
            (b.add_css_class if e.cwd is hub.ALL else b.remove_css_class)("suggested-action")
        if e.cwd is hub.ALL:
            sub = f"{hub.plural(self.view.projects, 'projet')} · {hub.plural(len(self.convs or []), 'conversation')}"
            signature = ("tous", sub)
            paused = account = None
        else:
            paused = paused_now() if self.assocs else False
            account = project_accounts.card_text(e.cwd, active, paused, self.assocs) if e.cwd else None
            signature = ("projet", e.cwd, e.name, e.exists, e.moved_to, account, active, embedded)
        if signature == self.header_signature:
            return
        self.header_signature = signature
        clear(self.header)
        top = Gtk.Box(spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        titles.append(Gtk.Label(label=e.name, xalign=0, css_classes=["title-2"], ellipsize=Pango.EllipsizeMode.END,
                                tooltip_text=e.cwd or None))
        top.append(titles)
        self.header.append(top)
        if e.cwd is hub.ALL:
            titles.append(caption(sub))
            return
        where = short_path(e.cwd) if e.cwd else "dossier inconnu"
        titles.append(Gtk.Label(label=where, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE,
                                css_classes=["caption", "dim-label"], tooltip_text=e.cwd or None))
        if e.cwd:
            top.append(self.new_session_button(e, embedded))
        if not e.exists:
            text = "Dossier introuvable"
            if e.moved_to:
                text += f" : déplacé vers {short_path(e.moved_to)} ? Reprends une conversation pour l'y copier."
            self.header.append(caption(text, error=True))
        if e.cwd:
            line = Gtk.Box(spacing=8)
            label = account_label(e.cwd, active, self.assocs, paused)
            if label is None:
                label = caption("Aucun compte associé : les sessions utilisent le compte actif"
                                + (f" ({active})." if active else "."))
            label.set_hexpand(True)
            label.set_valign(Gtk.Align.CENTER)
            line.append(label)
            choose = Gtk.Button(label=MENU_LABEL, css_classes=["flat"], valign=Gtk.Align.CENTER,
                                action_name="sess.account", tooltip_text="Compte proposé à l'ouverture d'une "
                                                                         "session de ce projet")
            choose.set_action_target_value(GLib.Variant.new_string(e.cwd))
            line.append(choose)
            self.header.append(line)

    def new_session_button(self, e, embedded):
        menu = Gio.Menu()
        cwd = GLib.Variant.new_string(e.cwd)
        entries = [("Avec des options…", "sess.new", cwd)]
        if embedded:
            entries.append(("Dans un terminal externe", "sess.external", pair(e.cwd)))
        entries += [("Terminal ici", "sess.terminal", cwd), ("Ouvrir le dossier", "sess.folder", cwd)]
        for label, action, target in entries:
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(action, target)
            menu.append_item(item)
        new = Adw.SplitButton(label="Nouvelle session", menu_model=menu, valign=Gtk.Align.CENTER,
                              sensitive=e.exists, css_classes=["suggested-action"],
                              tooltip_text="Nouvelle session dans l'application" if embedded
                              else "Nouvelle session dans un terminal")
        new.connect("clicked", lambda *_: self.start(e.cwd))
        return new

    # ---- actions -------------------------------------------------------------

    def close_session(self, s):
        """« Fermer » d'une session inactive (après la confirmation de la carte) : arrêt propre
        du processus, puis relecture ; la conversation reste reprenable."""
        ok = sessions.terminate(s.pid, s.proc_start)
        self.window.toast("Session fermée" if ok else "Session déjà fermée")
        GLib.timeout_add(800, lambda: (self.load_sessions(), False)[1])

    def with_conv(self, session_id, handler):
        conv = self.by_id.get(session_id)
        if conv is not None:
            handler(conv)

    def start(self, cwd, resume=None, title=None, external=False):
        """Ouvre (ou reprend) une session ; si le projet utilise un autre compte que l'actif,
        la bascule est d'abord proposée."""
        confirm_switch(self.window, cwd, lambda: self.open_now(cwd, resume, title, external))

    def open_now(self, cwd, resume=None, title=None, external=False):
        where = self.window.open_claude(cwd, resume or None, title, external)
        if where == "externe":
            self.window.toast("Conversation reprise dans un nouveau terminal" if resume
                              else "Nouvelle session lancée dans un terminal")
        for delay in (2000, 8000):  # le temps que la session apparaisse
            GLib.timeout_add(delay, lambda: (self.visible_page and self.load_sessions(), False)[1])

    def rename(self, cwd, session_id):
        conv = self.by_id.get(session_id)
        current = (self.titles.get(session_id) or (conv.title if conv else None)
                   or sessions.conversation_title(cwd, session_id) or "")
        self.window.rename_conversation(session_id, cwd=cwd, current=current)

    def preview(self, cwd, session_id):
        path = sessions.transcript_path(cwd, session_id)

        def work():
            try:
                return conversations.from_journal(path, cwd)
            except OSError as e:
                return e

        def done(conv):
            if isinstance(conv, OSError):
                self.window.toast(f"Aperçu impossible : {conv.strerror or conv}")
            else:
                self.window.preview(conv)
        in_thread(work, done)
