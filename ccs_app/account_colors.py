"""Couleur de chaque compte (sans GTK) : une palette lisible en clair comme en sombre,
attribuée automatiquement dans l'ordre alphabétique des profils, modifiable par choix."""

import re

PALETTE = ("#3584e4", "#c061cb", "#2ec27e", "#e5a50a", "#e66100", "#1c71d8", "#9141ac", "#26a269")

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _valid(value):
    return isinstance(value, str) and bool(_HEX.match(value))


def color_for(profile, profiles, chosen):
    """Couleur du compte `profile` : la couleur choisie si elle est valide (`#rrggbb`),
    sinon la première couleur de la palette non prise, dans l'ordre alphabétique des
    profils ; quand la palette est épuisée, on reboucle."""
    chosen = chosen or {}
    names = sorted(set(profiles or ()) | {profile})
    if _valid(chosen.get(profile)):
        return chosen[profile].lower()
    taken = {chosen[p].lower() for p in names if _valid(chosen.get(p))}
    given = 0
    for p in names:
        if _valid(chosen.get(p)):
            continue
        free = next((c for c in PALETTE if c not in taken), None)
        if free is None:
            free = PALETTE[given % len(PALETTE)]
        taken.add(free)
        given += 1
        if p == profile:
            return free
    return PALETTE[0]  # inatteignable : `profile` est dans `names`


def rgb(hex_color):
    """`#rrggbb` en (r, g, b), flottants de 0 à 1 (pour cairo). Invalide : gris."""
    if not _valid(hex_color):
        return (0.5, 0.5, 0.5)
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
