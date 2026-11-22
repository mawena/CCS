"""Mot de passe root demandé aux appareils (phase 34), version texte de `ccs tui`.

Même client que le reste de la TUI (le pont, local ou serveur) : événements `root.ask`,
`root.resolved`, `root.used`, `root.forgotten` ; méthodes `root.answer`, `root.status`,
`root.forget`. À `root.ask`, une fenêtre par-dessus l'écran : machine, commande, saisie masquée
(Entrée envoie, Échap refuse), erreur et essais restants. Le mot de passe n'est lu qu'à l'envoi,
le champ est vidé aussitôt ; il n'est ni gardé, ni journalisé, ni affiché."""

import time

import urwid

REASONS = {"expired": "le délai d'une heure est passé", "forget": "effacé à ta demande",
           "revoke": "révoqué depuis le téléphone", "stop": "le pont s'est arrêté"}
ERRORS = {"introuvable": "Cette demande n'existe plus (réglée ou expirée).",
          "conflit": "Un autre appareil vérifie déjà un mot de passe.",
          "invalide": "Réponse refusée par le gardien."}


def minutes(seconds):
    return f"{max(1, round((seconds or 0) / 60))} min"


def error_message(err):
    code = getattr(err, "code", None) or (err if isinstance(err, str) else None)
    if code in ERRORS:
        return ERRORS[code]
    return str(getattr(err, "message", None) or err or "Échec de l'envoi.")


class RootPrompt(urwid.WidgetWrap):
    """Fenêtre de saisie : Entrée envoie, Échap refuse."""

    def __init__(self, guard, data):
        self.guard = guard
        self.request_id = data.get("id")
        self.expires_at = data.get("expires_at")
        self.sending = False
        self.machine = urwid.Text("")
        self.command = urwid.Text("")
        self.edit = urwid.Edit(("titre", "Mot de passe : "), mask="*")
        self.error = urwid.Text("")
        self.tries = urwid.Text("")
        keys = urwid.Text(("discret", "Entrée : envoyer · Échap : refuser"))
        body = urwid.Pile([self.machine, urwid.AttrMap(self.command, "titre"), urwid.Divider(),
                           self.edit, urwid.AttrMap(self.error, "erreur"),
                           urwid.AttrMap(self.tries, "discret"), keys], focus_item=3)
        super().__init__(urwid.LineBox(urwid.Padding(body, left=1, right=1), title="Mot de passe root"))
        self.update(data)

    def update(self, data):
        """Même demande, nouvel état (après un mauvais mot de passe : `error`, essais restants)."""
        self.expires_at = data.get("expires_at", self.expires_at)
        self.machine.set_text(f"Commande root sur {data.get('machine') or 'cette machine'} :")
        self.command.set_text(data.get("command") or "(commande inconnue)")
        tries = data.get("tries_left")
        self.tries.set_text("" if tries is None else f"{tries} essai(s) restant(s) · gardé 1 h en mémoire")
        self.sending = False
        self.error.set_text(data.get("error") or "")

    def show_error(self, text):
        self.sending = False
        self.error.set_text(text)

    def expired(self, now=None):
        return bool(self.expires_at) and (now or time.time()) >= self.expires_at

    def keypress(self, size, key):
        if key == "enter":
            if not self.sending and self.edit.edit_text:
                password = self.edit.edit_text
                self.edit.set_edit_text("")     # vidé tout de suite
                self.sending = True
                self.error.set_text(("discret", "Vérification…"))
                self.guard.answer(self.request_id, password)
                password = None  # noqa: F841 — aucune référence gardée ici
            return None
        if key == "esc":
            self.edit.set_edit_text("")
            self.guard.cancel(self.request_id)
            self.guard.close()
            return None
        super().keypress(size, key)
        return None                             # rien ne passe à l'écran du dessous (q, Tab…)


class RootGuard:
    """État root de la TUI : fenêtre de saisie, texte d'en-tête « root gardé, N min »."""

    def __init__(self, app):
        self.app = app
        self.prompt = None
        self.machine = None
        self.kept_until = None

    def refresh(self):
        self.app.client.call("root.status", callback=self._status)

    def _status(self, result, error):
        if error is not None or not isinstance(result, dict):
            return
        self.machine = result.get("machine") or self.machine
        self.kept_until = time.time() + (result.get("remaining") or 0) if result.get("kept") else None
        pending = result.get("pending")
        if isinstance(pending, dict) and self.prompt is None:
            self.ask(pending)
        self.app.update_header()

    def on_event(self, name, data):
        """Vrai si l'événement était pour le gardien."""
        if not str(name).startswith("root."):
            return False
        data = data if isinstance(data, dict) else {}
        if name == "root.ask":
            self.ask(data)
        elif name == "root.resolved":
            if self.prompt is not None and self.prompt.request_id == data.get("id"):
                self.close()
            if data.get("ok"):
                self.refresh()
        elif name == "root.used":
            self.app.notify("alerte", f"Commande root lancée sur {data.get('machine') or 'cette machine'} : "
                                      f"{data.get('command') or '?'}")
            self.refresh()
        elif name == "root.forgotten":
            self.kept_until = None
            reason = REASONS.get(data.get("reason"), "")
            self.app.notify("discret", "Mot de passe root oublié" + (f" : {reason}" if reason else ""))
            self.app.update_header()
        return True

    def ask(self, data):
        self.machine = data.get("machine") or self.machine
        if self.prompt is not None and self.prompt.request_id == data.get("id"):
            self.prompt.update(data)
        else:
            self.prompt = RootPrompt(self, data)
            self.app.show_overlay(self.prompt)

    def close(self):
        if self.prompt is not None:
            self.prompt.edit.set_edit_text("")
            self.prompt = None
            self.app.show_overlay(None)

    def answer(self, request_id, password):
        self.app.client.call("root.answer", callback=lambda r, e: self._answered(request_id, r, e),
                             id=request_id, password=password)

    def cancel(self, request_id):
        self.app.client.call("root.answer", callback=lambda *_: None, id=request_id, cancel=True)

    def _answered(self, request_id, result, error):
        mine = self.prompt is not None and self.prompt.request_id == request_id
        if error is None and isinstance(result, dict) and result.get("ok"):
            if mine:
                self.close()
            self.app.notify("ok", "Mot de passe root accepté.")
            self.refresh()
            return
        text = error_message(error if error is not None else (result or {}).get("error"))
        if mine:
            self.prompt.show_error(text)
        else:
            self.app.notify("erreur", text)

    def forget(self):
        self.app.client.call("root.forget", callback=lambda *_: self.refresh())

    def tick(self, now=None):
        """Toutes les 30 s environ : demande expirée fermée, minutes de l'en-tête à jour."""
        if self.prompt is not None and self.prompt.expired(now):
            self.close()
        if self.kept_until is not None and (now or time.time()) >= self.kept_until:
            self.kept_until = None
        self.app.update_header()

    def header_text(self, now=None):
        if self.kept_until is None:
            return ""
        return f"   root gardé, {minutes(self.kept_until - (now or time.time()))} (F8 : oublier)"
