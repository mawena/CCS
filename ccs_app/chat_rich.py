"""Chat riche, partie commune (sans GTK) : lecture des blocs ```ccs et reconnaissance des sons
et vidéos. Même règles que la version web (ccs_app/web/chat-rich.js) ; format : docs/chat-riche.md."""

import json
import re

AUDIO = ("mp3", "ogg", "wav", "m4a", "opus")
VIDEO = ("mp4", "webm", "mov")
TYPES = ("choix", "formulaire", "carte", "cartes")
_EXT = re.compile(r"\.([a-z0-9]+)$", re.I)


def media_kind(src):
    """« audio », « video » ou None d'après l'extension (avant ?requête et #ancre)."""
    m = _EXT.search(re.split(r"[?#]", str(src or ""), maxsplit=1)[0])
    ext = m.group(1).lower() if m else ""
    return "audio" if ext in AUDIO else "video" if ext in VIDEO else None


def parse_block(text):
    """Bloc ```ccs : le dict décrit s'il est valide (JSON, type connu, contenu non vide), sinon None."""
    try:
        spec = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(spec, dict) or spec.get("type") not in TYPES:
        return None
    kind = spec["type"]
    if kind == "choix" and not (isinstance(spec.get("options"), list) and spec["options"]):
        return None
    if kind == "formulaire" and not (isinstance(spec.get("champs"), list) and spec["champs"]):
        return None
    if kind == "cartes" and not (isinstance(spec.get("items"), list) and spec["items"]):
        return None
    if kind == "carte" and not spec.get("titre"):
        return None
    return spec


def _str(v):
    return "" if v is None else str(v)


def option_of(o):
    """Option d'un choix ou action d'une carte : "texte", ou {label, message} / {label, lien}."""
    if isinstance(o, dict):
        return {"label": _str(o.get("label") or o.get("message")),
                "message": _str(o.get("message") or o.get("label")), "lien": _str(o.get("lien"))}
    return {"label": _str(o), "message": _str(o), "lien": ""}


def cards_of(spec):
    """Cartes d'un bloc « carte » ou « cartes » : seulement celles qui ont un titre."""
    items = [spec] if spec.get("type") == "carte" else spec.get("items", [])
    return [c for c in items if isinstance(c, dict) and c.get("titre")]


def web_link(url):
    """Lien http(s) gardé, tout autre schéma refusé (chaîne vide)."""
    url = _str(url).strip()
    return url if re.match(r"^https?://", url, re.I) else ""
