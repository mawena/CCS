"""Disposition du graphe des commits façon ungit, portée de GiGit (`src/graph.rs`).

La chaîne des premiers parents depuis HEAD est la « ligne principale » : gros nœuds en
colonne 0. Tout autre commit appartient à la référence qui le « possède » (sa branche
idéologique) et se dessine en petit nœud dans la colonne de cette branche, à droite. Les
commits joignables par aucune référence (une remise, par exemple) sont laissés de côté.
"""

from dataclasses import dataclass, field


@dataclass
class GNode:
    commit: int            # indice dans la liste de commits d'origine
    main: bool             # sur la ligne principale
    slot: int              # colonne : 0 pour la ligne principale, 1… pour les autres branches
    y: float               # position verticale (2 entre deux nœuds principaux, sinon 1)
    branch: object         # nom de la référence propriétaire (sa couleur), ou None


@dataclass(frozen=True)
class GEdge:
    from_: int
    to: int


@dataclass
class Layout:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    height: float = 0.0
    max_slot: int = 0
    index: dict = field(default_factory=dict)    # id de commit → indice de nœud


def layout(commits, refs):
    pos = {c.id: i for i, c in enumerate(commits)}

    def parents_of(i):
        return [pos[p] for p in commits[i].parents if p in pos]

    # Branches idéologiques : les références réclament leur histoire dans l'ordre d'ungit
    # (locales avant distantes, branches avant tags, HEAD en dernier, puis la pointe la plus
    # ancienne d'abord) ; un commit déjà réclamé arrête la remontée.
    order = [(ri, pos[r.target]) for ri, r in enumerate(refs) if r.target in pos]

    def key(item):
        ri, ci = item
        ref = refs[ri]
        is_branch = ref.kind in ("branch", "remote")
        return (ref.kind == "remote", not is_branch, ref.kind == "head", commits[ci].time, ref.name)

    order.sort(key=key)
    owner = [None] * len(commits)
    for ri, ci in order:
        stack = [ci]
        while stack:
            i = stack.pop()
            if owner[i] is not None:
                continue
            owner[i] = ri
            stack.extend(parents_of(i))

    # Ligne principale : premiers parents depuis HEAD.
    main = [False] * len(commits)
    head = next((pos[r.target] for r in refs if r.kind == "head" and r.target in pos), None)
    cur = head
    while cur is not None and not main[cur]:
        main[cur] = True
        first = commits[cur].parents[0] if commits[cur].parents else None
        cur = pos.get(first) if first is not None else None

    kept = [i for i in range(len(commits)) if main[i] or owner[i] is not None]

    # Colonnes : chaque branche prend la colonne libre suivante la première fois qu'on la
    # rencontre en partant du bas.
    slot_of_ref = {}
    next_slot = 1 if head is not None else 0
    slots = [0] * len(commits)
    for i in reversed(kept):
        if main[i]:
            continue
        r = owner[i]
        if r not in slot_of_ref:
            slot_of_ref[r] = next_slot
            next_slot += 1
        slots[i] = slot_of_ref[r]

    out = Layout()
    y = 0.0
    for k, i in enumerate(kept):
        if k > 0:
            y += 2.0 if (main[i] and main[kept[k - 1]]) else 1.0
        out.index[commits[i].id] = k
        out.max_slot = max(out.max_slot, slots[i])
        out.nodes.append(GNode(i, main[i], slots[i], y,
                               refs[owner[i]].name if owner[i] is not None else None))
    out.height = y
    for k, i in enumerate(kept):
        for p in commits[i].parents:
            to = out.index.get(p)
            if to is not None:
                out.edges.append(GEdge(k, to))
    return out
