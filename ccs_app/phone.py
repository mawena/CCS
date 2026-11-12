"""Notifications sur le téléphone (ntfy, optionnel, désactivé par défaut).

Une alerte (`alerts.Alert`) du service est traduite en message **sans contenu** : le nom du
projet et l'état, jamais un titre de conversation, un message, un chemin complet ni un nom
de compte. L'envoi est un POST sur `<serveur>/<canal>` (en-têtes Title, Priority, Tags), dans
un fil, avec un délai court ; un échec est journalisé (`ccs.phone`) et n'est jamais une
exception. « Ne pas déranger » s'applique aussi au téléphone (`quiet.should_hold`, avec la
même exception « attend ta réponse »).

Le canal ntfy est un secret : quiconque le connaît lit les notifications. On le tire donc au
hasard (`new_topic`) ; il n'est jamais écrit dans le journal.

Réglages (`settings["phone"]`, repli sur `DEFAULTS` clé par clé) :
    {"enabled": false, "server": "https://ntfy.sh", "topic": "",
     "events": {"waiting": true, "task": true, "switch": true, "exhausted": true}}
"""

import base64
import logging
import re
import secrets
import threading
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

log = logging.getLogger("ccs.phone")

DEFAULTS = {
    "enabled": False,
    "server": "https://ntfy.sh",
    "topic": "",
    "events": {"waiting": True, "task": True, "switch": True, "exhausted": True},
}
EVENTS = (
    ("waiting", "Session qui attend ta réponse"),
    ("task", "Tâche finie ou échouée"),
    ("switch", "Bascule de compte"),
    ("exhausted", "Tous les comptes épuisés"),
)
TIMEOUT_S = 8
TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
USER_AGENT = "ccs-phone"


@dataclass(frozen=True)
class Message:
    event: str          # waiting | task | switch | exhausted | test
    title: str
    body: str
    priority: int       # 1 à 5 (ntfy)
    tags: tuple = ()    # noms d'emoji ntfy (ASCII)


# --------------------------------------------------------------------------
# Réglages
# --------------------------------------------------------------------------

def config(settings=None):
    """Section « phone » complète : valeurs par défaut pour toute clé absente ou invalide."""
    raw = settings.get("phone") if isinstance(settings, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    server = raw.get("server")
    topic = raw.get("topic")
    cfg = {"enabled": raw.get("enabled") is True,
           "server": server.strip() if isinstance(server, str) and server.strip() else DEFAULTS["server"],
           "topic": topic.strip() if isinstance(topic, str) else ""}
    ev = raw.get("events") if isinstance(raw.get("events"), dict) else {}
    cfg["events"] = {k: ev[k] if isinstance(ev.get(k), bool) else v for k, v in DEFAULTS["events"].items()}
    return cfg


def new_topic():
    """Nouveau canal secret (« ccs- » + 24 caractères au hasard)."""
    return "ccs-" + secrets.token_urlsafe(18)


def valid_server(server):
    p = urlparse(server or "")
    return p.scheme in ("http", "https") and bool(p.netloc) and not p.query and not p.fragment


def valid_topic(topic):
    return bool(TOPIC_RE.match(topic or ""))


def base_url(server):
    return (server or DEFAULTS["server"]).strip().rstrip("/")


def subscribe_url(cfg):
    """Lien d'abonnement (à ouvrir dans l'application ntfy), ou None sans canal valide."""
    if not valid_server(cfg.get("server")) or not valid_topic(cfg.get("topic")):
        return None
    return f"{base_url(cfg['server'])}/{cfg['topic']}"


def ready(settings=None):
    cfg = config(settings)
    return cfg["enabled"] and subscribe_url(cfg) is not None


# --------------------------------------------------------------------------
# Alerte -> message (pur)
# --------------------------------------------------------------------------

_WAITING_SUFFIXES = (" attend toujours ta réponse", " attend ta réponse")
_TASK_FAILED = ("echec", "echoue", "failed", "error", "erreur")


def event_of(alert):
    """Événement du téléphone d'une alerte, ou None (rien à envoyer : fin de session,
    seuils, conseils, bilans, budgets…). D'après la clé, comme `quiet.kind`."""
    prefix = str(alert.key).split(":", 1)[0]
    if prefix in ("attente", "rappel", "fin"):   # fin : un chat a fini de répondre
        return "waiting"
    if prefix in ("tache", "task"):
        return "task"
    if prefix == "switch":
        return "switch"
    if prefix == "exhausted":
        return "exhausted"
    return None


def _clean(name):
    """Nom de projet sûr : une seule ligne courte, jamais un chemin."""
    name = " ".join(str(name or "").split())
    if "/" in name:
        name = name.rstrip("/").rsplit("/", 1)[-1]
    return name[:60]


def _project_from_title(title):
    for suffix in _WAITING_SUFFIXES:
        if str(title).endswith(suffix):
            return _clean(str(title)[:-len(suffix)])
    return ""


def message_for(alert, project=None):
    """Message sans contenu pour `alert`, ou None si cet événement n'existe pas.

    `project` : nom du projet (dossier) quand l'appelant le connaît ; à défaut, il est lu
    dans le titre d'une alerte d'attente (« <projet> attend ta réponse »). Le corps ne
    reprend jamais celui de l'alerte. Une tâche est « échouée » quand sa clé contient
    « echec », « echoue », « failed » ou « error » (ex. `tache:<id>:echec`)."""
    ev = event_of(alert)
    if ev is None:
        return None
    name = _clean(project) or (_project_from_title(alert.title) if ev == "waiting" else "")
    if ev == "waiting" and str(alert.key).startswith("fin"):
        return Message(ev, "Claude a fini de répondre",
                       f"{name} : Claude a fini de répondre." if name else "Une session a fini de répondre.",
                       3, ("white_check_mark",))
    if ev == "waiting":
        again = str(alert.key).startswith("rappel")
        body = ("Une session attend ta réponse." if not name else
                f"{name} attend toujours ta réponse." if again else f"{name} attend ta réponse.")
        return Message(ev, "Une session attend ta réponse", body, 4, ("hourglass_flowing_sand",))
    if ev == "task":
        failed = any(w in str(alert.key).lower() for w in _TASK_FAILED)
        title = "Tâche échouée" if failed else "Tâche finie"
        return Message(ev, title, f"{name} : {title.lower()}." if name else f"{title}.",
                       4 if failed else 3, ("x",) if failed else ("white_check_mark",))
    if ev == "switch":
        return Message(ev, "Bascule de compte", "CCS a basculé sur un autre compte.", 2, ("repeat",))
    return Message(ev, "Comptes épuisés", "Tous les comptes Claude sont presque épuisés.", 5, ("warning",))


def sample_message():
    return Message("test", "CCS", "Test : les notifications arrivent sur ce téléphone.", 3, ("bell",))


# --------------------------------------------------------------------------
# Envoi
# --------------------------------------------------------------------------

def _header(text):
    """Valeur d'en-tête HTTP : ASCII tel quel, sinon encodage RFC 2047 (accepté par ntfy)."""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


def build_request(cfg, msg):
    """Requête POST de `msg`, ou None si le serveur ou le canal est invalide."""
    url = subscribe_url(cfg)
    if url is None:
        return None
    headers = {"Title": _header(msg.title), "Priority": str(msg.priority), "User-Agent": USER_AGENT,
               "Content-Type": "text/plain; charset=utf-8"}
    if msg.tags:
        headers["Tags"] = ",".join(msg.tags)
    return urllib.request.Request(url, data=msg.body.encode("utf-8"), headers=headers, method="POST")


def deliver(cfg, msg, urlopen=None):
    """Envoie `msg` tout de suite (appel bloquant, délai `TIMEOUT_S`). (réussi, raison).
    Ne lève jamais ; le canal n'est jamais écrit dans le journal."""
    try:
        req = build_request(cfg, msg)
        if req is None:
            return False, "serveur ou canal invalide"
        with (urlopen or urllib.request.urlopen)(req, timeout=TIMEOUT_S) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
        if isinstance(code, int) and code >= 400:
            log.warning("téléphone : le serveur a répondu %s", code)
            return False, f"réponse {code}"
        return True, ""
    except Exception as e:  # noqa: BLE001 — réseau, certificat, délai… : échec silencieux
        reason = type(e).__name__
        log.warning("téléphone : envoi impossible (%s)", reason)
        return False, reason


def decide(alert, settings=None, now=None, project=None):
    """(message | None, raison) : ce qu'il faut envoyer pour `alert`, sans rien envoyer.
    Raisons de non-envoi : « désactivé », « canal manquant », « sans objet », « événement
    coupé », « ne pas déranger »."""
    cfg = config(settings)
    if not cfg["enabled"]:
        return None, "désactivé"
    if subscribe_url(cfg) is None:
        return None, "canal manquant"
    msg = message_for(alert, project)
    if msg is None:
        return None, "sans objet"
    if not cfg["events"].get(msg.event, True):
        return None, "événement coupé"
    try:
        from . import quiet
        if quiet.should_hold(alert, now, settings):
            return None, "ne pas déranger"
    except Exception:  # noqa: BLE001 — réglages de silence illisibles : on n'empêche pas l'envoi
        log.exception("téléphone : « ne pas déranger » illisible")
    return msg, ""


def send(alert, settings=None, now=None, project=None, urlopen=None, run=None):
    """Envoie `alert` au téléphone, dans un fil (le service n'attend pas). Renvoie le fil
    lancé, ou None si rien n'est à envoyer. Ne lève jamais. `run(fonction)` : exécuteur
    injectable (tests : appel direct, sans fil)."""
    try:
        msg, _why = decide(alert, settings, now, project)
        if msg is None:
            return None
        cfg = config(settings)

        def work():
            deliver(cfg, msg, urlopen)
        if run is not None:
            run(work)
            return None
        t = threading.Thread(target=work, name="ccs-telephone", daemon=True)
        t.start()
        return t
    except Exception:  # noqa: BLE001 — jamais d'exception vers le service
        log.exception("téléphone : envoi impossible")
        return None


def send_test(settings=None, urlopen=None):
    """Bouton « Essayer » : envoi immédiat, même si l'interrupteur est coupé. (réussi, texte)."""
    cfg = config(settings)
    if subscribe_url(cfg) is None:
        return False, "Indique un serveur (http:// ou https://) et crée un canal."
    ok, why = deliver(cfg, sample_message(), urlopen)
    return (True, "Message envoyé : regarde ton téléphone.") if ok else (False, f"Envoi impossible ({why}).")
