"""Autoriser ou refuser depuis le téléphone : réponses signées, à usage unique.

Une demande d'autorisation du chat part en notification ntfy avec deux boutons (« Autoriser »,
« Refuser »). Chaque bouton publie `"<allow|deny> <id de la demande> <jeton>"` sur un sujet de
réponse secret (`phone.reply_topic`). Le jeton est tiré au hasard pour cette seule demande :
il sert une fois, expire après `TOKEN_TTL` secondes et disparaît dès que la demande est réglée
sur le PC. Tout le reste (jeton inconnu, déjà servi, expiré) est ignoré et journalisé sans le
jeton. Le contenu de la commande ne passe dans la notification que si l'utilisateur l'a voulu.

Même modèle pour le mot de passe root (phase 34) : chaque commande lancée avec le mot de passe
gardé part avec un bouton « Révoquer » (`"revoke <id> <jeton>"`, jeton à usage unique valable tant
que le mot de passe est gardé). Les notifications root ne contiennent jamais le mot de passe.
"""

import hmac
import json
import logging
import secrets
import threading
import time
import urllib.request

from . import phone

log = logging.getLogger("ccs.phone")

TOKEN_TTL = 600           # secondes de validité d'un jeton
RETRY_S = 5               # attente avant de se reconnecter à l'écoute
LISTEN_TIMEOUT_S = 90     # ntfy envoie un « keepalive » toutes les 30 s
HIDDEN_BODY = "Réponds depuis la notification ou sur le PC"
DECISIONS = ("allow", "deny", "revoke")   # mots connus ; chaque écouteur ne prend que les siens

# Nom d'outil de Claude Code → type affiché dans la notification
KINDS = {"Bash": "Commande", "Edit": "Modification de fichier", "MultiEdit": "Modification de fichier",
         "Write": "Modification de fichier", "NotebookEdit": "Modification de fichier",
         "Read": "Lecture", "Grep": "Lecture", "Glob": "Lecture", "LS": "Lecture"}
LABELS = ("Commande", "Modification de fichier", "Lecture", "Autre action")


def reply_topic(settings):
    """Sujet secret des réponses (réglage `phone.reply_topic`) ; s'il n'y en a pas, en tire un,
    l'enregistre dans les réglages et le renvoie."""
    phone_cfg = settings.get("phone") if isinstance(settings, dict) else None
    topic = phone_cfg.get("reply_topic") if isinstance(phone_cfg, dict) else None
    if isinstance(topic, str) and phone.valid_topic(topic):
        return topic
    from . import settings as settings_mod
    topic = phone.new_topic()
    settings.setdefault("phone", {})["reply_topic"] = topic
    settings_mod.save_settings(settings)
    return topic


class Replies:
    """Jetons des demandes en attente. Sûr entre fils."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tokens = {}          # id de demande → (jeton, instant d'expiration)

    def issue(self, request_id, now=None, ttl=TOKEN_TTL):
        token = secrets.token_urlsafe(24)
        now = time.time() if now is None else now
        with self._lock:
            self._tokens[request_id] = (token, now + ttl)
        return token

    def settle(self, request_id):
        """La demande est réglée (sur le PC) : son jeton ne sert plus."""
        with self._lock:
            self._tokens.pop(request_id, None)

    def settle_all(self):
        with self._lock:
            self._tokens.clear()

    def pending(self):
        with self._lock:
            return bool(self._tokens)

    def verify(self, body, now=None, decisions=("allow", "deny")):
        """`(id, décision)` pour une réponse valide — une seule fois — sinon None. Une décision
        connue mais pas dans `decisions` (celle d'un autre écouteur du même sujet) est ignorée
        sans bruit."""
        now = time.time() if now is None else now
        parts = str(body or "").split()
        if len(parts) == 3 and parts[0] in DECISIONS and parts[0] not in decisions:
            return None
        if len(parts) != 3 or parts[0] not in decisions:
            log.warning("téléphone : réponse ignorée (format inattendu)")
            return None
        decision, request_id, token = parts
        with self._lock:
            entry = self._tokens.get(request_id)
            if entry is None:
                log.warning("téléphone : réponse ignorée (demande inconnue ou déjà réglée)")
                return None
            expected, expires = entry
            if now > expires:
                del self._tokens[request_id]
                log.warning("téléphone : réponse ignorée (jeton expiré)")
                return None
            if not hmac.compare_digest(expected.encode(), token.encode()):
                log.warning("téléphone : réponse ignorée (jeton incorrect)")
                return None
            del self._tokens[request_id]
        return request_id, decision


def actions_header(cfg, topic, request_id, token):
    """En-tête `Actions` de ntfy : deux boutons qui publient la réponse sur le sujet secret."""
    url = f"{phone.base_url(cfg.get('server'))}/{topic}"
    return "; ".join(
        f"http, {label}, {url}, method=POST, body={decision} {request_id} {token}, clear=true"
        for label, decision in (("Autoriser", "allow"), ("Refuser", "deny")))


def revoke_header(cfg, topic, request_id, token):
    """En-tête `Actions` de ntfy : bouton « Révoquer » (efface le mot de passe root gardé).
    Encodé RFC 2047 (accent), comme les titres."""
    url = f"{phone.base_url(cfg.get('server'))}/{topic}"
    return phone._header(f"http, Révoquer, {url}, method=POST, body=revoke {request_id} {token}, "
                         "clear=true")


def root_ask_message(machine, command, show_content):
    """Demande du mot de passe root, SANS secret : la machine, et la commande seulement si
    l'utilisateur a voulu voir le contenu (`phone.show_content`)."""
    name = phone._clean(machine) or "Une machine"
    cmd = str(command or "").strip()
    body = f"{name} demande le mot de passe root pour : {cmd}" if show_content and cmd \
        else f"{name} demande le mot de passe root"
    return phone.Message("root", "Mot de passe root", body[:500], 5, ("key",))


def root_used_message(machine, command, show_content):
    """Commande lancée avec le mot de passe root gardé (le bouton « Révoquer » va à part)."""
    name = phone._clean(machine) or "Une machine"
    cmd = str(command or "").strip()
    body = f"{name} a lancé en root : {cmd}" if show_content and cmd \
        else f"{name} a lancé une commande root"
    return phone.Message("root", "Commande root", body[:500], 3, ("warning",))


def permission_message(kind, project, detail, show_content):
    """Message d'une demande d'autorisation. `kind` : nom de l'outil (Bash, Edit…) ou l'un des
    types affichés. Le détail (commande, fichier) n'est montré que si `show_content`."""
    label = KINDS.get(kind, kind if kind in LABELS else "Autre action")
    name = phone._clean(project)
    title = f"{label} dans {name}" if name else label
    body = str(detail or "").strip() if show_content and str(detail or "").strip() else HIDDEN_BODY
    return phone.Message("waiting", title, body[:500], 4, ("hourglass_flowing_sand",))


class Listener:
    """Écoute le sujet de réponses (`<serveur>/<sujet>/json?since=<maintenant>`, flux ntfy) dans
    un fil et appelle `on_body(texte)` pour chaque message. Se reconnecte tant qu'on ne l'arrête
    pas ; ne lève jamais."""

    def __init__(self, cfg, topic, on_body, urlopen=None):
        self.cfg = cfg
        self.topic = topic
        self.on_body = on_body
        self._urlopen = urlopen or urllib.request.urlopen
        self._stop = threading.Event()
        self._thread = None
        self._resp = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ccs-telephone-reponses", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        resp = self._resp
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    def _url(self):
        return f"{phone.base_url(self.cfg.get('server'))}/{self.topic}/json?since={int(time.time())}"

    def _run(self):
        since = self._url()
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(since, headers={"User-Agent": phone.USER_AGENT})
                with self._urlopen(req, timeout=LISTEN_TIMEOUT_S) as resp:
                    self._resp = resp
                    for raw in resp:
                        if self._stop.is_set():
                            break
                        self._line(raw)
            except Exception as e:  # noqa: BLE001 — réseau coupé : on réessaie
                if not self._stop.is_set():
                    log.warning("téléphone : écoute interrompue (%s)", type(e).__name__)
            finally:
                self._resp = None
            since = self._url()
            self._stop.wait(RETRY_S)

    def _line(self, raw):
        try:
            event = json.loads(raw)
        except ValueError:
            return
        if isinstance(event, dict) and event.get("event") == "message" \
                and isinstance(event.get("message"), str):
            try:
                self.on_body(event["message"])
            except Exception:  # noqa: BLE001 — un rappel ne doit pas tuer l'écoute
                log.exception("téléphone : réponse mal traitée")
