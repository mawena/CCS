"""Analyse du Markdown en blocs simples (sans GTK), pour le chat et l'aperçu des fichiers.

`parse(text)` rend une liste de blocs (dataclasses) ; `to_pango(spans)` rend un balisage
Pango échappé, utilisable tel quel dans un `Gtk.Label` (`use_markup=True`).
"""

from dataclasses import dataclass, field

from markdown_it import MarkdownIt


@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    strike: bool = False
    link: str | None = None


@dataclass
class Heading:
    level: int
    spans: list


@dataclass
class Paragraph:
    spans: list


@dataclass
class Item:
    checked: bool | None
    blocks: list = field(default_factory=list)


@dataclass
class ListBlock:
    ordered: bool
    start: int
    items: list = field(default_factory=list)


@dataclass
class Code:
    lang: str
    text: str


@dataclass
class Table:
    header: list
    align: list
    rows: list


@dataclass
class Quote:
    blocks: list = field(default_factory=list)


@dataclass
class Rule:
    pass


@dataclass
class Image:
    src: str
    alt: str


def _parser():
    return MarkdownIt("commonmark").enable("table").enable("strikethrough")


def escape(text):
    """Échappe `&`, `<` et `>` pour Pango."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_pango(spans):
    """Balisage Pango échappé d'une suite de morceaux de texte."""
    out = []
    for s in spans:
        if not s.text:
            continue
        part = escape(s.text)
        if s.code:
            part = f"<tt>{part}</tt>"
        if s.bold:
            part = f"<b>{part}</b>"
        if s.italic:
            part = f"<i>{part}</i>"
        if s.strike:
            part = f"<s>{part}</s>"
        if s.link:
            href = escape(s.link).replace('"', "&quot;")
            part = f'<a href="{href}">{part}</a>'
        out.append(part)
    return "".join(out)


def _inline(token):
    """Convertit les enfants d'un jeton `inline` en blocs : renvoie une liste mêlant
    des listes de `Span` (texte) et des `Image`."""
    pieces, spans = [], []
    bold = italic = strike = 0
    link = []
    for t in token.children or []:
        kind = t.type
        if kind == "strong_open":
            bold += 1
        elif kind == "strong_close":
            bold -= 1
        elif kind == "em_open":
            italic += 1
        elif kind == "em_close":
            italic -= 1
        elif kind == "s_open":
            strike += 1
        elif kind == "s_close":
            strike -= 1
        elif kind == "link_open":
            link.append(t.attrGet("href") or "")
        elif kind == "link_close":
            if link:
                link.pop()
        elif kind == "image":
            if spans:
                pieces.append(spans)
                spans = []
            pieces.append(Image(t.attrGet("src") or "", t.content))
        elif kind in ("softbreak", "hardbreak"):
            spans.append(Span("\n" if kind == "hardbreak" else " ", bold=bold > 0, italic=italic > 0,
                              strike=strike > 0, link=link[-1] if link else None))
        elif kind in ("text", "code_inline", "html_inline"):
            spans.append(Span(t.content, bold=bold > 0, italic=italic > 0, code=kind == "code_inline",
                              strike=strike > 0, link=link[-1] if link else None))
    if spans:
        pieces.append(spans)
    return pieces


def _spans(token):
    """Les morceaux de texte d'un `inline` (les images y sont remplacées par leur texte alternatif)."""
    out = []
    for piece in _inline(token):
        out.extend(piece if isinstance(piece, list) else [Span(piece.alt)])
    return out


def _blocks(tokens, i, closer=None):
    """Lit des blocs à partir de `tokens[i]` jusqu'au jeton fermant `closer` (exclu).
    Renvoie `(blocs, indice du jeton suivant)`."""
    blocks = []
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if closer and t.type == closer:
            return blocks, i
        kind = t.type
        if kind == "heading_open":
            blocks.append(Heading(int(t.tag[1:]), _spans(tokens[i + 1])))
            i += 3
        elif kind == "paragraph_open":
            for piece in _inline(tokens[i + 1]):
                blocks.append(Image(piece.src, piece.alt) if isinstance(piece, Image) else Paragraph(piece))
            i += 3
        elif kind in ("bullet_list_open", "ordered_list_open"):
            ordered = kind == "ordered_list_open"
            lst = ListBlock(ordered, int(t.attrGet("start") or 1) if ordered else 1)
            close = kind.replace("_open", "_close")
            i += 1
            while i < n and tokens[i].type != close:
                inner, i = _blocks(tokens, i + 1, "list_item_close")
                lst.items.append(_item(inner))
                i += 1
            blocks.append(lst)
            i += 1
        elif kind in ("fence", "code_block"):
            lang = (t.info or "").strip().split()[0] if kind == "fence" and (t.info or "").strip() else ""
            blocks.append(Code(lang, t.content.rstrip("\n")))
            i += 1
        elif kind == "blockquote_open":
            inner, i = _blocks(tokens, i + 1, "blockquote_close")
            blocks.append(Quote(inner))
            i += 1
        elif kind == "hr":
            blocks.append(Rule())
            i += 1
        elif kind == "table_open":
            table, i = _table(tokens, i)
            blocks.append(table)
        elif kind == "html_block":
            blocks.append(Paragraph([Span(t.content.strip("\n"))]))
            i += 1
        else:
            i += 1
    return blocks, i


def _item(blocks):
    """Reconnaît la case `[ ]` / `[x]` en tête d'un élément de liste."""
    checked = None
    if blocks and isinstance(blocks[0], Paragraph) and blocks[0].spans:
        first = blocks[0].spans[0]
        for mark, value in (("[ ] ", False), ("[x] ", True), ("[X] ", True)):
            if first.text.startswith(mark):
                checked = value
                first.text = first.text[len(mark):]
                break
        else:
            if first.text in ("[ ]", "[x]", "[X]") and len(blocks[0].spans) == 1:
                checked = first.text != "[ ]"
                blocks[0].spans = []
    return Item(checked, blocks)


def _table(tokens, i):
    header, align, rows = [], [], []
    current = None
    in_head = False
    i += 1
    while i < len(tokens) and tokens[i].type != "table_close":
        t = tokens[i]
        if t.type == "thead_open":
            in_head = True
        elif t.type == "thead_close":
            in_head = False
        elif t.type == "tr_open":
            current = []
        elif t.type == "tr_close":
            if in_head:
                header.extend(current)
            else:
                rows.append(current)
        elif t.type in ("th_open", "td_open"):
            style = t.attrGet("style") or ""
            if in_head:
                align.append(style.split(":", 1)[1].strip(" ;") if "text-align" in style else None)
            current.append(_spans(tokens[i + 1]))
            i += 2
        i += 1
    return Table(header, align, rows), i + 1


def parse(text):
    """Analyse un texte Markdown. Texte vide : liste vide ; fins de ligne CRLF acceptées."""
    if not text:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks, _ = _blocks(_parser().parse(text), 0)
    return blocks
