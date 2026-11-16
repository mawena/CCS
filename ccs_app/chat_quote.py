"""Répondre en citant un message du chat, comme dans une messagerie.

Le message envoyé à Claude commence par la citation, en bloc Markdown, puis la réponse :

    > **Claude :**
    > le passage cité
    > sur plusieurs lignes

    la réponse

L'auteur est « Claude » (une de ses réponses) ou « Moi » (un message de l'utilisateur). C'est ce
texte qui est écrit dans le journal de la conversation : le même format sert donc à la relecture
(historique, aperçu, autres appareils) pour montrer la citation à part de la réponse.
Sans entrée-sortie. Le même code existe pour le web : `web/chat-quote.js`.
"""

from dataclasses import dataclass

CLAUDE, ME = "claude", "moi"
LABELS = {CLAUDE: "Claude", ME: "Moi"}      # dans le texte envoyé (c'est l'utilisateur qui parle)
SHOWN = {CLAUDE: "Claude", ME: "Toi"}       # à l'écran (CCS tutoie l'utilisateur)
QUOTE_MAX = 1200          # message cité en entier : au-delà, seulement son début
SELECTION_MAX = 4000      # passage choisi à la souris : coupé plus loin, c'est un choix
CUT_MARK = " […]"
_HEADS = {f"> **{label} :**": author for author, label in LABELS.items()}


@dataclass(frozen=True)
class Quote:
    author: str           # CLAUDE | ME
    text: str             # le passage cité
    body: str = ""        # la réponse qui suit la citation


def excerpt(text, limit=QUOTE_MAX):
    """Texte à citer : sans blancs autour, coupé à `limit` caractères (entre deux mots si possible)."""
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = max(cut.rfind(" "), cut.rfind("\n"))
    if space >= limit - 80:
        cut = cut[:space]
    return cut.rstrip() + CUT_MARK


def compose(author, quoted, body=""):
    """Message à envoyer : la citation puis `body`. Sans citation valable : `body` tel quel."""
    quoted = (quoted or "").replace("\r\n", "\n").strip()
    if author not in LABELS or not quoted:
        return body
    lines = [f"> **{LABELS[author]} :**"]
    lines += [f"> {line}" if line.strip() else ">" for line in quoted.split("\n")]
    head = "\n".join(lines)
    return f"{head}\n\n{body}" if body else head


def split(text):
    """Citation en tête d'un message de l'utilisateur (`Quote`), ou None s'il n'en a pas."""
    if not isinstance(text, str) or not text.startswith("> **"):
        return None
    lines = text.replace("\r\n", "\n").split("\n")
    author = _HEADS.get(lines[0].rstrip())
    if author is None:
        return None
    quoted, i = [], 1
    while i < len(lines) and lines[i].startswith(">"):
        line = lines[i][1:]
        quoted.append(line[1:] if line.startswith(" ") else line)
        i += 1
    quoted_text = "\n".join(quoted).strip()
    if not quoted_text:
        return None
    rest = lines[i:]
    if rest and not rest[0].strip():
        rest = rest[1:]
    return Quote(author, quoted_text, "\n".join(rest))


def reply_text(text):
    """Ce que l'utilisateur a tapé : la réponse sans sa citation (le message entier s'il n'y a
    pas de citation, ou pas de réponse après elle)."""
    quote = split(text)
    return quote.body if quote is not None and quote.body.strip() else text


def source_text(text):
    """Texte d'un message de l'utilisateur à citer à son tour : sa réponse, pas ce qu'il citait."""
    quote = split(text)
    if quote is None:
        return text
    return quote.body if quote.body.strip() else quote.text


def one_line(text, limit=140):
    """Aperçu sur une ligne (bandeau au-dessus de la saisie)."""
    line = " ".join((text or "").split())
    return line[:limit - 1] + "…" if len(line) > limit else line
