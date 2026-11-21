"""Écran de chat de `ccs tui` : messages en texte, actions en une ligne, autorisations au clavier
(1 Autoriser, 2 Toujours, 3 Refuser) comme au bureau, saisie en bas (Entrée envoie)."""

import urwid

from .. import token_use

LABELS = {"Read": "Lecture", "Edit": "Modification", "MultiEdit": "Modification", "Write": "Écriture",
          "Bash": "Commande", "Grep": "Recherche", "Glob": "Fichiers", "WebFetch": "Page web",
          "WebSearch": "Recherche web", "Task": "Sous-agent", "Agent": "Sous-agent", "TodoWrite": "Tâches"}
STATES = {"busy": "Claude travaille…", "starting": "Démarrage…", "permission": "Attend ta réponse",
          "suspended": "En veille"}


def target(name, inp):
    inp = inp if isinstance(inp, dict) else {}
    first = lambda v: v.splitlines()[0] if isinstance(v, str) and v else ""  # noqa: E731
    if name == "Bash":
        return first(inp.get("command"))
    if name in ("Read", "Write", "Edit", "MultiEdit"):
        return inp.get("file_path") or ""
    if name in ("Grep", "Glob"):
        return inp.get("pattern") or ""
    return next((first(v) for v in inp.values() if isinstance(v, str) and v.strip()), "")


NOTICE_STYLES = {"warning": "alerte", "error": "erreur", "info": "discret"}


class ChatScreen(urwid.WidgetWrap):
    def __init__(self, app, chat_id, title):
        self.app = app
        self.chat_id = chat_id
        self.seq = 0
        self.texts = {}
        self.tools = {}
        self.pending = []           # demandes d'autorisation, dans l'ordre
        self.walker = urwid.SimpleFocusListWalker([])
        self.log = urwid.ListBox(self.walker)
        self.status = urwid.Text(("discret", title))
        self.perm = urwid.Text("")
        self.edit = urwid.Edit(("titre", "› "))
        self.pile = urwid.Pile([("pack", self.status), self.log, ("pack", urwid.AttrMap(self.perm, "alerte")),
                                ("pack", urwid.Divider("─")), ("pack", self.edit)], focus_item=4)
        super().__init__(self.pile)

    # ---- fil -----------------------------------------------------------------------------

    def add(self, markup):
        w = urwid.Text(markup)
        self.walker.append(w)
        self.walker.set_focus(len(self.walker) - 1)
        return w

    def receive(self, item):
        seq = item.get("seq") or 0
        if seq and seq <= self.seq:
            return
        self.seq = max(self.seq, seq)
        ev = item.get("event") or {}
        t = ev.get("type")
        if t == "TextDelta":
            w = self.texts.get(ev["msg_id"])
            text = (w.text if w else "") + ev.get("text", "")
            self._text(ev["msg_id"], text)
        elif t == "AssistantText":
            self._text(ev["msg_id"], ev.get("text", ""))
        elif t == "ToolUse":
            self.tools[ev["tool_id"]] = self.add(("discret", f"  • {LABELS.get(ev.get('name'), ev.get('name'))} : "
                                                  f"{target(ev.get('name'), ev.get('input'))}"))
        elif t == "ToolResult":
            w = self.tools.get(ev.get("tool_id"))
            if w is not None:
                mark = " ✗" if ev.get("is_error") else " ✓"
                w.set_text(("erreur" if ev.get("is_error") else "discret", w.text + mark))
        elif t == "PermissionRequest":
            self.pending.append(ev)
            self._perm()
        elif t == "PermissionSettled":
            self.pending = [p for p in self.pending if p.get("request_id") != ev.get("request_id")]
            self._perm()
        elif t == "TurnResult":
            self.pending = []
            self._perm()
            if ev.get("interrupted"):
                self.add(("discret", "Arrêté."))
            elif ev.get("is_limit"):
                self.add(("alerte", "Limite d'usage atteinte : " + (ev.get("text") or "change de compte.")))
            elif not ev.get("ok"):
                self.add(("erreur", ev.get("text") or "Claude n'a pas pu finir sa réponse."))
            else:
                line = token_use.summary(ev.get("usage") if isinstance(ev.get("usage"), dict) else {})
                if line:
                    self.add(("discret", f"  {line}"))
        elif t == "CacheExpired" and ev.get("text"):    # le prochain message relira tout le contexte
            self.add(("alerte", ev["text"] + " Tape /compact pour compacter, ou ouvre une nouvelle session."))
        elif t == "StateChanged":
            self.status.set_text(("alerte" if ev.get("state") == "permission" else "discret",
                                  STATES.get(ev.get("state"), "")))
        elif t == "Notice" and ev.get("text"):          # note du pont (relance après une limite…)
            self.add((NOTICE_STYLES.get(ev.get("kind"), "discret"), ev["text"]))
        elif t == "UserSent" and ev.get("text") and not ev.get("nonce"):   # envoyé par CCS ou un autre appareil
            self.add(("discret", f"» {ev['text']}"))
        elif t in ("LocalCommand",) and ev.get("text"):
            self.add(("discret", ev["text"]))
        elif t == "ProcessExited" and not ev.get("requested") and ev.get("code"):
            self.add(("erreur", f"Claude s'est arrêté (code {ev['code']})."))

    def _text(self, msg_id, text):
        w = self.texts.get(msg_id)
        if w is None:
            self.texts[msg_id] = self.add(text)
        else:
            w.set_text(text)

    def _perm(self):
        if not self.pending:
            self.perm.set_text("")
            return
        p = self.pending[0]
        what = target(p.get("tool_name"), p.get("input")) or p.get("tool_name")
        self.perm.set_text(f"Claude demande : {p.get('display_name') or p.get('tool_name')} — {what}\n"
                           "  1 Autoriser · 2 Toujours · 3 Refuser")

    # ---- actions -------------------------------------------------------------------------

    def send(self):
        text = self.edit.edit_text.strip()
        if not text:
            return
        self.edit.set_edit_text("")
        self.add(("titre", f"Toi : {text}"))
        self.app.client.call("chat.send", callback=self.app.report, chat_id=self.chat_id, text=text,
                             nonce="tui")     # son écho (UserSent) n'est pas affiché deux fois

    def answer(self, decision):
        p = self.pending.pop(0)
        self._perm()
        self.app.client.call("chat.answer", callback=self.app.report, chat_id=self.chat_id,
                             request_id=p["request_id"], decision=decision)

    def interrupt(self):
        self.app.client.call("chat.interrupt", callback=self.app.report, chat_id=self.chat_id)

    def keypress(self, size, key):
        if self.pending and key in ("1", "2", "3"):
            self.answer({"1": "allow", "2": "always", "3": "deny"}[key])
            return None
        if key == "enter":
            self.send()
            return None
        return super().keypress(size, key)
