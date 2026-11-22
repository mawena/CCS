"""Mot de passe root demandé aux appareils (phase 34) : dialogue du bureau et indicateur.

Le gardien (`root_keeper.py`, `server/bridge_root.py`) diffuse par le pont local `root.ask`,
`root.resolved`, `root.used` et `root.forgotten` ; le bureau répond par `root.answer`, lit
`root.status` au démarrage (et à chaque reconnexion) et efface par `root.forget`. On réutilise la
connexion des chats au pont local (`TerminalsPage.local_bridge`).

Le mot de passe ne passe que par le champ masqué : lu au clic sur « Envoyer », envoyé tel quel
par `root.answer`, le champ est vidé aussitôt. Il n'est ni gardé, ni journalisé, ni mis en toast."""

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .common import in_thread  # noqa: E402

TICK_S = 30           # indicateur « root gardé, N min » rafraîchi toutes les 30 s
RETRY_S = 60          # pont local injoignable : nouvel essai dans une minute
REASONS = {"expired": "le délai d'une heure est passé", "forget": "effacé à ta demande",
           "revoke": "révoqué depuis le téléphone", "stop": "le pont local s'est arrêté"}
ERRORS = {"introuvable": "Cette demande n'existe plus (réglée ou expirée).",
          "conflit": "Un autre appareil vérifie déjà un mot de passe.",
          "invalide": "Réponse refusée par le gardien."}


def minutes(seconds):
    """« 42 min » (au moins 1)."""
    return f"{max(1, round((seconds or 0) / 60))} min"


def error_message(err):
    """Texte d'une erreur de `root.answer` (RpcError, autre exception ou code)."""
    code = getattr(err, "code", None) or (err if isinstance(err, str) else None)
    if code in ERRORS:
        return ERRORS[code]
    return str(getattr(err, "message", None) or err or "Échec de l'envoi.")


def attach_events(conn, fn):
    """Abonne `fn(nom, données)` à tous les événements du pont (`RemoteConnection` ne distribue
    que ceux des chats) : son rappel est chaîné une seule fois, les autres abonnés suivent."""
    listeners = getattr(conn, "event_listeners", None)
    if listeners is None:
        listeners = conn.event_listeners = set()
        base = conn.client.on_event

        def chained(name, data):
            if base is not None:
                base(name, data)
            for f in list(listeners):
                try:
                    f(name, data)
                except Exception:  # noqa: BLE001 — un abonné en erreur n'arrête pas les autres
                    pass
        conn.client.on_event = chained
    listeners.add(fn)


class RootDialog(Adw.Dialog):
    """Demande de mot de passe : machine, commande, champ masqué, « Envoyer » et « Refuser »,
    erreur et essais restants. Se ferme seule à l'expiration de la demande."""

    def __init__(self, guard, data):
        super().__init__(title="Mot de passe root", content_width=440, follows_content_size=True)
        self.guard = guard
        self.request_id = data.get("id")
        self.expires_at = data.get("expires_at")
        self.sending = False
        self._done = False
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12,
                      margin_bottom=18, margin_start=18, margin_end=18)
        self.machine_label = Gtk.Label(wrap=True, xalign=0, css_classes=["heading"])
        box.append(self.machine_label)
        self.command_label = Gtk.Label(wrap=True, xalign=0, selectable=True,
                                       css_classes=["monospace"])
        box.append(self.command_label)
        self.entry = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True,
                                       placeholder_text="Mot de passe de sudo…")
        self.entry.connect("activate", lambda *_: self.send())
        self.entry.connect("changed", lambda *_: self._sync())
        box.append(self.entry)
        self.error_label = Gtk.Label(wrap=True, xalign=0, visible=False, css_classes=["error"])
        box.append(self.error_label)
        self.tries_label = Gtk.Label(xalign=0, css_classes=["dim-label", "caption"])
        box.append(self.tries_label)
        buttons = Gtk.Box(spacing=12, homogeneous=True, margin_top=6)
        self.deny_button = Gtk.Button(label="Refuser", css_classes=["pill", "destructive-action"])
        self.deny_button.connect("clicked", lambda *_: self.deny())
        self.send_button = Gtk.Button(label="Envoyer", css_classes=["pill", "suggested-action"])
        self.send_button.connect("clicked", lambda *_: self.send())
        buttons.append(self.deny_button)
        buttons.append(self.send_button)
        box.append(buttons)
        view = Adw.ToolbarView(content=box)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        self.set_default_widget(self.send_button)
        self.set_focus(self.entry)
        self.update(data)
        self._timer = GLib.timeout_add_seconds(1, self._check_expiry)
        self.connect("closed", self._on_closed)

    def update(self, data):
        """Même demande, nouvel état (après un mauvais mot de passe : `error`, essais restants)."""
        self.expires_at = data.get("expires_at", self.expires_at)
        self.machine_label.set_label(f"Commande root sur {data.get('machine') or 'cette machine'}")
        self.command_label.set_label(data.get("command") or "(commande inconnue)")
        tries = data.get("tries_left")
        self.tries_label.set_label(
            "" if tries is None else f"{tries} essai{'s' if tries != 1 else ''} restant{'s' if tries != 1 else ''}"
            " · gardé 1 h en mémoire, jamais écrit sur disque")
        if data.get("error"):
            self.show_error(data["error"])
        self.sending = False
        self._sync()

    def show_error(self, text):
        self.error_label.set_label(text)
        self.error_label.set_visible(bool(text))
        self.sending = False
        self._sync()
        self.entry.grab_focus()

    def _sync(self):
        self.send_button.set_sensitive(not self.sending and bool(self.entry.get_text()))
        self.deny_button.set_sensitive(not self.sending)
        self.entry.set_sensitive(not self.sending)
        if self.sending:
            self.send_button.set_label("Vérification…")
        else:
            self.send_button.set_label("Envoyer")

    def send(self):
        if self.sending or not self.entry.get_text():
            return
        password = self.entry.get_text()
        self.entry.set_text("")             # effacé du champ tout de suite
        self.sending = True
        self.error_label.set_visible(False)
        self._sync()
        self.guard.answer(self.request_id, password)
        password = None  # noqa: F841 — aucune référence gardée ici

    def deny(self):
        self.guard.cancel(self.request_id)
        self.finish()

    def finish(self):
        """Ferme le dialogue ; l'état est réglé tout de suite (le signal « closed » vient
        après l'animation)."""
        self._on_closed()
        self.close()

    def _check_expiry(self):
        if self._done or self.guard._closed:   # fermé, ou fenêtre détruite : on n'y touche plus
            self._timer = None
            return False
        if self.expires_at and time.time() >= self.expires_at:
            self._timer = None
            self.finish()
            return False
        return True

    def _on_closed(self, *_):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None
        self.entry.set_text("")
        if not self._done:
            self._done = True
            self.guard.dialog_closed(self)


class RootGuard:
    """Branché sur la fenêtre : dialogue à chaque `root.ask`, indicateur « root gardé, N min »
    dans l'en-tête (menu : « Oublier »), avis à chaque `root.used` et `root.forgotten`."""

    def __init__(self, window, bridge=None):
        self.window = window
        self.bridge = bridge          # fonction qui rend la connexion au pont local (ou None)
        self.conn = None
        self.dialog = None
        self.pending = None           # dernière demande en cours (pour rouvrir le dialogue)
        self.machine = None
        self.kept_until = None
        self._tick = None
        self._retry = None            # nouvel essai de connexion au pont (minuterie GLib)
        self._closed = False          # fenêtre détruite : plus rien ne doit toucher aux widgets
        window.connect("destroy", lambda *_: self.close())
        self.label = Gtk.Label()
        self.info = Gtk.Label(wrap=True, xalign=0, max_width_chars=36)
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=8,
                          margin_bottom=8, margin_start=8, margin_end=8)
        pop_box.append(self.info)
        self.reply_button = Gtk.Button(label="Répondre", css_classes=["suggested-action"], visible=False)
        self.reply_button.connect("clicked", lambda *_: (self.popover.popdown(), self.reopen()))
        pop_box.append(self.reply_button)
        self.forget_button = Gtk.Button(label="Oublier", css_classes=["destructive-action"])
        self.forget_button.connect("clicked", lambda *_: (self.popover.popdown(), self.forget()))
        pop_box.append(self.forget_button)
        self.popover = Gtk.Popover(child=pop_box)
        self.button = Gtk.MenuButton(css_classes=["flat"], valign=Gtk.Align.CENTER, visible=False,
                                     popover=self.popover, child=self.label,
                                     tooltip_text="Mot de passe root gardé en mémoire")

    # ---- connexion ---------------------------------------------------------------------

    def start(self):
        """Joint le pont local hors du fil de l'interface (il peut le lancer)."""
        if self.bridge is None or self._closed:
            return
        in_thread(self._connect, self.attach)

    def _connect(self):
        try:
            return self.bridge()
        except Exception:  # noqa: BLE001 — pont injoignable : nouvel essai plus tard
            return None

    def attach(self, conn):
        if self._closed:
            return
        if conn is None:
            def retry():
                self._retry = None
                self.start()
                return False
            self._retry = GLib.timeout_add_seconds(RETRY_S, retry)
            return
        self.conn = conn
        attach_events(conn, self.on_event)
        conn.listeners.add(self.on_state)
        self.refresh()

    def on_state(self, state):
        if state == "reconnected":
            self.refresh()

    def refresh(self):
        if self.conn is not None:
            self.conn.call("root.status", callback=self._status)

    def _status(self, result, error):
        if self._closed or error is not None or not isinstance(result, dict):
            return
        self.machine = result.get("machine") or self.machine
        if result.get("kept"):
            self.kept_until = time.time() + (result.get("remaining") or 0)
        else:
            self.kept_until = None
        pending = result.get("pending")
        self.pending = pending if isinstance(pending, dict) else None
        if self.pending is not None and self.dialog is None:
            self.ask(self.pending)
        self.update_indicator()

    # ---- événements --------------------------------------------------------------------

    def on_event(self, name, data):
        if self._closed:
            return
        data = data if isinstance(data, dict) else {}
        if name == "root.ask":
            self.ask(data)
        elif name == "root.resolved":
            if self.pending is not None and self.pending.get("id") == data.get("id"):
                self.pending = None
            if self.dialog is not None and self.dialog.request_id == data.get("id"):
                self.dialog.finish()
            if data.get("ok"):
                self.refresh()
            self.update_indicator()
        elif name == "root.used":
            self.toast(f"Commande root lancée sur {data.get('machine') or 'cette machine'} : "
                       f"{data.get('command') or '?'}")
            self.refresh()
        elif name == "root.forgotten":
            self.kept_until = None
            self.update_indicator()
            reason = REASONS.get(data.get("reason"), "")
            self.toast("Mot de passe root oublié" + (f" : {reason}" if reason else ""))

    def ask(self, data):
        self.machine = data.get("machine") or self.machine
        self.pending = data
        if self.dialog is not None and self.dialog.request_id == data.get("id"):
            self.dialog.update(data)
        else:
            if self.dialog is not None:
                self.dialog.finish()
            self.dialog = RootDialog(self, data)
            self.dialog.present(self.window)
        self.update_indicator()

    def reopen(self):
        if self.pending is not None and self.dialog is None:
            self.ask(self.pending)

    def dialog_closed(self, dialog):
        if self.dialog is dialog:
            self.dialog = None
        self.update_indicator()

    # ---- réponses ----------------------------------------------------------------------

    def answer(self, request_id, password):
        """Envoie le mot de passe (une seule fois) ; le rappel ne le voit pas."""
        if self.conn is None:
            self._answered(request_id, None, "Pont local injoignable.")
            return
        self.conn.call("root.answer", callback=lambda r, e: self._answered(request_id, r, e),
                       id=request_id, password=password)

    def cancel(self, request_id):
        if self.conn is not None:
            self.conn.call("root.answer", callback=lambda *_: None, id=request_id, cancel=True)

    def _answered(self, request_id, result, error):
        if self._closed:
            return
        dialog = self.dialog if self.dialog is not None and self.dialog.request_id == request_id else None
        if error is None and isinstance(result, dict) and result.get("ok"):
            if dialog is not None:
                dialog.finish()
            self.toast("Mot de passe root accepté")
            self.refresh()
            return
        text = error_message(error if error is not None else (result or {}).get("error"))
        if dialog is not None:
            dialog.show_error(text)
        else:
            self.toast(text)

    def forget(self):
        if self.conn is None:
            return
        self.conn.call("root.forget", callback=lambda *_: self.refresh())

    # ---- indicateur --------------------------------------------------------------------

    def remaining(self):
        if self.kept_until is None:
            return 0
        return max(0, int(self.kept_until - time.time()))

    def update_indicator(self):
        machine = self.machine or "cette machine"
        left = self.remaining()
        if self.kept_until is not None and left <= 0:
            self.kept_until = None
        kept = self.kept_until is not None
        waiting = self.pending is not None and self.dialog is None
        if kept:
            self.label.set_label(f"root gardé, {minutes(left)}")
            self.label.set_css_classes(["warning"])
            self.info.set_label(f"Mot de passe root de {machine} gardé en mémoire encore "
                                f"{minutes(left)}. Les commandes sudo des chats le reprennent sans "
                                "rien demander.")
        elif waiting:
            self.label.set_label("root demandé")
            self.label.set_css_classes(["accent"])
            self.info.set_label(f"Une commande attend le mot de passe root de {machine} :\n"
                                f"{self.pending.get('command') or '?'}")
        self.reply_button.set_visible(waiting)
        self.forget_button.set_visible(kept)
        self.button.set_visible(kept or waiting)
        if kept and self._tick is None:
            self._tick = GLib.timeout_add_seconds(TICK_S, self._on_tick)
        elif not kept and self._tick is not None:
            GLib.source_remove(self._tick)
            self._tick = None

    def close(self):
        """Ferme le dialogue et arrête les minuteries (fenêtre détruite, tests) : une minuterie
        GLib laissée derrière toucherait des widgets détruits."""
        self._closed = True
        if self._retry is not None:
            GLib.source_remove(self._retry)
            self._retry = None
        if self.dialog is not None:
            self.dialog.finish()
        if self._tick is not None:
            GLib.source_remove(self._tick)
            self._tick = None

    def _on_tick(self):
        self._tick = None
        self.update_indicator()              # relance la minuterie tant que le mot de passe est gardé
        return False

    def toast(self, text):
        toast = getattr(self.window, "toast", None)
        if toast is not None:
            toast(text)
