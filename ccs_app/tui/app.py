"""Application `ccs tui` : projets et conversations, chat, feuille de route, comptes.

Tab change d'écran, Échap revient aux projets, Ctrl+C interrompt Claude, q quitte (hors saisie).
Le client (local ou vers un serveur) est celui de `ccs_app.remote.client`."""

import os

import urwid

from .chat import ChatScreen

PALETTE = [
    ("titre", "bold", ""), ("discret", "dark gray", ""), ("alerte", "yellow,bold", ""),
    ("erreur", "light red", ""), ("ok", "light green", ""), ("choix", "standout", ""),
    ("entete", "white,bold", "dark blue"),
]
ORDER = ("projets", "chat", "feuille", "comptes")
NAMES = {"projets": "Projets", "chat": "Chat", "feuille": "Feuille de route", "comptes": "Comptes"}


def _row(label, callback):
    btn = urwid.Button(label, on_press=lambda _b: callback())
    btn._w = urwid.AttrMap(urwid.SelectableIcon(f"  {label}", 0), None, "choix")
    return btn


class _ListScreen(urwid.WidgetWrap):
    def __init__(self, app):
        self.app = app
        self.walker = urwid.SimpleFocusListWalker([urwid.Text(("discret", "Chargement…"))])
        super().__init__(urwid.ListBox(self.walker))

    def fill(self, widgets):
        self.walker[:] = widgets or [urwid.Text(("discret", "(vide)"))]
        first = next((i for i, w in enumerate(self.walker) if w.selectable()), None)
        if first is not None:
            self.walker.set_focus(first)


class ProjectsScreen(_ListScreen):
    def refresh(self):
        self.app.client.call("projects.list", callback=self.app.guard(self._show))

    def _show(self, r):
        items = [urwid.Text(("titre", "Projets")), urwid.Text(("discret", "Entrée : nouveau chat dans le projet"))]
        for p in r.get("entries") or []:
            if p.get("cwd") and p.get("exists", True):
                items.append(_row(f"{p['name']}  ({p.get('total', 0)} conversation(s))",
                                  lambda cwd=p["cwd"], name=p["name"]: self.app.open_chat(cwd, None, name)))
        items += [urwid.Divider(), urwid.Text(("titre", "Conversations récentes"))]
        for c in (r.get("conversations") or [])[:50]:
            if c.get("folder_exists", True):
                title = c.get("title") or c.get("first_prompt") or "(sans titre)"
                items.append(_row(f"{title}  · {os.path.basename(c['cwd'])}",
                                  lambda c=c, title=title: self.app.open_chat(c["cwd"], c["session_id"], title)))
        self.fill(items)


class _TaskRow(urwid.WidgetWrap):
    def __init__(self, screen, path, task):
        self.screen, self.path, self.task = screen, path, task
        mark = "[x]" if task.get("done") else "[ ]"
        indent = "  " * min(int(task.get("depth") or 0), 3)
        super().__init__(urwid.AttrMap(urwid.SelectableIcon(f"{indent}{mark} {task['text']}", len(indent) + 1),
                                       "discret" if task.get("done") else None, "choix"))

    def keypress(self, size, key):
        if key in (" ", "enter"):
            self.screen.toggle(self.path, self.task)
            return None
        return key


class RoadmapScreen(_ListScreen):
    def refresh(self):
        if not self.app.cwd:
            self.fill([urwid.Text(("discret", "Ouvre d'abord un projet (écran Projets)."))])
            return
        self.app.client.call("roadmap.read", callback=self.app.guard(self._show), cwd=self.app.cwd)

    def _show(self, r):
        if not r.get("path"):
            self.fill([urwid.Text(("discret", "Pas de ROADMAP.md dans ce projet."))])
            return
        items = [urwid.Text(("titre", r.get("title") or "Feuille de route")), urwid.Text(("discret", "Espace : cocher"))]
        for phase in reversed(r.get("phases") or []):
            done = sum(1 for t in phase["tasks"] if t.get("done"))
            items += [urwid.Divider(), urwid.Text(("titre", f"{phase['title']}  {done}/{len(phase['tasks'])}"))]
            items += [_TaskRow(self, r["path"], t) for t in phase["tasks"]]
        self.fill(items)

    def toggle(self, path, task):
        self.app.client.call("roadmap.toggle", callback=self.app.guard(lambda _r: self.refresh()),
                             path=path, line=task["line"], text=task["text"])


class AccountsScreen(_ListScreen):
    def refresh(self):
        self.app.client.call("accounts.state", callback=self.app.guard(self._show))

    def _show(self, r):
        items = [urwid.Text(("titre", f"Comptes Claude — actif : {r.get('active') or 'aucun'}"))]
        accounts = (r.get("state") or {}).get("accounts") or r.get("profiles") or []
        for a in accounts:
            items += [urwid.Divider(), urwid.Text(("ok" if a.get("active") else "titre",
                                                   f"● {a['name']}{'  (actif)' if a.get('active') else ''}"))]
            for lim in a.get("limits") or []:
                if lim.get("kind") in ("session", "weekly_all"):
                    pct = round(lim.get("percent") or 0)
                    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                    items.append(urwid.Text(f"  {lim.get('label', lim['kind']):<26} {bar} {pct} %"))
        self.fill(items)


class TuiApp:
    def __init__(self, client, label):
        self.client = client
        self.label = label
        self.chat = None
        self.cwd = None
        self.current = None
        client.on_event = self.on_event
        client.on_state = self.on_state
        self.header = urwid.Text("")
        self.footer = urwid.Text(("discret", "Tab : écran suivant · Échap : projets · Ctrl+C : arrêter Claude · q : quitter"))
        self.screens = {"projets": ProjectsScreen(self), "feuille": RoadmapScreen(self), "comptes": AccountsScreen(self)}
        self.root = urwid.Frame(urwid.SolidFill(" "), header=urwid.AttrMap(self.header, "entete"),
                                footer=self.footer)
        self.show("projets")

    # ---- écrans --------------------------------------------------------------------------

    def show(self, name):
        if name == "chat" and self.chat is None:
            return
        self.current = name
        if name == "chat":
            self.root.body = self.chat
        else:
            self.root.body = self.screens[name]
            self.screens[name].refresh()
        tabs = "  ".join(f"[{NAMES[n]}]" if n == name else NAMES[n] for n in ORDER
                         if n != "chat" or self.chat is not None)
        self.header.set_text(f" CCS · {self.label}   {tabs}")

    def open_chat(self, cwd, session_id=None, title=None):
        self.cwd = cwd

        def opened(r):
            self.chat = ChatScreen(self, r["chat_id"], title or os.path.basename(cwd))
            self.show("chat")
            self.client.call("chat.attach", callback=self.guard(self._attached), chat_id=r["chat_id"], since=0)
        self.client.call("chat.open", callback=self.guard(opened), cwd=cwd, session_id=session_id)

    def _attached(self, r):
        for item in r.get("events") or []:
            self.chat.receive(item)

    # ---- clavier, événements -------------------------------------------------------------

    def handle_key(self, key):
        if key == "tab":
            names = [n for n in ORDER if n != "chat" or self.chat is not None]
            self.show(names[(names.index(self.current) + 1) % len(names)])
        elif key == "esc":
            self.show("projets")
        elif key == "ctrl c":
            if self.chat is not None:
                self.chat.interrupt()
        elif key in ("q", "Q"):
            raise urwid.ExitMainLoop()
        elif key == "f5" and self.current != "chat":
            self.screens[self.current].refresh()

    def on_event(self, name, data):
        if name == "chat.event" and self.chat is not None and data.get("chat_id") == self.chat.chat_id:
            self.chat.receive(data)
        elif name == "notice":
            self.footer.set_text(("alerte", data.get("text", "")))

    def on_state(self, state):
        text = {"offline": "Connexion perdue : reconnexion…", "reconnected": "Reconnecté.",
                "auth": "Jeton refusé : appaire de nouveau ce serveur (ccs serveur ajouter)."}.get(state)
        if text:
            self.footer.set_text(("alerte", text))
        if state == "reconnected" and self.chat is not None:
            self.client.call("chat.attach", callback=self.guard(self._attached), chat_id=self.chat.chat_id,
                             since=self.chat.seq)

    def report(self, _result, error):
        if error is not None:
            self.footer.set_text(("erreur", str(getattr(error, "message", error))))

    def guard(self, fn):
        """Rappel (résultat, erreur) qui affiche l'erreur au lieu de planter."""
        def callback(result, error):
            if error is not None:
                self.report(None, error)
            else:
                fn(result)
        return callback


def run(transport, label):
    """Boucle urwid : les réponses du client (fil asyncio) entrent par un tube surveillé."""
    import queue
    from ..remote.client import SyncBridgeClient
    pending = queue.Queue()
    loop_box = {}

    def wake(_data):
        while not pending.empty():
            fn, args = pending.get_nowait()
            fn(*args)
        return True

    def dispatch(fn, *args):
        pending.put((fn, args))
        os.write(loop_box["fd"], b"x")

    client = SyncBridgeClient(transport, dispatch)
    screen = urwid.raw_display.Screen()
    screen.tty_signal_keys(intr="undefined")
    app = None
    loop = urwid.MainLoop(urwid.SolidFill(" "), PALETTE, screen=screen)
    loop_box["fd"] = loop.watch_pipe(wake)
    client.start()
    app = TuiApp(client, label)
    loop.widget = app.root
    loop.unhandled_input = app.handle_key
    try:
        loop.run()
    finally:
        client.stop()
