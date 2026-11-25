"""Machine « modal » de `ccs remote` : la commande tourne dans un bac à sable Modal (GPU au choix).

`ccs remote run --machine modal -- <commande>`, ou `--gpu H100` (équivaut à `--machine modal:H100`).
Réglages facultatifs dans `~/.config/ccs/machines.toml` :

    [machines.modal]
    gpu = "L4"            # carte par défaut (aucune : processeur seul)
    python = "3.12"       # python de l'image
    apt = ["git"]         # paquets Debian à ajouter à l'image
    pip = ["torch"]       # paquets python à ajouter à l'image
    timeout = 3600        # durée maximale, en secondes
    limit = 2             # commandes en même temps
    modal_python = "~/.local/opt/modal/bin/python3"   # python où `modal` est installé

Le projet part en archive (fichiers suivis par git et non ignorés, plus `--include`), la commande
tourne dans `/projet`, `--fetch` revient en archive, et le bac à sable est détruit à la fin.
"""
import json
import os
import shlex
import shutil
import signal
import subprocess
import tarfile
import tempfile
from pathlib import Path

MACHINE_ID = "modal"
RUNNER = Path(__file__).resolve().with_name("modal_runner.py")
DEFAULT_PYTHON = "~/.local/opt/modal/bin/python3"
DEFAULT_TIMEOUT = 3600
GPUS = ("T4", "L4", "A10", "A10G", "L40S", "A100", "A100-40GB", "A100-80GB", "H100", "H200", "B200")
BEST_GPU = "B200"


class ModalError(Exception):
    pass


def is_modal(machine):
    """Vrai pour `modal` et `modal:<GPU>`."""
    return bool(machine) and (machine == MACHINE_ID or machine.startswith(MACHINE_ID + ":"))


def split(machine):
    """`modal:H100` → `H100` ; `modal` → None."""
    return machine.split(":", 1)[1] if ":" in machine else None


def settings(overrides):
    conf = overrides.get(MACHINE_ID) or {}
    return conf if isinstance(conf, dict) else {}


def python_path(conf=None):
    """Python où le paquet `modal` est installé (réglage, puis l'emplacement habituel, puis le
    python du script `modal` trouvé dans le PATH)."""
    conf = conf or {}
    for candidate in (conf.get("modal_python"), DEFAULT_PYTHON):
        if isinstance(candidate, str) and candidate:
            p = Path(os.path.expanduser(candidate))
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    cli = shutil.which("modal")
    if cli:
        try:
            first = Path(cli).read_text(errors="replace").splitlines()[0]
        except (OSError, IndexError):
            first = ""
        if first.startswith("#!"):
            interp = first[2:].strip().split()[0]
            if Path(interp).is_file():
                return interp
    return None


def configured(conf=None):
    """Modal utilisable : son python et un jeton (`~/.modal.toml` ou variables d'environnement)."""
    if not python_path(conf):
        return False
    return (Path.home() / ".modal.toml").is_file() or bool(os.environ.get("MODAL_TOKEN_ID"))


def normalize_gpu(gpu):
    """Nom de carte accepté par Modal (`h100` → `H100`, `best` → la meilleure, `H100:2` gardé)."""
    if not gpu:
        return None
    gpu = str(gpu).strip()
    if gpu.lower() in ("best", "meilleure", "max"):
        return BEST_GPU
    if gpu.lower() in ("none", "aucune", "cpu"):
        return None
    name, _, count = gpu.partition(":")
    canon = next((g for g in GPUS if g.lower() == name.lower()), None)
    if canon is None:
        raise ModalError(f"Carte inconnue pour Modal : {name} (connues : {', '.join(GPUS)})")
    if count and not (count.isdigit() and 1 <= int(count) <= 8):
        raise ModalError(f"Nombre de cartes invalide : {count} (1 à 8)")
    return canon + (":" + count if count else "")


def project_files(root, include=(), with_git=False, cwd=None, run=subprocess.run):
    """Fichiers du projet à envoyer, relatifs à la racine."""
    root = Path(root)
    files = None
    if (root / ".git").exists():
        r = run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                 "--exclude-standard"], capture_output=True, timeout=60)
        if r.returncode == 0:
            files = [f for f in r.stdout.decode("utf-8", "surrogateescape").split("\0") if f]
    if files is None:
        files = [str(p.relative_to(root)) for p in sorted(root.rglob("*"))
                 if p.is_file() and ".git" not in p.relative_to(root).parts]
    extra = []
    for p in include:
        full = (Path(cwd or root) / p).resolve()
        try:
            rel = full.relative_to(root.resolve())
        except ValueError:
            raise ModalError(f"--include {p} : hors du projet") from None
        if full.is_dir():
            extra += [str(x.relative_to(root.resolve())) for x in sorted(full.rglob("*")) if x.is_file()]
        elif full.exists():
            extra.append(str(rel))
    if with_git and (root / ".git").is_dir():
        extra += [str(x.relative_to(root)) for x in sorted((root / ".git").rglob("*")) if x.is_file()]
    seen, out = set(), []
    for f in files + extra:
        if f not in seen and (root / f).is_file():
            seen.add(f)
            out.append(f)
    return out


def pack(root, files, dest):
    with tarfile.open(dest, "w:gz") as tar:
        for f in files:
            tar.add(str(Path(root) / f), arcname=f, recursive=False)
    return Path(dest).stat().st_size


def unpack(archive, where):
    """Extrait l'archive rapportée dans le dossier courant, sans sortir de celui-ci."""
    where = Path(where).resolve()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(where, filter="data")


def run_job(command, gpu, root, rel, overrides, fetch=(), include=(), with_git=False, cwd=None,
            say=print, popen=subprocess.Popen, run=subprocess.run):
    """Lance la commande sur Modal ; renvoie (code, raison)."""
    conf = settings(overrides)
    py = python_path(conf)
    if not py:
        raise ModalError("Modal introuvable : installe-le (pipx install modal) puis `modal setup`")
    gpu = normalize_gpu(gpu if gpu is not None else conf.get("gpu"))
    line = command[0] if len(command) == 1 else shlex.join(command)
    with tempfile.TemporaryDirectory(prefix="ccs-modal-") as tmp:
        tmp = Path(tmp)
        files = project_files(root, include, with_git, cwd, run=run)
        size = pack(root, files, tmp / "projet.tar.gz")
        say(f"modal ({gpu or 'processeur seul'}) : envoi de {Path(root).name} "
            f"({len(files)} fichiers, {size / 1e6:.1f} Mo)…")
        params = {"archive": str(tmp / "projet.tar.gz"), "command": line,
                  "rel": Path(rel).as_posix(), "fetch": list(fetch),
                  "out": str(tmp / "rapporte.tar.gz"), "status": str(tmp / "statut.json"),
                  "gpu": gpu, "python": conf.get("python") or "3.12",
                  "apt": conf.get("apt") or [], "pip": conf.get("pip") or [],
                  "timeout": conf.get("timeout") or DEFAULT_TIMEOUT,
                  "cpu": conf.get("cpu"), "memory": conf.get("memory")}
        (tmp / "params.json").write_text(json.dumps(params), encoding="utf-8")
        p = popen([py, str(RUNNER), str(tmp / "params.json")], stdin=subprocess.DEVNULL)
        try:
            p.wait()
        except KeyboardInterrupt:
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                p.kill()
            say("interrompu : bac à sable Modal arrêté")
            return 130, "interrompu : bac à sable Modal arrêté"
        try:
            status = json.loads((tmp / "statut.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ModalError(f"Modal : le lanceur s'est arrêté sans statut (code {p.returncode})") from None
        if status.get("error") and status.get("code") is None:
            raise ModalError(f"Modal : {status['error']}")
        code = status.get("code")
        code = 1 if code is None else int(code)
        why = "" if code == 0 else ("interrompu" if code == 130 else f"la commande a renvoyé {code}")
        got = status.get("fetched") or []
        if code == 0 and got:
            unpack(tmp / "rapporte.tar.gz", cwd or root)
            for path in got:
                say(f"{path} rapatrié")
        missing = [p for p in fetch if p not in got]
        if code == 0 and missing:
            code, why = 1, f"{missing[0]} : rien à rapatrier"
        elif code:
            for path in fetch:
                say(f"commande en échec (code {code}) : {path} non rapatrié")
        return code, why


def overview(overrides):
    """Ligne de la page Machines et de `ccs remote machines` pour Modal (None s'il n'est pas prêt)."""
    conf = settings(overrides)
    if not configured(conf):
        return None
    return {"id": MACHINE_ID, "name": "Modal (GPU à la demande)", "online": True, "local": False,
            "cores": 0, "load": 0.0, "mem_used": 0, "mem_total": 0, "tunnel": False,
            "gpu": conf.get("gpu") or ""}
