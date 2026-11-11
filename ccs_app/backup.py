"""Sauvegarde chiffrée des comptes et des réglages (`ccs sauvegarde`, `ccs restaurer`).

Contenu, déduit du code de CCS :

- les profils du dossier de comptes (`core.paths().store`) : `oauth.json` (jetons
  compris) et `account.json` de chaque dossier qui en a un ;
- les réglages (`settings.json`), les comptes par projet (`projects.json`) et les
  budgets (`budgets.json`), s'ils existent ;
- la configuration des raccourcis clavier (actions installées et leur combinaison,
  lues par `shortcuts.status`, car elle vit dans les réglages du bureau).

Jamais : états passagers (`state.json`, `pause.json`, `quiet*.json`, `terminals.json`,
`switch-origin.json`, `updates.json`, `limits/`), caches (`usage.json`,
`conversations-*.json`), journaux (`history.db`), verrous, ni les conversations.

L'archive est un tar construit en mémoire, chiffré par
`gpg --symmetric --cipher-algo AES256` : la phrase de passe est saisie dans la fenêtre de
gpg (pinentry), jamais passée en argument ni en variable d'environnement. Le fichier est
créé en 600 puis posé atomiquement. La restauration n'écrit que dans le dossier de comptes
(écriture atomique en 600, sous le verrou) : ni le compte actif ni
`~/.claude/.credentials.json` ne changent.

API : BackupError, default_name(), collect(), create(), open_backup(), Backup
(`contents`, `conflicts()`, `restore()`), restore(), describe(), command() (`ccs
sauvegarde` / `ccs restaurer`).
"""

import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import core, project_accounts, settings, shortcuts

FORMAT = 1
MANIFEST = "MANIFEST.json"
SHORTCUTS = "raccourcis.json"
PROFILE_FILES = ("oauth.json", "account.json")
# Fichiers du dossier de comptes sauvegardés tels quels (noms relatifs au dossier).
STORE_FILES = (settings.settings_path().name, project_accounts.path().name, "budgets.json")
SUFFIX = ".gpg"

MAX_MEMBER = 4 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MEMBER_RE = re.compile(r"^profils/(?!\.{1,2}/)([A-Za-z0-9._-]+)/(oauth|account)\.json$")

USAGE = (
    "usage : ccs sauvegarde [fichier]          sauvegarde chiffrée (gpg) des comptes et réglages\n"
    "        ccs restaurer <fichier> [--oui]   restaure une sauvegarde (--oui : sans confirmation)"
)


class BackupError(Exception):
    """Sauvegarde ou restauration impossible (message affichable, en français)."""


# --------------------------------------------------------------------------
# gpg
# --------------------------------------------------------------------------

# Point d'injection des tests : {"home": GNUPGHOME temporaire, "passphrase": "…"}. En
# production il reste None : gpg demande la phrase de passe dans sa fenêtre (pinentry).
_TEST_GPG = None


def _gpg_error(stderr, decrypting):
    text = stderr.decode(errors="replace")
    low = text.lower()
    if "bad_passphrase" in low or "bad session key" in low:
        return "Mauvaise phrase de passe."
    if "cancel" in low or " 99" in low or "annul" in low:
        return "Saisie de la phrase de passe annulée."
    if decrypting and ("nodata" in low or "decryption_failed" in low or "no valid openpgp" in low
                       or "aucune donnée" in low):
        return "Fichier illisible : ce n'est pas une sauvegarde de CCS, ou il est abîmé."
    detail = " ".join(l[len("gpg: "):] if l.startswith("gpg: ") else l
                      for l in text.splitlines() if l and not l.startswith("[GNUPG:]"))
    return "gpg a échoué" + (f" : {detail[:300]}" if detail else ".")


def _run_gpg(args, data=None):
    """Lance gpg ; renvoie la sortie standard. Lève BackupError (gpg absent, échec)."""
    cmd = ["gpg", "--status-fd", "2", *args]
    env = dict(os.environ)
    pass_fds, fd_r = (), None
    if _TEST_GPG:
        fd_r, fd_w = os.pipe()
        os.write(fd_w, _TEST_GPG["passphrase"].encode())
        os.close(fd_w)
        pass_fds = (fd_r,)
        cmd[1:1] = ["--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase-fd", str(fd_r)]
        env["GNUPGHOME"] = str(_TEST_GPG["home"])
    try:
        r = subprocess.run(cmd, input=data, capture_output=True, env=env, pass_fds=pass_fds)
    except FileNotFoundError:
        raise BackupError("gpg est introuvable : installe-le avec « sudo apt install gnupg ».") from None
    except OSError as e:
        raise BackupError(f"Impossible de lancer gpg : {e.strerror or e}.") from e
    finally:
        if fd_r is not None:
            os.close(fd_r)
    if r.returncode != 0:
        raise BackupError(_gpg_error(r.stderr, "--decrypt" in args))
    return r.stdout


def _encrypt(data, dest):
    """Chiffre `data` vers `dest` : fichier créé en 600 puis posé atomiquement."""
    dest = Path(dest)
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", suffix=".tmp", dir=dest.parent)
    os.close(fd)  # mkstemp : déjà en 600
    try:
        _run_gpg(["--yes", "--symmetric", "--cipher-algo", "AES256", "--s2k-digest-algo", "SHA512",
                  "--output", tmp], data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# Contenu
# --------------------------------------------------------------------------

def default_name(now=None):
    """Nom par défaut, daté : `ccs-sauvegarde-2026-11-11.gpg`."""
    return time.strftime("ccs-sauvegarde-%Y-%m-%d", time.localtime(now)) + SUFFIX


def _read(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def collect(backend=None):
    """Ce qui entre dans la sauvegarde : {nom dans l'archive: octets}. Rien n'est écrit."""
    store = core.paths().store
    entries = {}
    if store.is_dir():
        for d in sorted(p for p in store.iterdir() if p.is_dir() and _NAME_RE.match(p.name)
                        and p.name not in (".", "..")):
            files = {f: _read(d / f) for f in PROFILE_FILES}
            if all(v is not None for v in files.values()):
                for f, content in files.items():
                    entries[f"profils/{d.name}/{f}"] = content
        for name in STORE_FILES:
            content = _read(store / name)
            if content is not None:
                entries[f"reglages/{name}"] = content
    sc = _shortcuts_snapshot(backend)
    if sc:
        entries[SHORTCUTS] = json.dumps({"actions": sc}, indent=2, ensure_ascii=False).encode()
    return entries


def _shortcuts_snapshot(backend):
    """Actions de raccourcis installées {id: combinaison} ; vide si le bureau ne les gère pas."""
    try:
        st = shortcuts.status(backend)
        return {i.id: i.binding for i in st.items if i.installed and i.binding}
    except Exception:  # noqa: BLE001 — une lecture du bureau ratée ne bloque pas la sauvegarde
        return {}


def _manifest(entries, now=None):
    return {
        "format": FORMAT,
        "cree": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "profils": sorted({m.group(1) for n in entries if (m := _MEMBER_RE.match(n))}),
        "fichiers": sorted(n for n in entries if n.startswith("reglages/")),
        "raccourcis": SHORTCUTS in entries,
    }


def _tar(entries, manifest, now=None):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, content in [(MANIFEST, json.dumps(manifest, indent=2).encode()), *entries.items()]:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o600
            info.mtime = int(now or time.time())
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def create(dest, now=None, backend=None):
    """Crée la sauvegarde chiffrée `dest` (600) ; refuse d'écraser un fichier existant.
    Renvoie le contenu sauvegardé (`Contents`). `backend` : moteur des raccourcis (tests)."""
    dest = Path(dest)
    if dest.exists():
        raise BackupError(f"« {dest} » existe déjà : choisis un autre nom.")
    if not dest.parent.is_dir():
        raise BackupError(f"Le dossier « {dest.parent} » n'existe pas.")
    entries = collect(backend)
    if not any(_MEMBER_RE.match(n) for n in entries) and not any(n.startswith("reglages/") for n in entries):
        raise BackupError("Rien à sauvegarder : aucun profil ni réglage.")
    manifest = _manifest(entries, now)
    _encrypt(_tar(entries, manifest, now), dest)
    return _contents(entries, manifest)


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

@dataclass
class Contents:
    """Ce qu'une sauvegarde contient. Aucun jeton ici : des noms seulement."""
    created: str = ""
    profiles: list = field(default_factory=list)
    files: list = field(default_factory=list)      # réglages, comptes par projet, budgets
    shortcuts: dict = field(default_factory=dict)  # {action: combinaison}


def _contents(entries, manifest):
    sc = {}
    if SHORTCUTS in entries:
        try:
            sc = _clean_shortcuts(json.loads(entries[SHORTCUTS]).get("actions"))
        except (ValueError, AttributeError):
            sc = {}
    return Contents(
        created=str(manifest.get("cree", "")),
        profiles=sorted({m.group(1) for n in entries if (m := _MEMBER_RE.match(n))}),
        files=sorted(n.split("/", 1)[1] for n in entries if n.startswith("reglages/")),
        shortcuts=sc,
    )


def _clean_shortcuts(actions):
    if not isinstance(actions, dict):
        return {}
    return {k: v for k, v in actions.items()
            if k in shortcuts.ACTION_IDS and isinstance(v, str) and v}


def _valid_member(name):
    return (name in (MANIFEST, SHORTCUTS) or bool(_MEMBER_RE.match(name))
            or (name.startswith("reglages/") and name[len("reglages/"):] in STORE_FILES))


def _parse(data):
    """Tar déchiffré → (manifeste, {nom: octets}). Liste blanche stricte : seuls des
    fichiers ordinaires aux noms attendus sont lus, jamais extraits sur le disque."""
    entries, total = {}, 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
            for m in tar:
                if not m.isfile() or not _valid_member(m.name):
                    raise BackupError(f"Sauvegarde invalide : élément inattendu « {m.name[:80]} ».")
                total += m.size
                if m.size > MAX_MEMBER or total > MAX_TOTAL:
                    raise BackupError("Sauvegarde invalide : contenu trop gros.")
                entries[m.name] = tar.extractfile(m).read()
    except tarfile.TarError as e:
        raise BackupError("Sauvegarde illisible : l'archive est abîmée.") from e
    try:
        manifest = json.loads(entries.pop(MANIFEST))
    except (KeyError, ValueError):
        raise BackupError("Ce fichier n'est pas une sauvegarde de CCS (manifeste absent).") from None
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BackupError("Sauvegarde d'un format inconnu : mets CCS à jour.")
    for name, content in entries.items():
        if name != SHORTCUTS:
            try:
                ok = isinstance(json.loads(content), dict)
            except ValueError:
                ok = False
            if not ok:
                raise BackupError(f"Sauvegarde invalide : « {name} » n'est pas un JSON valide.")
    for name in {m.group(1) for n in entries if (m := _MEMBER_RE.match(n))}:
        if not all(f"profils/{name}/{f}" in entries for f in PROFILE_FILES):
            raise BackupError(f"Sauvegarde invalide : profil « {name} » incomplet.")
    return manifest, entries


def open_backup(path):
    """Déchiffre `path` (gpg demande la phrase de passe) et renvoie une `Backup`."""
    path = Path(path)
    if not path.is_file():
        raise BackupError(f"« {path} » est introuvable.")
    manifest, entries = _parse(_run_gpg(["--decrypt", str(path)]))
    return Backup(entries, _contents(entries, manifest))


class Backup:
    """Sauvegarde déchiffrée, en mémoire : une seule saisie de phrase de passe pour lire
    le contenu, voir ce qui serait écrasé, puis restaurer."""

    def __init__(self, entries, contents):
        self._entries = entries
        self.contents = contents

    def _targets(self):
        store = core.paths().store
        for name, content in sorted(self._entries.items()):
            if m := _MEMBER_RE.match(name):
                yield f"profil {m.group(1)}", m.group(1), store / m.group(1) / f"{m.group(2)}.json", content
            elif name.startswith("reglages/"):
                f = name.split("/", 1)[1]
                yield f, f, store / f, content

    def conflicts(self):
        """Éléments existants que la restauration écraserait (contenu différent) : noms de
        profils et de fichiers de réglages. Les profils sont listés une fois."""
        out = []
        for _label, key, path, content in self._targets():
            existing = _read(path)
            if existing is not None and existing != content and key not in out:
                out.append(key)
        return out

    def restore(self, confirm=None, assume_yes=False, backend=None, with_shortcuts=True):
        """Écrit les profils et fichiers dans le dossier de comptes (atomique, 600, sous le
        verrou). Si quelque chose serait écrasé : `assume_yes` ou `confirm(liste) -> bool`
        (sans l'un ni l'autre : refus). Les raccourcis sont réinstallés par `shortcuts`
        (`backend` injectable). Renvoie un `Restored`, ou lève BackupError."""
        over = self.conflicts()
        if over and not assume_yes and not (confirm and confirm(over)):
            raise BackupError("Restauration annulée : rien n'a été écrasé.")
        written = []
        with core.store_lock():
            for _label, _key, path, content in self._targets():
                _write_atomic(path, content)
                written.append(str(path.relative_to(core.paths().store)))
        applied, note = [], ""
        if with_shortcuts and self.contents.shortcuts:
            applied, note = _apply_shortcuts(self.contents.shortcuts, backend)
        return Restored(profiles=list(self.contents.profiles), files=list(self.contents.files),
                        overwritten=over, shortcuts=applied, note=note)


@dataclass
class Restored:
    profiles: list
    files: list
    overwritten: list
    shortcuts: list = field(default_factory=list)
    note: str = ""


def _write_atomic(path, content):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _apply_shortcuts(actions, backend):
    try:
        sup = shortcuts.supported(backend)
    except Exception as e:  # noqa: BLE001
        return [], f"raccourcis non restaurés ({e})"
    if not sup.ok:
        return [], "raccourcis non restaurés : bureau non pris en charge"
    done = []
    for act_id, binding in actions.items():
        try:
            shortcuts.install(act_id, binding, backend=backend)
            done.append(act_id)
        except Exception:  # noqa: BLE001 — un raccourci invalide ne bloque pas les autres
            continue
    return done, ""


def restore(path, confirm=None, assume_yes=False, backend=None, with_shortcuts=True):
    """Déchiffre `path` puis restaure (voir `Backup.restore`)."""
    return open_backup(path).restore(confirm, assume_yes, backend, with_shortcuts)


# --------------------------------------------------------------------------
# Textes
# --------------------------------------------------------------------------

def describe(contents):
    """Contenu lisible d'une sauvegarde, sans jeton : profils, fichiers, raccourcis."""
    lines = []
    if contents.created:
        lines.append(f"Sauvegarde du {contents.created.replace('T', ' à ')}")
    lines.append("Profils : " + (", ".join(contents.profiles) or "aucun"))
    lines.append("Fichiers : " + (", ".join(contents.files) or "aucun"))
    if contents.shortcuts:
        lines.append("Raccourcis : " + ", ".join(sorted(contents.shortcuts)))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------

def _ask(over):
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(f"Écraser {', '.join(over)} ? [o/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("o", "oui", "y", "yes")


def command(args, confirm=None, backend=None, out=None, err=None):
    """`ccs sauvegarde [fichier]` et `ccs restaurer <fichier> [--oui]` : la sous-commande
    est le premier argument (« sauvegarde » ou « restaurer »). Renvoie le code de sortie."""
    out, err = out or sys.stdout, err or sys.stderr
    args = list(args)
    verb = args.pop(0) if args and args[0] in ("sauvegarde", "restaurer") else "sauvegarde"
    yes = "--oui" in args
    rest = [a for a in args if a != "--oui"]
    if any(a.startswith("-") for a in rest) or (verb == "sauvegarde" and (yes or len(rest) > 1)) \
            or (verb == "restaurer" and len(rest) != 1):
        print(USAGE, file=err)
        return 2
    try:
        if verb == "sauvegarde":
            dest = Path(rest[0]) if rest else Path.cwd() / default_name()
            c = create(dest, backend=backend)
            print(f"Sauvegarde chiffrée écrite : {dest}\n{describe(c)}", file=out)
            print("Garde la phrase de passe : sans elle, la sauvegarde est perdue.", file=out)
            return 0
        b = open_backup(rest[0])
        print(describe(b.contents), file=out)
        r = b.restore(confirm or _ask, assume_yes=yes, backend=backend)
        print("Restauré : " + (", ".join(r.profiles) or "aucun profil")
              + (f" ; écrasé : {', '.join(r.overwritten)}" if r.overwritten else "") + ".", file=out)
        if r.note:
            print(r.note, file=out)
        print("Le compte actif n'a pas changé.", file=out)
        return 0
    except BackupError as e:
        print(f"ccs : {e}", file=err)
        return 1
    except OSError as e:
        print(f"ccs : {e.strerror or e}", file=err)
        return 1
