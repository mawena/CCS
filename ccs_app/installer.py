"""Mise à jour en un clic : télécharge le .deb de la release GitHub, le vérifie, l'installe.

Logique sans GTK ; réseau (`opener`), exécution de commandes (`run`) et progression
(`progress`) sont injectables. Sécurité : seules les URL de téléchargement du dépôt
mawena/CCS sont acceptées (redirections vers les hôtes de stockage GitHub comprises),
la somme SHA-256 est vérifiée contre `SHA256SUMS`, puis `dpkg-deb -f` doit confirmer
`Package: ccs` et la version annoncée, plus récente que l'installée. Toute erreur laisse
le système intact et nettoie le dossier temporaire (privé, 0700), sauf quand on propose la
commande `sudo apt install` à copier : le paquet vérifié reste alors disponible.
"""

import hashlib
import http.client
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__, updates

REPO = "mawena/CCS"
API_RELEASES = f"https://api.github.com/repos/{REPO}/releases"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
API_ASSET_PREFIX = f"https://api.github.com/repos/{REPO}/releases/assets/"
# Hôtes vers lesquels GitHub redirige les téléchargements de pièces jointes.
REDIRECT_HOSTS = ("objects.githubusercontent.com", "release-assets.githubusercontent.com")
USER_AGENT = "ccs"
TIMEOUT_S = 20
MAX_JSON = 1 << 20
MAX_SUMS = 1 << 16
MAX_DEB = 64 << 20
CHUNK = 1 << 16

PHASES = ("download", "verify", "install")


class InstallError(Exception):
    """Échec clair, rien d'installé. `fallback` : commande à copier, si elle aide."""

    def __init__(self, message, fallback=None):
        super().__init__(message)
        self.fallback = fallback


@dataclass
class Plan:
    version: str
    notes: str
    deb_name: str
    deb_url: str
    sums_url: str


@dataclass
class Result:
    ok: bool
    version: str
    message: str
    fallback: str = None


# --------------------------------------------------------------------------
# Réseau : liste blanche d'URL
# --------------------------------------------------------------------------

def allowed_url(url, version=None):
    """Vrai pour une pièce jointe de ce dépôt (page de téléchargement de la version
    annoncée, ou URL d'API des pièces jointes), en https, sans caractère douteux."""
    if not isinstance(url, str) or not url.isprintable() or " " in url or "\\" in url:
        return False
    if url.startswith(API_ASSET_PREFIX):
        return url[len(API_ASSET_PREFIX):].isdigit()
    base = f"{DOWNLOAD_PREFIX}v{version}/"
    if version is None or not url.startswith(base):
        return False
    rest = url[len(base):]
    return bool(rest) and not any(c in rest for c in "/?#%") and rest != ".."


def allowed_redirect(url):
    p = urllib.parse.urlsplit(url)
    return p.scheme == "https" and p.hostname in REDIRECT_HOSTS and p.port in (None, 443)


def _version_of(url):
    m = re.search(r"/releases/download/v([^/]+)/", url or "")
    return m.group(1) if m else None


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Une redirection ne mène qu'au dépôt ou au stockage des pièces jointes de GitHub."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not (allowed_redirect(newurl) or allowed_url(newurl, _version_of(req.full_url))
                or allowed_url(newurl)):
            raise urllib.error.URLError(f"redirection refusée : {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_opener(req, timeout=TIMEOUT_S):
    return urllib.request.build_opener(_Redirects).open(req, timeout=timeout)


def _request(url, accept=None):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                "Accept": accept or "*/*"})


def _network_error(e):
    if isinstance(e, urllib.error.HTTPError):
        return InstallError(f"GitHub a répondu HTTP {e.code}.")
    if isinstance(e, urllib.error.URLError):
        return InstallError(f"Réseau indisponible : {e.reason}.")
    return InstallError(f"Réseau indisponible : {e}.")


_NET = (OSError, http.client.HTTPException)


def fetch_json(url, opener=None):
    opener = opener or default_opener
    try:
        with opener(_request(url, "application/vnd.github+json"), timeout=TIMEOUT_S) as r:
            return json.loads(r.read(MAX_JSON))
    except ValueError as e:
        raise InstallError("Réponse de GitHub illisible.") from e
    except _NET as e:
        raise _network_error(e) from e


def download(url, dest, limit, opener=None, progress=None):
    """Télécharge `url` dans `dest` (au plus `limit` octets). progress(fait, total|None)."""
    if not (allowed_url(url, _version_of(url))):
        raise InstallError("Adresse de téléchargement refusée : elle ne vient pas du dépôt "
                           f"{REPO}.")
    opener = opener or default_opener
    total = None
    done = 0
    try:
        with opener(_request(url, "application/octet-stream"), timeout=TIMEOUT_S) as r:
            try:
                total = int(r.headers.get("Content-Length")) if r.headers else None
            except (TypeError, ValueError, AttributeError):
                total = None
            if total is not None and total > limit:
                raise InstallError("Fichier annoncé trop volumineux, téléchargement refusé.")
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > limit:
                        raise InstallError("Fichier trop volumineux, téléchargement interrompu.")
                    out.write(chunk)
                    if progress:
                        progress(done, total)
    except _NET as e:
        raise _network_error(e) from e
    if total is not None and done != total:
        raise InstallError("Téléchargement incomplet.")


# --------------------------------------------------------------------------
# Release et pièces jointes
# --------------------------------------------------------------------------

def deb_name(version):
    return f"ccs_{version}_all.deb"


def _asset_url(asset, version):
    for key in ("browser_download_url", "url"):
        if allowed_url(asset.get(key), version):
            return asset[key]
    return None


def plan_from_release(data):
    """Plan d'installation d'après la réponse de l'API, ou InstallError."""
    release = updates.parse_release(data)
    if release is None:
        raise InstallError("Aucune version publiée lisible sur GitHub.")
    v = release.version
    assets = data.get("assets")
    by_name = {}
    for a in assets if isinstance(assets, list) else []:
        if isinstance(a, dict) and isinstance(a.get("name"), str):
            by_name.setdefault(a["name"], a)
    deb, sums = by_name.get(deb_name(v)), by_name.get("SHA256SUMS")
    if deb is None or sums is None:
        raise InstallError(f"La version {v} n'a pas de pièce jointe {deb_name(v)} et SHA256SUMS.")
    deb_url, sums_url = _asset_url(deb, v), _asset_url(sums, v)
    if deb_url is None or sums_url is None:
        raise InstallError("Adresse de téléchargement refusée : elle ne vient pas du dépôt "
                           f"{REPO}.")
    notes = data.get("body") if isinstance(data.get("body"), str) else ""
    return Plan(v, notes, deb_name(v), deb_url, sums_url)


def fetch_plan(version=None, opener=None):
    """Dernière release, ou celle de `version` (tag annoncé)."""
    if version is None:
        url = f"{API_RELEASES}/latest"
    else:
        if updates.parse_version(version) is None:
            raise InstallError(f"Version illisible : {version}")
        url = f"{API_RELEASES}/tags/v{version.strip().lstrip('vV')}"
    return plan_from_release(fetch_json(url, opener))


# --------------------------------------------------------------------------
# Vérifications
# --------------------------------------------------------------------------

def parse_sums(text):
    """{nom: somme} d'un fichier `sha256sum` (« <hex>  <nom> » ou « <hex> *<nom> »)."""
    sums = {}
    for line in text.splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{64}) [ *]?(\S.*)", line.strip("\r\n"))
        if m:
            sums[os.path.basename(m.group(2).strip())] = m.group(1).lower()
    return sums


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sum(deb_path, sums_text, name):
    expected = parse_sums(sums_text).get(name)
    if expected is None:
        raise InstallError(f"SHA256SUMS ne contient pas {name} : paquet refusé.")
    if sha256_file(deb_path) != expected:
        raise InstallError("La somme SHA-256 du paquet ne correspond pas : fichier refusé.")


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def check_package(path, version, current, run=None):
    """`dpkg-deb -f` : Package = ccs, Version = annoncée, plus récente que l'installée."""
    rc, out = (run or _run)(["dpkg-deb", "-f", str(path), "Package", "Version"])
    if rc != 0:
        raise InstallError("Le fichier téléchargé n'est pas un paquet Debian lisible.")
    fields = {}
    for line in out.splitlines():
        k, sep, v = line.partition(":")
        if sep:
            fields[k.strip()] = v.strip()
    if fields.get("Package") != "ccs":
        raise InstallError("Le paquet téléchargé n'est pas « ccs » : refusé.")
    if fields.get("Version") != version:
        raise InstallError(f"Le paquet est en version {fields.get('Version')}, "
                           f"pas {version} : refusé.")
    if not updates.is_newer(version, current):
        raise InstallError(f"La version {version} n'est pas plus récente que {current}.")


def is_package_install(run=None, path=None):
    """Vrai si ce code vient du paquet dpkg (sinon : copie de développement, mise à jour
    par git)."""
    path = str(path or Path(__file__).resolve())
    rc, out = (run or _run)(["dpkg", "-S", path])
    return rc == 0 and out.startswith("ccs:")


def install_command(deb_path):
    """Commande d'installation avec mot de passe (fenêtre polkit)."""
    return ["pkexec", "apt-get", "install", "-y", str(Path(deb_path).resolve())]


def manual_command(deb_path):
    return f"sudo apt install {shlex.quote(str(Path(deb_path).resolve()))}"


def _install(deb_path, run):
    manual = manual_command(deb_path)
    rc, out = run(install_command(deb_path))
    if rc is None:
        raise InstallError("pkexec est introuvable : installe le paquet avec la commande "
                           "ci-dessous.", fallback=manual)
    if rc in (126, 127):
        raise InstallError("Mot de passe refusé ou fenêtre fermée : rien n'a été installé. "
                           "Tu peux installer avec la commande ci-dessous.", fallback=manual)
    if rc != 0:
        tail = " ".join(out.strip().splitlines()[-2:])[:300]
        raise InstallError(f"L'installation a échoué (code {rc}). {tail}".strip())


# --------------------------------------------------------------------------
# Enchaînement
# --------------------------------------------------------------------------

def install(plan=None, current=None, opener=None, run=None, progress=None, tmp_root=None):
    """Télécharge, vérifie et installe. Renvoie un Result ; lève InstallError.
    progress(phase, fraction|None) avec phase dans PHASES."""
    current = current or __version__
    run = run or _run
    note = progress or (lambda *_: None)
    if plan is None:
        plan = fetch_plan(opener=opener)
    if not updates.is_newer(plan.version, current):
        return Result(True, current, f"CCS {current} est déjà à jour.")
    tmp = tempfile.mkdtemp(prefix="ccs-maj-", dir=tmp_root)
    os.chmod(tmp, 0o700)
    keep = False
    try:
        deb = os.path.join(tmp, plan.deb_name)
        sums = os.path.join(tmp, "SHA256SUMS")
        note("download", 0.0)
        download(plan.sums_url, sums, MAX_SUMS, opener)
        download(plan.deb_url, deb, MAX_DEB, opener,
                 lambda done, total: note("download", done / total if total else None))
        note("download", 1.0)
        note("verify", None)
        try:
            text = Path(sums).read_text(encoding="utf-8")
        except (OSError, ValueError) as e:
            raise InstallError("SHA256SUMS illisible.") from e
        verify_sum(deb, text, plan.deb_name)
        check_package(deb, plan.version, current, run)
        note("install", None)
        try:
            _install(deb, run)
        except InstallError as e:
            keep = e.fallback is not None  # le paquet vérifié reste pour la commande manuelle
            raise
        return Result(True, plan.version, f"CCS {plan.version} est installé.")
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# Sous-commande « ccs mise-a-jour »
# --------------------------------------------------------------------------

USAGE = """usage : ccs mise-a-jour [--verifier]

Installe la dernière version de CCS publiée sur GitHub (téléchargement, vérification
SHA-256 et du paquet, puis installation après mot de passe).
  --verifier   indique seulement s'il y a une nouvelle version, sans rien installer"""


def command(args, opener=None, run=None, out=print, current=None):
    """(code, texte) de `ccs mise-a-jour [--verifier]`. Code 0 : à jour / installé /
    nouvelle version signalée ; 1 : échec ; 2 : usage. `out(ligne)` reçoit la progression."""
    args = list(args)
    if args in (["-h"], ["--help"], ["--aide"]):
        return 0, USAGE
    if args not in ([], ["--verifier"]):
        return 2, USAGE
    current = current or __version__
    if not is_package_install(run):
        return 1, "Copie de développement : mise à jour par git."
    try:
        plan = fetch_plan(opener=opener)
        if not updates.is_newer(plan.version, current):
            return 0, f"CCS {current} est à jour."
        if args:
            return 0, f"CCS {plan.version} est disponible (installée : {current})."
        labels = {"download": "Téléchargement…", "verify": "Vérification…",
                  "install": "Installation (mot de passe demandé)…"}
        seen = []

        def progress(phase, _fraction):
            if phase not in seen:
                seen.append(phase)
                out(labels[phase])
        result = install(plan, current, opener, run, progress)
    except InstallError as e:
        return 1, str(e) + (f"\n  {e.fallback}" if e.fallback else "")
    return 0, result.message


# --------------------------------------------------------------------------
# Notes de version
# --------------------------------------------------------------------------

def plain_notes(markdown):
    """Corps Markdown de la release en texte lisible (sans balisage)."""
    lines = []
    for raw in (markdown or "").replace("\r", "").splitlines():
        line = raw.rstrip()
        if re.match(r"\s*(```.*|---+|\*\*\*+)$", line):
            continue
        m = re.match(r"\s{0,3}#{1,6}\s+(.*)", line)
        if m:
            if lines and lines[-1] != "":
                lines.append("")
            line = m.group(1).strip()
        line = re.sub(r"^(\s*)[-*+]\s+(\[[ xX]\]\s+)?", lambda g: f"{g.group(1)}• ", line)
        line = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]*)\)", r"\1 (\2)", line)
        line = re.sub(r"(\*\*|__)(.+?)\1", r"\2", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        if line == "" and lines and lines[-1] == "":
            continue
        lines.append(line)
    return "\n".join(lines).strip()


# ---- version déjà en mémoire ----------------------------------------------------------------

def code_stamp(root=None):
    """Empreinte du code de CCS sur le disque (date de modification la plus récente des .py du
    paquet et de `gui/`) ; elle change quand un nouveau paquet remplace les fichiers. None si
    le dossier est illisible. Sert à proposer de relancer une application ouverte avant."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    stamps = []
    for folder in (root, root / "gui"):
        try:
            stamps += [e.stat().st_mtime for e in os.scandir(folder)
                       if e.name.endswith(".py") and e.is_file()]
        except OSError:
            continue
    return max(stamps) if stamps else None
