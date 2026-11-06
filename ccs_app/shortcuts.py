"""Raccourcis clavier globaux : raccourcis personnalisés du bureau GNOME.

Ils marchent même quand l'application est fermée : c'est le bureau
(gnome-settings-daemon) qui lance la commande. CCS les range comme ceux que
l'on crée dans Paramètres › Clavier › Raccourcis personnalisés :

- la liste `custom-keybindings` du schéma
  `org.gnome.settings-daemon.plugins.media-keys` (chemins dconf, dans l'ordre) ;
- pour chaque chemin, le schéma relogeable
  `org.gnome.settings-daemon.plugins.media-keys.custom-keybinding`
  (clés `name`, `command`, `binding`).

CCS n'écrit que sous ses propres chemins (`…/custom-keybindings/ccs-<action>/`)
et ne retire jamais un raccourci qui n'est pas à lui. La liste est relue juste
avant d'être réécrite, en une seule écriture qui garde l'ordre ; les valeurs
d'un raccourci sont posées avant son ajout à la liste et effacées après son
retrait. Toutes les lectures et écritures passent par un « moteur » : `GioBackend`
(vrais réglages, Gio.Settings) ou `MemoryBackend` (tests, essais).

API : ACTIONS, action(), parse_binding(), normalize(), label(), same(), is_modifier_key(),
supported(), status(), install(), remove(), remove_all(), set_binding(),
update_commands(), conflicts(), format_text(), command() (`ccs raccourcis`).
"""

import copy
import os
import re
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = MEDIA_KEYS + ".custom-keybinding"
CUSTOM_KEY = "custom-keybindings"
CUSTOM_DIR = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
OWN_PREFIX = CUSTOM_DIR + "ccs-"
CUSTOM_FIELDS = ("name", "command", "binding")
_OWN_RE = re.compile("^" + re.escape(OWN_PREFIX) + r"[a-z0-9-]+/$")

# Raccourcis du bureau examinés pour les conflits (absents : ignorés). Le Dock et
# l'assistant de tuilage sont activés d'office sous Ubuntu.
KEYBINDING_SCHEMAS = (
    "org.gnome.desktop.wm.keybindings",
    "org.gnome.shell.keybindings",
    "org.gnome.mutter.keybindings",
    "org.gnome.mutter.wayland.keybindings",
    MEDIA_KEYS,
    "org.gnome.shell.extensions.dash-to-dock",
    "org.gnome.shell.extensions.tiling-assistant",
)

USR_BIN = Path("/usr/bin")
REPO_BIN = Path(__file__).resolve().parent.parent / "bin"


class ShortcutError(Exception):
    """Raccourci invalide, action inconnue, bureau non pris en charge… (message affichable)."""


# --------------------------------------------------------------------------
# Actions proposées
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Action:
    id: str
    label: str
    program: str      # « ccs » ou « claude-accounts », chemin résolu à l'installation
    args: tuple
    default: str      # raccourci par défaut (format GTK)

    @property
    def display(self):
        """Commande courte, pour l'affichage : « ccs next »."""
        return " ".join((self.program, *self.args))

    @property
    def path(self):
        return f"{OWN_PREFIX}{self.id}/"

    @property
    def title(self):
        """Nom affiché dans Paramètres › Clavier."""
        return f"CCS : {self.label}"


# Super+Alt+lettre : aucune de ces combinaisons n'est prise par GNOME 46, le Dock
# ou l'assistant de tuilage d'Ubuntu (Super+Alt+S, 8, =, - le sont : lecteur
# d'écran, loupe). Lettres plutôt que chiffres : mêmes touches en AZERTY.
ACTIONS = (
    Action("ouvrir", "Ouvrir Comptes Claude", "claude-accounts", ("gui",), "<Super><Alt>c"),
    Action("sessions", "Afficher les sessions", "claude-accounts", ("gui", "--page", "sessions"),
           "<Super><Alt>v"),
    Action("nouvelle-session", "Nouvelle session", "claude-accounts", ("gui", "--new-session"),
           "<Super><Alt>n"),
    Action("suivant", "Basculer sur le compte suivant", "ccs", ("next",), "<Super><Alt>b"),
    Action("meilleur", "Basculer sur le meilleur compte", "ccs", ("best",), "<Super><Alt>m"),
    Action("pause", "Pause 1 h", "ccs", ("pause", "1h"), "<Super><Alt>p"),
    Action("reprendre", "Reprendre (lever la pause)", "ccs", ("pause", "off"), "<Super><Alt>r"),
)
ACTION_IDS = tuple(a.id for a in ACTIONS)
_BY_ID = {a.id: a for a in ACTIONS}


def action(action_id):
    if isinstance(action_id, Action):
        return action_id
    try:
        return _BY_ID[action_id]
    except (KeyError, TypeError):
        raise ShortcutError(f"Action inconnue : « {action_id} » ({', '.join(ACTION_IDS)}).") from None


def is_ours(path):
    return bool(_OWN_RE.match(path or ""))


def _id_of(path):
    name = path[len(CUSTOM_DIR):].rstrip("/")
    short = name[len("ccs-"):]
    return short if short in _BY_ID else name


def program_path(program):
    """Chemin absolu du programme : paquet installé (/usr/bin), sinon le dépôt, sinon le PATH."""
    for directory in (USR_BIN, REPO_BIN):
        p = Path(directory) / program
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which(program) or program


def command_for(act):
    """Commande écrite dans le raccourci (lue par g_shell_parse_argv, sans shell)."""
    act = action(act)
    return shlex.join([program_path(act.program), *act.args])


# --------------------------------------------------------------------------
# Raccourcis : lecture, validation, libellés
# --------------------------------------------------------------------------

MOD_ORDER = ("Super", "Control", "Alt", "Shift", "Meta", "Hyper")
_MOD_LABELS = {"Super": "Super", "Control": "Ctrl", "Alt": "Alt", "Shift": "Maj",
               "Meta": "Meta", "Hyper": "Hyper"}
_MODS = {"super": "Super", "mod4": "Super", "win": "Super", "windows": "Super", "logo": "Super",
         "control": "Control", "ctrl": "Control", "ctl": "Control", "primary": "Control",
         "alt": "Alt", "mod1": "Alt", "shift": "Shift", "maj": "Shift",
         "meta": "Meta", "hyper": "Hyper"}
_STRONG = {"Super", "Control", "Alt", "Meta", "Hyper"}  # Maj seule ne suffit pas
_MODIFIER_KEYS = {n.lower() for n in (
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Super_L", "Super_R",
    "Meta_L", "Meta_R", "Hyper_L", "Hyper_R", "ISO_Level3_Shift", "ISO_Level5_Shift",
    "Caps_Lock", "Shift_Lock", "Num_Lock", "Mode_switch")}

_NAMED = (
    "space", "Return", "Tab", "Escape", "BackSpace", "Delete", "Insert", "Home", "End",
    "Page_Up", "Page_Down", "Left", "Right", "Up", "Down", "Print", "Pause", "Scroll_Lock",
    "Menu", "Above_Tab",
    "minus", "equal", "plus", "comma", "period", "slash", "backslash", "semicolon", "colon",
    "apostrophe", "quotedbl", "grave", "asciitilde", "bracketleft", "bracketright",
    "braceleft", "braceright", "parenleft", "parenright", "less", "greater", "exclam",
    "question", "at", "numbersign", "dollar", "percent", "asciicircum", "ampersand",
    "asterisk", "underscore", "bar", "section", "degree", "sterling", "mu", "twosuperior",
    "eacute", "egrave", "agrave", "ccedilla", "ugrave", "dead_circumflex", "dead_diaeresis",
    "KP_Add", "KP_Subtract", "KP_Multiply", "KP_Divide", "KP_Enter", "KP_Decimal",
    *(f"F{i}" for i in range(1, 36)), *(f"KP_{i}" for i in range(10)),
    *"abcdefghijklmnopqrstuvwxyz0123456789",
)
_KEY_LABELS = {
    "space": "Espace", "Return": "Entrée", "Escape": "Échap", "BackSpace": "Retour arrière",
    "Delete": "Suppr", "Insert": "Inser", "Home": "Début", "End": "Fin",
    "Page_Up": "Page préc.", "Page_Down": "Page suiv.", "Left": "←", "Right": "→",
    "Up": "↑", "Down": "↓", "Print": "Impr. écran", "minus": "-", "equal": "=", "plus": "+",
    "comma": ",", "period": ".", "slash": "/", "backslash": "\\", "semicolon": ";",
    "colon": ":", "apostrophe": "'", "grave": "`", "bracketleft": "[", "bracketright": "]",
    "asterisk": "*", "exclam": "!", "question": "?", "eacute": "é", "egrave": "è",
    "agrave": "à", "ccedilla": "ç", "ugrave": "ù",
}
_CANON = {n.lower(): n for n in _NAMED}
_CANON.update({lbl.lower(): name for name, lbl in _KEY_LABELS.items()  # « Page suiv. », « é »…
               if not (len(lbl) == 1 and lbl.isascii() and lbl.isalnum())})
_CANON.update({
    "prior": "Page_Up", "next": "Page_Down", "pageup": "Page_Up", "pagedown": "Page_Down",
    "pgup": "Page_Up", "pgdown": "Page_Down", "pgdn": "Page_Down", "esc": "Escape",
    "echap": "Escape", "enter": "Return", "entree": "Return", "del": "Delete",
    "ins": "Insert", "debut": "Home", "impr": "Print", "printscreen": "Print",
})
_XF86 = re.compile(r"^XF86[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class Binding:
    mods: tuple   # dans l'ordre de MOD_ORDER
    key: str      # nom de touche canonique (lettres en minuscules)

    @property
    def accel(self):
        """Format GTK / GNOME : <Super><Alt>c."""
        return "".join(f"<{m}>" for m in self.mods) + self.key

    @property
    def label(self):
        """Libellé lisible : Super+Alt+C."""
        key = self.key
        key = key.upper() if len(key) == 1 else _KEY_LABELS.get(key, key)
        return "+".join([*(_MOD_LABELS[m] for m in self.mods), key])


def _gdk_known(name):
    """Nom de touche reconnu par GDK, s'il est là (touches mortes, lettres accentuées…)."""
    try:
        import gi
        try:
            gi.require_version("Gdk", "4.0")
        except ValueError:
            pass  # déjà chargé dans une autre version (GTK 3) : elle convient aussi
        from gi.repository import Gdk
        value = Gdk.keyval_from_name(name)
    except Exception:  # noqa: BLE001 — sans GDK, seule la table connue compte
        return False
    return value not in (0, 0xFFFFFF)


def _split(text):
    t = text.strip()
    if t.startswith("<"):
        mods = []
        while t.startswith("<"):
            end = t.find(">")
            if end < 0:
                raise ShortcutError(f"Raccourci illisible : « {text} ».")
            mods.append(t[1:end])
            t = t[end + 1:]
        return mods, t.strip()
    parts = t[:-2].split("+") + ["+"] if t.endswith("++") else t.split("+")
    parts = [p.strip() for p in parts]
    return parts[:-1], parts[-1]


def _parse(text, strict):
    if not isinstance(text, str) or not text.strip():
        raise ShortcutError("Raccourci vide.")
    raw_mods, raw_key = _split(text)
    mods = set()
    for m in raw_mods:
        canon = _MODS.get(m.strip().lower())
        if canon is None:
            raise ShortcutError(f"Modificateur inconnu : « {m} » (Super, Ctrl, Alt, Maj).")
        mods.add(canon)
    if not raw_key:
        raise ShortcutError("Il manque la touche (ex. Super+Alt+C).")
    low = raw_key.lower()
    if low in _MODIFIER_KEYS or low in _MODS:
        raise ShortcutError(f"« {raw_key} » est un modificateur : ajoute une touche (ex. Super+Alt+C).")
    key = _CANON.get(low)
    if key is None:
        if _XF86.match(raw_key) or not strict or _gdk_known(raw_key):
            key = raw_key
        else:
            raise ShortcutError(f"Touche inconnue : « {raw_key} ».")
    if strict and not mods & _STRONG and not key.startswith("XF86"):
        raise ShortcutError("Ajoute Super, Ctrl ou Alt : seule (ou avec Maj), cette touche "
                            "serait prise à toutes les applications.")
    return Binding(tuple(m for m in MOD_ORDER if m in mods), key)


def parse_binding(text):
    """Raccourci saisi (« <Super><Alt>c », « Super+Alt+C », « Ctrl+Maj+F5 »…) → Binding.
    Lève ShortcutError (message affichable) s'il est invalide ou dangereux (sans Super,
    Ctrl ni Alt, sauf touche multimédia XF86…)."""
    return _parse(text, strict=True)


def _loose(text):
    """Raccourci du bureau tel quel (touche seule permise), None s'il est illisible."""
    try:
        return _parse(text, strict=False)
    except ShortcutError:
        return None


def is_modifier_key(name):
    """Touche de modification seule (Shift_L, Super_R, ISO_Level3_Shift…) : la capture
    d'un raccourci attend la touche suivante."""
    return bool(name) and name.lower() in _MODIFIER_KEYS


def normalize(text):
    """Forme GTK canonique (« <Super><Alt>c »), None si le raccourci est invalide."""
    try:
        return parse_binding(text).accel
    except ShortcutError:
        return None


def label(text):
    """Libellé lisible (« Super+Alt+C ») ; « aucun » pour un raccourci vide."""
    if not text:
        return "aucun"
    b = _loose(text)
    return b.label if b else text


def same(a, b):
    """Deux raccourcis désignent-ils la même combinaison (<Primary> = <Control>…) ?"""
    x, y = _loose(a), _loose(b)
    return x is not None and x == y


# --------------------------------------------------------------------------
# Moteurs de réglages
# --------------------------------------------------------------------------

class MemoryBackend:
    """Réglages en mémoire : schémas (valeurs par défaut), valeurs, journal des écritures
    (`log` : ("set", schéma, chemin, {clé: valeur}) / ("reset", schéma, chemin, clés))."""

    def __init__(self):
        self.schemas = {}     # schéma → {clé: valeur par défaut}
        self.values = {}      # (schéma, chemin) → {clé: valeur}
        self.summaries = {}   # (schéma, clé) → résumé
        self.log = []
        self._watchers = {}
        self._next = 0

    @classmethod
    def gnome(cls):
        """Bureau GNOME minimal : liste des raccourcis personnalisés vide."""
        b = cls()
        b.add_schema(MEDIA_KEYS, {CUSTOM_KEY: []})
        b.add_schema(CUSTOM_SCHEMA, {k: "" for k in CUSTOM_FIELDS})
        return b

    @classmethod
    def from_installed_defaults(cls):
        """Valeurs par défaut des schémas installés (jamais les réglages de l'utilisateur)."""
        from gi.repository import Gio
        source = Gio.SettingsSchemaSource.get_default()
        b = cls()
        for sid in (*KEYBINDING_SCHEMAS, CUSTOM_SCHEMA):
            schema = source.lookup(sid, True) if source else None
            if schema is None:
                continue
            keys = {}
            for k in schema.list_keys():
                sk = schema.get_key(k)
                keys[k] = sk.get_default_value().unpack()
                b.summaries[(sid, k)] = sk.get_summary() or ""
            b.add_schema(sid, keys)
        return b

    def add_schema(self, schema, defaults):
        self.schemas.setdefault(schema, {}).update(copy.deepcopy(defaults))

    def has_schema(self, schema):
        return schema in self.schemas

    def keys(self, schema):
        return list(self.schemas.get(schema, {}))

    def _check(self, schema, keys):
        known = self.schemas[schema]  # KeyError : schéma absent
        for k in keys:
            if k not in known:
                raise KeyError(k)

    def get(self, schema, key, path=None):
        self._check(schema, [key])
        stored = self.values.get((schema, path), {})
        return copy.deepcopy(stored[key] if key in stored else self.schemas[schema][key])

    def set(self, schema, values, path=None):
        self._check(schema, values)
        self.values.setdefault((schema, path), {}).update(copy.deepcopy(values))
        self.log.append(("set", schema, path, copy.deepcopy(dict(values))))
        self._changed()

    def reset(self, schema, keys, path=None):
        keys = tuple(keys)
        self._check(schema, keys)
        stored = self.values.get((schema, path), {})
        for k in keys:
            stored.pop(k, None)
        self.log.append(("reset", schema, path, keys))
        self._changed()

    def summary(self, schema, key):
        return self.summaries.get((schema, key), "")

    def watch(self, callback):
        self._next += 1
        self._watchers[self._next] = callback
        return self._next

    def unwatch(self, token):
        self._watchers.pop(token, None)

    def _changed(self):
        for cb in list(self._watchers.values()):
            cb()

    def sync(self):
        pass


class GioBackend:
    """Vrais réglages du bureau (Gio.Settings, dconf). Chaque écriture est un seul
    changement (delay/apply), attendu jusqu'au bout (Gio.Settings.sync)."""

    def __init__(self):
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as e:
            raise ShortcutError(f"PyGObject (Gio) introuvable : {e}") from e
        self.Gio, self.GLib = Gio, GLib
        self.source = Gio.SettingsSchemaSource.get_default()
        self._readers = {}
        self._watchers = {}
        self._next = 0

    def _schema(self, sid):
        return self.source.lookup(sid, True) if self.source else None

    def _settings(self, sid, path, fresh=False):
        schema = self._schema(sid)
        if schema is None:
            raise KeyError(sid)
        if fresh:
            return self.Gio.Settings.new_full(schema, None, path), schema
        cache = (sid, path)
        if cache not in self._readers:
            self._readers[cache] = self.Gio.Settings.new_full(schema, None, path)
        return self._readers[cache], schema

    def has_schema(self, sid):
        return self._schema(sid) is not None

    def keys(self, sid):
        schema = self._schema(sid)
        return list(schema.list_keys()) if schema else []

    def get(self, sid, key, path=None):
        s, schema = self._settings(sid, path)
        if not schema.has_key(key):
            raise KeyError(key)
        return s.get_value(key).unpack()

    def set(self, sid, values, path=None):
        s, schema = self._settings(sid, path, fresh=True)
        variants = {}
        for k, v in values.items():
            if not schema.has_key(k):
                raise KeyError(k)
            if not s.is_writable(k):
                raise ShortcutError(f"Réglage verrouillé par l'administrateur : {sid} {k}.")
            variants[k] = self.GLib.Variant(schema.get_key(k).get_value_type().dup_string(), v)
        s.delay()
        for k, var in variants.items():
            s.set_value(k, var)
        s.apply()
        self.Gio.Settings.sync()

    def reset(self, sid, keys, path=None):
        s, schema = self._settings(sid, path, fresh=True)
        s.delay()
        for k in keys:
            if schema.has_key(k):
                s.reset(k)
        s.apply()
        self.Gio.Settings.sync()

    def summary(self, sid, key):
        schema = self._schema(sid)
        if schema is None or not schema.has_key(key):
            return ""
        return schema.get_key(key).get_summary() or ""

    def watch(self, callback):
        """Rappelle `callback()` quand la liste des raccourcis personnalisés change
        (boucle GLib nécessaire)."""
        s, _ = self._settings(MEDIA_KEYS, None, fresh=True)
        handler = s.connect(f"changed::{CUSTOM_KEY}", lambda *_: callback())
        s.get_value(CUSTOM_KEY)  # GSettings n'annonce que les clés déjà lues
        self._next += 1
        self._watchers[self._next] = (s, handler)
        return self._next

    def unwatch(self, token):
        s, handler = self._watchers.pop(token, (None, None))
        if s is not None:
            s.disconnect(handler)

    def sync(self):
        self.Gio.Settings.sync()


def default_backend():
    """Moteur des vrais réglages (lève ShortcutError sans PyGObject)."""
    return GioBackend()


def _b(backend):
    return backend if backend is not None else default_backend()


def installed_schemas_available():
    """Schémas GNOME des raccourcis installés sur ce système (pour sauter des tests)."""
    try:
        from gi.repository import Gio
        source = Gio.SettingsSchemaSource.get_default()
        return bool(source and source.lookup(MEDIA_KEYS, True)
                    and source.lookup("org.gnome.desktop.wm.keybindings", True))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------
# Prise en charge du bureau
# --------------------------------------------------------------------------

@dataclass
class Support:
    ok: bool
    message: str = ""
    desktop: str = ""


def supported(backend=None, environ=None):
    """GNOME présent et schémas des raccourcis personnalisés installés ? Sinon un
    message clair (autre bureau : créer les raccourcis à la main)."""
    env = os.environ if environ is None else environ
    desktop = env.get("XDG_CURRENT_DESKTOP", "") or ""
    names = [n.strip().lower() for n in desktop.split(":") if n.strip()]
    if names and "gnome" not in names:
        return Support(False, f"Raccourcis globaux pris en charge seulement sous GNOME "
                              f"(bureau actuel : {desktop}). Ailleurs, crée-les dans les réglages "
                              f"du clavier de ton bureau avec les commandes de CCS.", desktop)
    try:
        b = _b(backend)
    except ShortcutError as e:
        return Support(False, str(e), desktop)
    if not (b.has_schema(MEDIA_KEYS) and CUSTOM_KEY in b.keys(MEDIA_KEYS)
            and b.has_schema(CUSTOM_SCHEMA)):
        return Support(False, f"Schémas GNOME des raccourcis personnalisés introuvables ({MEDIA_KEYS}, "
                              f"paquet gnome-settings-daemon-common).", desktop)
    return Support(True, "", desktop)


def _ready(backend):
    b = _b(backend)
    s = supported(b)
    if not s.ok:
        raise ShortcutError(s.message)
    return b


# --------------------------------------------------------------------------
# Lecture de l'état et conflits
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Conflict:
    kind: str          # « bureau », « personnalisé » ou « ccs »
    name: str          # résumé du réglage, nom du raccourci personnalisé ou de l'action
    binding: str       # valeur trouvée, telle quelle
    schema: str = None
    key: str = None
    path: str = None

    def describe(self):
        if self.kind == "bureau":
            return f"{self.name} (raccourci du bureau)"
        if self.kind == "ccs":
            return f"{self.name} (CCS)"
        return f"« {self.name} » (raccourci personnalisé)"


# Noms français des raccourcis courants du bureau (les résumés des schémas sont en anglais).
DESKTOP_NAMES = {
    "screenreader": "Lecteur d'écran", "magnifier": "Loupe", "magnifier-zoom-in": "Loupe : zoom avant",
    "magnifier-zoom-out": "Loupe : zoom arrière", "terminal": "Lancer un terminal",
    "screensaver": "Verrouiller l'écran", "logout": "Se déconnecter", "help": "Aide",
    "home": "Dossier personnel", "www": "Navigateur", "email": "Courriel", "calculator": "Calculatrice",
    "search": "Recherche", "control-center": "Paramètres", "rotate-video-lock-static": "Verrou de rotation",
    "close": "Fermer la fenêtre", "minimize": "Réduire la fenêtre", "maximize": "Agrandir la fenêtre",
    "toggle-maximized": "Agrandir / restaurer", "show-desktop": "Afficher le bureau",
    "switch-applications": "Changer d'application", "switch-windows": "Changer de fenêtre",
    "switch-input-source": "Changer de disposition du clavier", "activate-window-menu": "Menu de la fenêtre",
    "panel-run-dialog": "Exécuter une commande", "switch-to-workspace-left": "Espace de travail à gauche",
    "switch-to-workspace-right": "Espace de travail à droite", "toggle-message-tray": "Notifications",
    "toggle-quick-settings": "Réglages rapides", "toggle-application-view": "Applications",
    "focus-active-notification": "Notification active", "screenshot": "Capture d'écran",
    "screenshot-window": "Capture de la fenêtre", "show-screenshot-ui": "Capture d'écran",
    "show-screen-recording-ui": "Enregistrement de l'écran", "switch-monitor": "Changer d'écran",
    "toggle-overview": "Vue d'ensemble", "shift-overview-up": "Vue d'ensemble : haut",
    "shift-overview-down": "Vue d'ensemble : bas", "restore-shortcuts": "Rétablir les raccourcis",
    "shortcut": "Dock : afficher les numéros",
}


def _list(b):
    return list(b.get(MEDIA_KEYS, CUSTOM_KEY) or [])


def _entries(b):
    """(Binding, origine) de tous les raccourcis du bureau ; une clé illisible est sautée."""
    out = []
    for sid in KEYBINDING_SCHEMAS:
        if not b.has_schema(sid):
            continue
        for key in sorted(b.keys(sid)):
            if (sid == MEDIA_KEYS and key == CUSTOM_KEY) or key.endswith("-text"):
                continue  # liste de chemins ; texte affiché d'un raccourci (Dock)
            try:
                value = b.get(sid, key)
            except Exception:  # noqa: BLE001
                continue
            values = [value] if isinstance(value, str) else value if isinstance(value, (list, tuple)) else ()
            for v in values:
                parsed = _loose(v) if isinstance(v, str) and v else None
                if parsed:
                    out.append((parsed, ("bureau", sid, key, v, None)))
    try:
        paths = _list(b)
    except Exception:  # noqa: BLE001
        paths = []
    for p in dict.fromkeys(paths):
        try:
            v = b.get(CUSTOM_SCHEMA, "binding", p)
        except Exception:  # noqa: BLE001
            continue
        parsed = _loose(v) if isinstance(v, str) and v else None
        if parsed:
            out.append((parsed, ("ccs" if is_ours(p) else "personnalisé", None, None, v, p)))
    return out


def _conflict(b, origin):
    kind, sid, key, value, path = origin
    if kind == "bureau":
        try:
            name = DESKTOP_NAMES.get(key) or b.summary(sid, key) or key
        except Exception:  # noqa: BLE001
            name = key
        return Conflict(kind, name, value, schema=sid, key=key)
    if kind == "ccs" and _id_of(path) in _BY_ID:
        return Conflict(kind, _BY_ID[_id_of(path)].label, value, path=path)
    try:
        name = b.get(CUSTOM_SCHEMA, "name", path) or path
    except Exception:  # noqa: BLE001
        name = path
    return Conflict(kind, name, value, path=path)


def _match(b, entries, binding, skip_path=None):
    target = _loose(binding) if binding else None
    if target is None:
        return []
    found = {}
    for parsed, origin in entries:
        if parsed == target and not (skip_path and origin[4] == skip_path):
            c = _conflict(b, origin)
            found.setdefault((c.kind, c.name, c.path), c)
    return list(found.values())


def conflicts(binding, exclude=None, backend=None):
    """Raccourcis du bureau (GNOME, Dock, tuilage), personnalisés ou d'une autre action
    de CCS qui utilisent déjà `binding` ; `exclude` : identifiant de l'action à ignorer."""
    if not binding or _loose(binding) is None:
        return []
    b = _b(backend)
    skip = action(exclude).path if exclude else None
    return _match(b, _entries(b), binding, skip)


@dataclass
class Item:
    action: Action
    installed: bool
    binding: str                    # raccourci en place, sinon celui par défaut
    command: str                    # commande attendue (chemins absolus)
    installed_command: str = None   # commande en place
    conflicts: list = field(default_factory=list)

    @property
    def id(self):
        return self.action.id

    @property
    def label(self):
        return self.action.label

    @property
    def binding_label(self):
        return label(self.binding)

    @property
    def outdated(self):
        """Installé avec une autre commande (dépôt déplacé, paquet installé depuis…)."""
        return self.installed and self.installed_command != self.command


@dataclass
class Status:
    support: Support
    items: list

    def item(self, action_id):
        return next(i for i in self.items if i.id == action_id)

    @property
    def installed(self):
        return [i for i in self.items if i.installed]


def _item(b, act, paths=None, entries=None):
    paths = _list(b) if paths is None else paths
    installed = act.path in paths
    if installed:
        binding = b.get(CUSTOM_SCHEMA, "binding", act.path) or ""
        cmd = b.get(CUSTOM_SCHEMA, "command", act.path)
    else:
        binding, cmd = act.default, None
    entries = _entries(b) if entries is None else entries
    return Item(act, installed, binding, command_for(act), cmd, _match(b, entries, binding, act.path))


def status(backend=None):
    """État de chaque action (installée, raccourci, commande, conflits)."""
    try:
        b = _b(backend)
    except ShortcutError as e:
        return Status(Support(False, str(e), os.environ.get("XDG_CURRENT_DESKTOP", "")), [])
    sup = supported(b)
    if not sup.ok:
        return Status(sup, [])
    paths, entries = _list(b), _entries(b)
    return Status(sup, [_item(b, a, paths, entries) for a in ACTIONS])


# --------------------------------------------------------------------------
# Écritures
# --------------------------------------------------------------------------

def install(action_id, binding=None, backend=None):
    """Installe (ou met à jour) le raccourci d'une action. `binding` : raccourci voulu,
    sinon celui en place, sinon celui par défaut. Les conflits n'empêchent rien : ils
    sont renvoyés dans l'Item. Lève ShortcutError (raccourci invalide, bureau non pris
    en charge) avant toute écriture."""
    act = action(action_id)
    accel = parse_binding(binding).accel if binding is not None else None
    b = _ready(backend)
    if accel is None:
        current = b.get(CUSTOM_SCHEMA, "binding", act.path) if act.path in _list(b) else ""
        accel = current or act.default
    b.set(CUSTOM_SCHEMA, {"name": act.title, "command": command_for(act), "binding": accel}, act.path)
    paths = _list(b)  # relue juste avant d'écrire : rien d'ajouté entre-temps n'est perdu
    if act.path not in paths:
        b.set(MEDIA_KEYS, {CUSTOM_KEY: paths + [act.path]})
    return _item(b, act)


def _remove_paths(b, targets):
    current = _list(b)
    gone = list(dict.fromkeys(p for p in current if p in targets))
    if not gone:
        return []
    b.set(MEDIA_KEYS, {CUSTOM_KEY: [p for p in current if p not in targets]})
    for p in gone:  # après le retrait de la liste : le bureau a déjà oublié le raccourci
        b.reset(CUSTOM_SCHEMA, CUSTOM_FIELDS, p)
    return gone


def remove(action_id, backend=None):
    """Retire le raccourci d'une action ; True s'il était installé."""
    act = action(action_id)
    return bool(_remove_paths(_ready(backend), {act.path}))


def remove_all(backend=None):
    """Retire tous les raccourcis de CCS (actions d'anciennes versions comprises), jamais
    les autres ; renvoie leurs identifiants dans l'ordre de la liste."""
    b = _ready(backend)
    ours = {p for p in _list(b) if is_ours(p)}
    return [_id_of(p) for p in _remove_paths(b, ours)]


def set_binding(action_id, binding, backend=None):
    """Change le raccourci d'une action ; l'installe si elle ne l'était pas."""
    act = action(action_id)
    accel = parse_binding(binding).accel
    b = _ready(backend)
    if act.path not in _list(b):
        return install(act, accel, backend=b)
    b.set(CUSTOM_SCHEMA, {"binding": accel}, act.path)
    return _item(b, act)


def update_commands(backend=None):
    """Réécrit la commande des raccourcis installés qui ne pointent plus au bon endroit
    (paquet installé depuis, dépôt déplacé) ; renvoie les actions mises à jour."""
    b = _ready(backend)
    paths, done = _list(b), []
    for act in ACTIONS:
        if act.path in paths:
            expected = command_for(act)
            if b.get(CUSTOM_SCHEMA, "command", act.path) != expected:
                b.set(CUSTOM_SCHEMA, {"command": expected}, act.path)
                done.append(act.id)
    return done


# --------------------------------------------------------------------------
# Texte de « ccs raccourcis »
# --------------------------------------------------------------------------

USAGE = (
    "usage : ccs raccourcis [status]                   état des raccourcis clavier globaux\n"
    "        ccs raccourcis on [action…]               active (toutes par défaut)\n"
    "        ccs raccourcis off [action…]              retire (toutes celles de CCS par défaut)\n"
    "        ccs raccourcis set <action> <raccourci>   ex. ccs raccourcis set suivant Super+Alt+B\n"
    f"actions : {', '.join(ACTION_IDS)}"
)


def _line(item, width):
    if item.installed:
        glyph = "⚠" if item.conflicts else "✔"
    else:
        glyph = "·"
    notes = []
    if not item.installed:
        notes.append("(désactivé)")
    if item.conflicts:
        notes.append("déjà pris : " + ", ".join(c.describe() for c in item.conflicts))
    if item.outdated:
        notes.append(f"commande à mettre à jour : ccs raccourcis on {item.id}")
    text = f"  {glyph} {item.label.ljust(width)}  {item.binding_label}"
    return text + ("  " + " — ".join(notes) if notes else "")


def format_text(st):
    """Texte de `ccs raccourcis status`."""
    if not st.support.ok:
        width = max(len(a.label) for a in ACTIONS)
        lines = [f"Raccourcis clavier globaux : {st.support.message}", "",
                 "Commandes à associer à un raccourci dans les réglages du clavier :"]
        lines += [f"  {a.label.ljust(width)}  {command_for(a)}" for a in ACTIONS]
        return "\n".join(lines) + "\n"
    width = max(len(i.label) for i in st.items)
    lines = ["Raccourcis clavier globaux (bureau GNOME, même application fermée)", ""]
    lines += [_line(i, width) for i in st.items]
    lines += ["",
              "Activer : ccs raccourcis on [action…] · retirer : ccs raccourcis off [action…]",
              "Changer : ccs raccourcis set <action> <raccourci> (ex. Super+Alt+C)",
              f"Actions : {', '.join(ACTION_IDS)}"]
    return "\n".join(lines) + "\n"


def command(args=(), backend=None):
    """`ccs raccourcis [status|on|off|set]` → (code de sortie, texte). 2 : usage,
    1 : bureau non pris en charge ou raccourci refusé."""
    args = list(args or [])
    sub = args[0] if args else "status"
    rest = args[1:]
    try:
        if sub in ("status", "etat", "état") and not rest:
            st = status(backend)
            return (0 if st.support.ok else 1), format_text(st)
        if sub in ("on", "off"):
            unknown = [x for x in rest if x not in _BY_ID]
            if unknown:
                return 2, f"Action inconnue : {', '.join(unknown)}.\n{USAGE}\n"
            b = _ready(backend)
            if sub == "on":
                items = [install(i, backend=b) for i in (rest or ACTION_IDS)]
                width = max(len(i.label) for i in items)
                return 0, "Raccourcis activés :\n" + "\n".join(_line(i, width) for i in items) + "\n"
            removed = remove_all(backend=b) if not rest else [i for i in rest if remove(i, backend=b)]
            if not removed:
                return 0, "Aucun raccourci de CCS installé : rien à retirer.\n"
            names = [_BY_ID[i].label if i in _BY_ID else i for i in removed]
            return 0, f"Raccourcis retirés : {', '.join(names)}.\n"
        if sub == "set":
            if len(rest) != 2:
                return 2, USAGE + "\n"
            item = set_binding(rest[0], rest[1], backend=backend)
            return 0, "Raccourci enregistré :\n" + _line(item, len(item.label)) + "\n"
    except ShortcutError as e:
        return 1, f"{e}\n"
    return 2, USAGE + "\n"
