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


def remote_src(src):
    """Adresse https d'une image ou d'un média gardée telle quelle, sinon chaîne vide."""
    src = _str(src).strip()
    return src if re.match(r"^https://", src, re.I) else ""


def form_fields(spec):
    """Champs d'un formulaire : {cle, label, type, options, valeur, aide} pour chaque objet de
    `champs` (le reste est ignoré). `cle` : `nom`, à défaut `label`."""
    out = []
    for f in spec.get("champs") or []:
        if not isinstance(f, dict):
            continue
        options = f.get("options")
        out.append({"cle": _str(f["nom"] if f.get("nom") is not None else f.get("label")),
                    "label": _str(f.get("label") or f.get("nom")),
                    "type": _str(f.get("type")) or "texte",
                    "options": [_str(o) for o in options] if isinstance(options, list) else [],
                    "valeur": None if f.get("valeur") is None else _str(f["valeur"]),
                    "aide": _str(f.get("aide"))})
    return out


def form_message(spec, values):
    """Message envoyé par un formulaire : le titre, puis « - Libellé : valeur » par champ rempli
    (`values` : {cle: texte}). Même texte que la version web (formMessage)."""
    lines = [_str(spec["titre"])] if spec.get("titre") else []
    for f in form_fields(spec):
        v = _str(values.get(f["cle"])).strip()
        if v:
            lines.append(f"- {f['label']} : {v}")
    return "\n".join(lines)
