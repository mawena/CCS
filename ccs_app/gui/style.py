"""Style commun de CCS : classes CSS, couleur des comptes, thème clair / sombre.

Les pages existantes gardent leur CSS (`common.install_css`, `terminals.CSS`) ; ce module
y ajoute les classes des nouvelles pages, avec les couleurs nommées de libadwaita pour
rester lisible en clair comme en sombre."""

import re
import zlib

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .. import account_colors  # noqa: E402

BASE_CSS = """
.ccs-card {
  background-color: @card_bg_color; color: @card_fg_color;
  border-radius: 14px; padding: 14px 16px;
  box-shadow: 0 0 0 1px alpha(@window_fg_color, 0.08), 0 1px 3px alpha(black, 0.10);
}
.ccs-card.flat { box-shadow: 0 0 0 1px alpha(@window_fg_color, 0.08); }
.ccs-card-title { font-weight: 700; }
.ccs-big-number {
  font-size: 2.1rem; font-weight: 800; font-feature-settings: "tnum";
  letter-spacing: -0.02em;
}
.ccs-big-number.small { font-size: 1.5rem; }
.ccs-subtle { color: alpha(@window_fg_color, 0.65); font-size: 0.9em; }

.ccs-bubble-user, .ccs-bubble-claude {
  padding: 10px 14px; border-radius: 16px; margin: 2px 0;
}
.ccs-bubble-user {
  background-color: alpha(@accent_bg_color, 0.20); color: @window_fg_color;
  border-bottom-right-radius: 4px;
}
.ccs-bubble-claude {
  background-color: alpha(@window_fg_color, 0.06); color: @window_fg_color;
  border-bottom-left-radius: 4px;
}

.ccs-tool-card {
  background-color: alpha(@window_fg_color, 0.04); border-radius: 10px;
  border: 1px solid alpha(@window_fg_color, 0.10); border-left: 3px solid @accent_bg_color;
  padding: 6px 10px; font-size: 0.92em;
}
.ccs-tool-card.error { border-left-color: @error_bg_color; }
.ccs-tool-card.done { border-left-color: @success_bg_color; }

.ccs-permission-card {
  background-color: alpha(@warning_bg_color, 0.16); border-radius: 12px;
  border: 1px solid alpha(@warning_bg_color, 0.55); padding: 10px 14px;
}

.ccs-chip {
  background-color: alpha(@window_fg_color, 0.08); border-radius: 99px;
  padding: 2px 10px; font-size: 0.88em; font-weight: 600; min-height: 0;
}
.ccs-chip.accent { background-color: alpha(@accent_bg_color, 0.18); color: @accent_color; }

.ccs-account-dot { min-width: 10px; min-height: 10px; border-radius: 99px; }

levelbar.ccs-gauge trough, progressbar.ccs-gauge trough { min-height: 8px; border-radius: 99px; }
levelbar.ccs-gauge block, progressbar.ccs-gauge progress { border-radius: 99px; min-height: 8px; }
.ccs-gauge-ok block.filled, .ccs-gauge-ok progress { background-color: @success_bg_color; }
.ccs-gauge-warn block.filled, .ccs-gauge-warn progress { background-color: @warning_bg_color; }
.ccs-gauge-crit block.filled, .ccs-gauge-crit progress { background-color: @error_bg_color; }

.ccs-just-done {
  background-color: alpha(@success_bg_color, 0.22); border-radius: 8px;
  box-shadow: inset 0 0 0 1px alpha(@success_bg_color, 0.6);
}
"""

_SCHEMES = {
    "auto": Adw.ColorScheme.DEFAULT,
    "clair": Adw.ColorScheme.FORCE_LIGHT,
    "sombre": Adw.ColorScheme.FORCE_DARK,
}

_base_provider = None
_accounts_provider = None
_last = ([], {})


def account_class(profile):
    """Classe CSS d'un compte, toujours valide : `ccs-account-<nom sûr>`. Un nom qui a dû
    être modifié (`mawena.2`) reçoit une courte empreinte pour ne pas se confondre avec
    un autre (`mawena-2`)."""
    name = str(profile)
    safe = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "compte"
    if safe != name:
        safe += f"-{zlib.crc32(name.encode()) & 0xffff:04x}"
    return f"ccs-account-{safe}"


def accounts_css(profiles, chosen):
    """Règles CSS des comptes (texte), une couleur par profil."""
    out = []
    for p in profiles:
        c = account_colors.color_for(p, profiles, chosen)
        k = "." + account_class(p)
        out.append(
            f"{k} {{ color: {c}; }}\n"
            f"{k}.ccs-account-dot, {k}.ccs-account-bg {{ background-color: {c}; color: white; }}\n"
            f"{k}.ccs-card {{ border-top: 3px solid {c}; }}\n"
            f"{k}.ccs-chip {{ background-color: alpha({c}, 0.20); color: {c}; }}\n"
            f"{k}.ccs-account-bar {{ border-left: 3px solid {c}; }}\n"
            f"{k} levelbar block.filled, {k} progressbar progress {{ background-color: {c}; }}\n")
    return "".join(out)


def _add(css):
    prov = Gtk.CssProvider()
    if hasattr(prov, "load_from_string"):
        prov.load_from_string(css)
    else:
        prov.load_from_data(css.encode())
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    return prov


def install():
    """Installe le CSS commun pour toute l'application (une seule fois)."""
    global _base_provider
    if _base_provider is None:
        _base_provider = _add(BASE_CSS)
        refresh_accounts(*_last)


def apply_color_scheme(value):
    """« auto » suit le système ; « clair » et « sombre » forcent le thème."""
    Adw.StyleManager.get_default().set_color_scheme(_SCHEMES.get(value, Adw.ColorScheme.DEFAULT))


def refresh_accounts(profiles, chosen):
    """Regénère les règles des comptes (nouveau compte, couleur changée)."""
    global _accounts_provider, _last
    _last = (list(profiles), dict(chosen or {}))
    display = Gdk.Display.get_default()
    if _accounts_provider is not None and display is not None:
        Gtk.StyleContext.remove_provider_for_display(display, _accounts_provider)
    _accounts_provider = _add(accounts_css(*_last))
