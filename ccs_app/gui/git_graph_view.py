"""Graphe des commits de la page Git, en deux densités.

- **compact** : une ligne par commit (rails colorés, étiquettes, titre, âge), pour le
  panneau étroit (disposition A) ;
- **cartes** : façon ungit / GiGit, une carte par commit de la ligne principale (avatar,
  titre, auteur, âge, hash) et un petit nœud par commit des autres branches.

Tout est dessiné dans une seule `Gtk.DrawingArea` de la taille de la vue, et seule la
partie visible est peinte : aucun widget par commit, aucune texture de la hauteur de
l'historique (le défilement est tenu par notre propre barre). Les commits arrivent par
pages de 200, la suivante quand on approche du bas.
"""

import bisect
import zlib

from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango, PangoCairo

from .. import avatars, git_graph, git_repo, settings
from ..account_colors import PALETTE, rgb
from ..conversations import ago
from .common import in_thread

PAGE = 200
# compact
ROW = 24
LANE = 12
PAD = 10
# cartes
UNIT = 34
TOP = 34
LANE_C = 22
CARD_H = 50
AVATAR = 28
ACCENT = rgb("#3584e4")


def _avatars_enabled():
    try:
        return bool(settings.load_settings()["git"]["avatars"])
    except Exception:
        return True


def branch_color(name):
    if not name:
        return rgb("#77767b")
    return rgb(PALETTE[zlib.crc32(name.encode("utf-8")) % len(PALETTE)])


class GraphView(Gtk.Box):
    __gsignals__ = {
        "commit-activated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "load-failed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "loaded": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, density="compact"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.density = density if density in ("compact", "cards") else "compact"
        self._repo = None
        self._commits = []
        self._refs = []
        self._labels = {}            # id de commit → [(nom, sorte)]
        self._layout = git_graph.Layout()
        self._ys = []                # y (pixels de contenu) de chaque nœud, croissants
        self._done = False
        self._loading = False
        self._gen = 0
        self._sel = None
        self._width = 480
        self._height = 400
        self._use_avatars = _avatars_enabled()
        self._avatar = {}            # adresse → Pixbuf, None (pas d'avatar) ou "pending"
        self._head_branch = None

        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True, focusable=True)
        self.area.set_draw_func(lambda _a, cr, w, h: self.paint(cr, w, h))
        self.area.connect("resize", self._on_resize)
        self.adj = Gtk.Adjustment(lower=0, upper=1, step_increment=ROW, page_increment=300,
                                  page_size=1)
        self.adj.connect("value-changed", self._on_scrolled)
        self.append(self.area)
        self.append(Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL, adjustment=self.adj))

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_wheel)
        self.area.add_controller(scroll)
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.area.add_controller(click)

    # ---- données ---------------------------------------------------------------------

    def commit_count(self):
        return len(self._commits)

    def loading(self):
        return self._loading

    def selected(self):
        return self._sel

    def commit(self, cid):
        k = self._layout.index.get(cid)
        return self._commits[self._layout.nodes[k].commit] if k is not None else None

    def load(self, repo, keep=False):
        """Charge l'historique de `repo` (première page, ou autant que déjà chargé si
        `keep` : rafraîchissement sans perdre sa place)."""
        same = keep and repo == self._repo
        limit = max(PAGE, len(self._commits)) if same else PAGE
        self._repo = repo
        self._gen += 1
        gen = self._gen
        self._loading = True
        if not same:
            self._sel = None

        def work():
            try:
                return git_repo.log(repo, 0, limit), git_repo.refs(repo), git_repo.branch(repo)
            except git_repo.GitError as e:
                return e

        def done(res):
            if gen != self._gen:
                return
            self._loading = False
            if isinstance(res, git_repo.GitError):
                self._set_data([], [], None, True)
                self.emit("load-failed", str(res))
                return
            commits, refs, br = res
            self._set_data(commits, refs, br.name if br else None, len(commits) < limit)
            self.emit("loaded")
        in_thread(work, done)

    def load_more(self):
        if self._loading or self._done or self._repo is None:
            return
        self._loading = True
        gen, repo, skip = self._gen, self._repo, len(self._commits)

        def work():
            try:
                return git_repo.log(repo, skip, PAGE)
            except git_repo.GitError as e:
                return e

        def done(res):
            if gen != self._gen:
                return
            self._loading = False
            if isinstance(res, git_repo.GitError):
                self._done = True
                return
            self._set_data(self._commits + res, self._refs, self._head_branch, len(res) < PAGE)
        in_thread(work, done)

    def _set_data(self, commits, refs, head_branch, done):
        self._commits, self._refs, self._done = commits, refs, done
        self._head_branch = head_branch
        self._layout = git_graph.layout(commits, refs)
        self._labels = {}
        for r in refs:
            if r.kind == "head":
                continue
            self._labels.setdefault(r.target, []).append((r.name, r.kind))
        self._relayout()

    # ---- géométrie -------------------------------------------------------------------

    def _graph_x0(self):
        """Abscisse de la colonne 0 en mode cartes (les cartes sont à gauche)."""
        return max(170, self._width - (self._layout.max_slot + 1) * LANE_C - 90)

    def _card_w(self):
        return self._graph_x0() - 8 - 26

    def _content_y(self, k):
        if self.density == "compact":
            return k * ROW + ROW / 2
        return TOP + self._layout.nodes[k].y * UNIT

    def _content_x(self, k):
        slot = self._layout.nodes[k].slot
        if self.density == "compact":
            return PAD + slot * LANE + LANE / 2
        return self._graph_x0() + slot * LANE_C

    def _total_height(self):
        n = len(self._layout.nodes)
        if self.density == "compact":
            return n * ROW + 8
        return TOP + self._layout.height * UNIT + CARD_H + 16 if n else 0

    def _relayout(self):
        self._ys = [self._content_y(k) for k in range(len(self._layout.nodes))]
        self.adj.set_upper(max(self._total_height(), self._height))
        self.adj.set_page_size(self._height)
        self.adj.set_page_increment(self._height * 0.9)
        if self.adj.get_value() > self.adj.get_upper() - self._height:
            self.adj.set_value(max(0, self.adj.get_upper() - self._height))
        self.area.queue_draw()

    def node_position(self, cid):
        """Centre du nœud de `cid` dans la vue (défilement compris), ou None."""
        k = self._layout.index.get(cid)
        if k is None:
            return None
        return self._content_x(k), self._ys[k] - self.adj.get_value()

    def node_at(self, x, y):
        yy = y + self.adj.get_value()
        nodes = self._layout.nodes
        if not nodes:
            return None
        if self.density == "compact":
            k = int(yy // ROW)
            return self._commits[nodes[k].commit].id if 0 <= k < len(nodes) else None
        lo = bisect.bisect_left(self._ys, yy - CARD_H)
        hi = bisect.bisect_right(self._ys, yy + CARD_H)
        best, best_d = None, None
        for k in range(lo, hi):
            n = nodes[k]
            nx, ny = self._content_x(k), self._ys[k]
            r = 15 if n.main else 9
            hit = (nx - x) ** 2 + (ny - yy) ** 2 <= r * r
            if n.main and not hit:
                hit = 8 <= x <= 8 + self._card_w() and abs(ny - yy) <= CARD_H / 2
            if hit:
                d = abs(ny - yy)
                if best_d is None or d < best_d:
                    best, best_d = k, d
        return self._commits[nodes[best].commit].id if best is not None else None

    # ---- sélection -------------------------------------------------------------------

    def select(self, cid):
        if cid not in self._layout.index:
            return
        self._sel = cid
        y = self._ys[self._layout.index[cid]]
        v = self.adj.get_value()
        if y < v + ROW or y > v + self._height - ROW:
            self.adj.set_value(max(0, min(y - self._height / 3, self.adj.get_upper() - self._height)))
        self.area.queue_draw()

    def activate(self, cid):
        self.select(cid)
        if cid in self._layout.index:
            self.emit("commit-activated", cid)

    def set_density(self, density):
        if density not in ("compact", "cards") or density == self.density:
            return
        self.density = density
        self._relayout()
        if self._sel:
            self.select(self._sel)

    # ---- événements ------------------------------------------------------------------

    def _on_resize(self, _area, width, height):
        self._width, self._height = max(1, width), max(1, height)
        self._relayout()

    def _on_wheel(self, _ctrl, _dx, dy):
        self.adj.set_value(min(max(0, self.adj.get_value() + dy * ROW * 2),
                               max(0, self.adj.get_upper() - self.adj.get_page_size())))
        return True

    def _on_scrolled(self, adj):
        self.area.queue_draw()
        if adj.get_value() + adj.get_page_size() >= adj.get_upper() - 2 * adj.get_page_size():
            self.load_more()

    def _on_click(self, _gesture, _n, x, y):
        self.area.grab_focus()
        cid = self.node_at(x, y)
        if cid:
            self.activate(cid)

    # ---- dessin ----------------------------------------------------------------------

    def _fg(self):
        try:
            c = self.get_color()
            return (c.red, c.green, c.blue)
        except (AttributeError, TypeError):
            return (0.2, 0.2, 0.2)

    def paint(self, cr, width, height):
        if width != self._width or height != self._height:
            self._width, self._height = max(1, width), max(1, height)
            self._relayout()
        nodes = self._layout.nodes
        if not nodes:
            return
        fg = self._fg()
        top = self.adj.get_value()
        bottom = top + height
        margin = CARD_H if self.density == "cards" else ROW
        lo = bisect.bisect_left(self._ys, top - margin)
        hi = bisect.bisect_right(self._ys, bottom + margin)
        cr.save()
        cr.translate(0, -top)
        self._paint_edges(cr, top - margin, bottom + margin)
        for k in range(lo, hi):
            if self.density == "compact":
                self._paint_row(cr, k, fg)
            else:
                self._paint_card(cr, k, fg)
        cr.restore()

    def _paint_edges(self, cr, top, bottom):
        nodes = self._layout.nodes
        cr.set_line_width(2 if self.density == "compact" else 3)
        for e in self._layout.edges:
            y1, y2 = self._ys[e.from_], self._ys[e.to]
            if max(y1, y2) < top or min(y1, y2) > bottom:
                continue
            x1, x2 = self._content_x(e.from_), self._content_x(e.to)
            a, b = nodes[e.from_], nodes[e.to]
            side = a if a.slot >= b.slot else b
            cr.set_source_rgba(*branch_color(side.branch), 0.85)
            cr.move_to(x1, y1)
            bend = min(ROW if self.density == "compact" else UNIT, abs(y2 - y1))
            if x1 == x2:
                cr.line_to(x2, y2)
            elif a.slot > b.slot:          # la branche rejoint son origine : virage en bas
                cr.line_to(x1, y2 - bend)
                cr.curve_to(x1, y2 - bend / 2, x2, y2 - bend / 2, x2, y2)
            else:                          # fusion : virage en haut, puis descente
                cr.curve_to(x1, y1 + bend / 2, x2, y1 + bend / 2, x2, y1 + bend)
                cr.line_to(x2, y2)
            cr.stroke()

    def _node(self, cr, k, radius):
        n = self._layout.nodes[k]
        x, y = self._content_x(k), self._ys[k]
        cid = self._commits[n.commit].id
        cr.set_source_rgb(*branch_color(n.branch))
        cr.arc(x, y, radius, 0, 6.2832)
        cr.fill()
        if cid == self._sel:
            cr.set_source_rgb(*ACCENT)
            cr.set_line_width(2)
            cr.arc(x, y, radius + 3, 0, 6.2832)
            cr.stroke()

    def _text(self, cr, text, x, y, width, size=9.5, bold=False, rgba=None, align_right=False):
        layout = PangoCairo.create_layout(cr)
        desc = Pango.FontDescription.from_string(f"Sans {'Bold ' if bold else ''}{size}")
        layout.set_font_description(desc)
        layout.set_text(text, -1)
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        layout.set_width(int(max(1, width) * Pango.SCALE))
        if align_right:
            layout.set_alignment(Pango.Alignment.RIGHT)
        _ink, logical = layout.get_pixel_extents()
        cr.set_source_rgba(*(rgba or (0, 0, 0, 1)))
        cr.move_to(x, y - logical.height / 2)
        PangoCairo.show_layout(cr, layout)
        return logical.width

    def _labels_of(self, cid):
        out = []
        for name, kind in self._labels.get(cid, ()):
            current = kind == "branch" and name == self._head_branch
            out.append((("● " if current else "") + name, kind))
        return out

    def _pill(self, cr, text, x, y, kind, fg):
        color = rgb("#e5a50a") if kind == "tag" else branch_color(text.lstrip("● "))
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription.from_string("Sans 8"))
        layout.set_text(text, -1)
        _i, log = layout.get_pixel_extents()
        w, h = log.width + 10, log.height + 2
        cr.set_source_rgba(*color, 0.18)
        self._round_rect(cr, x, y - h / 2, w, h, 4)
        cr.fill()
        cr.set_source_rgba(*color, 1)
        cr.move_to(x + 5, y - log.height / 2)
        PangoCairo.show_layout(cr, layout)
        return w

    @staticmethod
    def _round_rect(cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5708, 0)
        cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
        cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
        cr.arc(x + r, y + r, r, 3.1416, 4.7124)
        cr.close_path()

    def _paint_row(self, cr, k, fg):
        n = self._layout.nodes[k]
        c = self._commits[n.commit]
        y = self._ys[k]
        if c.id == self._sel:
            cr.set_source_rgba(*ACCENT, 0.16)
            cr.rectangle(0, y - ROW / 2, self._width, ROW)
            cr.fill()
        self._node(cr, k, 5 if n.main else 3.5)
        x = PAD + (self._layout.max_slot + 1) * LANE + 6
        age = ago(c.time) if c.time else ""
        age_w = 74
        right = self._width - age_w - 6
        for text, kind in self._labels_of(c.id):
            if x > right - 40:
                break
            x += self._pill(cr, text, x, y, kind, fg) + 4
        self._text(cr, c.subject, x, y, right - x, rgba=(*fg, 1))
        self._text(cr, age, right + 4, y, age_w, size=8.5, rgba=(*fg, 0.55), align_right=True)

    def _paint_card(self, cr, k, fg):
        n = self._layout.nodes[k]
        c = self._commits[n.commit]
        y = self._ys[k]
        if n.main:
            x0, w = 8, self._card_w()
            cr.set_source_rgba(*fg, 0.07)
            self._round_rect(cr, x0, y - CARD_H / 2, w, CARD_H, 8)
            cr.fill_preserve()
            if c.id == self._sel:
                cr.set_source_rgba(*ACCENT, 1)
                cr.set_line_width(1.5)
            else:
                cr.set_source_rgba(*fg, 0.10)
                cr.set_line_width(1)
            cr.stroke()
            self._paint_avatar(cr, c, x0 + 8, y - AVATAR / 2, fg)
            tx = x0 + 8 + AVATAR + 8
            tw = w - (tx - x0) - 8
            self._text(cr, c.subject, tx, y - 9, tw, size=9.5, bold=True, rgba=(*fg, 1))
            meta = f"{c.author} · {ago(c.time) if c.time else ''} · {c.id[:7]}"
            self._text(cr, meta, tx, y + 10, tw, size=8.5, rgba=(*fg, 0.6))
        self._node(cr, k, 14 if n.main else 7)
        lx = self._graph_x0() + (self._layout.max_slot + 1) * LANE_C - 4
        for text, kind in self._labels_of(c.id):
            if lx > self._width - 30:
                break
            lx += self._pill(cr, text, lx, y, kind, fg) + 4

    def _paint_avatar(self, cr, c, x, y, fg):
        pix = self._avatar_for(c.email)
        cx, cy, r = x + AVATAR / 2, y + AVATAR / 2, AVATAR / 2
        cr.save()
        cr.arc(cx, cy, r, 0, 6.2832)
        cr.clip()
        if isinstance(pix, GdkPixbuf.Pixbuf):
            Gdk.cairo_set_source_pixbuf(cr, pix, x, y)
            cr.paint()
        else:
            cr.set_source_rgb(*branch_color(c.email or c.author))
            cr.paint()
            self._text(cr, avatars.initials(c.author), x, cy, AVATAR, size=8.5, bold=True,
                       rgba=(1, 1, 1, 1))
        cr.restore()

    def _avatar_for(self, email):
        if not self._use_avatars or not email:
            return None
        if email in self._avatar:
            return self._avatar[email]
        self._avatar[email] = "pending"

        def done(path):
            pix = None
            if path is not None:
                try:
                    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), AVATAR, AVATAR, True)
                except GLib.Error:
                    pix = None
            self._avatar[email] = pix
            self.area.queue_draw()
        in_thread(lambda: avatars.fetch(email), done)
        return "pending"
