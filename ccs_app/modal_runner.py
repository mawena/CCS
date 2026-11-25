"""Exécute une commande dans un bac à sable Modal (lancé avec le python du paquet `modal`).

Autonome : n'importe rien de CCS, car il tourne avec le python où `modal` est installé.
Usage : python3 modal_runner.py <réglages.json>

Réglages (JSON) : archive (tar.gz du projet), command (texte shell), rel (dossier de la
commande dans le projet), fetch (chemins à rapporter), out (tar.gz rapporté), status (fichier
JSON écrit à la fin : code, erreur, rapportés), gpu, python, apt, pip, timeout, cpu, memory, app.
"""
import json
import signal
import sys
import threading

WORKDIR = "/projet"
CHUNK = 1 << 20


def _status(path, **data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _pump(stream, out):
    try:
        for chunk in stream:
            out.write(chunk)
            out.flush()
    except Exception:  # flux coupé à l'arrêt du bac à sable
        pass


def _image(modal, conf):
    image = modal.Image.debian_slim(python_version=conf.get("python") or None)
    apt = list(conf.get("apt") or [])
    if apt:
        image = image.apt_install(*apt)
    pip = list(conf.get("pip") or [])
    if pip:
        image = image.pip_install(*pip)
    return image


def _upload(sb, archive):
    p = sb.exec("tar", "xzf", "-", "-C", WORKDIR, text=False)
    with open(archive, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            p.stdin.write(chunk)
            p.stdin.drain()
    p.stdin.write_eof()
    p.stdin.drain()
    err = p.stderr.read()
    if p.wait():
        raise RuntimeError("envoi du projet raté : " + (err or b"").decode(errors="replace")[-300:])


def _fetch(sb, conf):
    where = WORKDIR + ("" if conf["rel"] in ("", ".") else "/" + conf["rel"])
    got = []
    for path in conf.get("fetch") or []:
        if sb.exec("test", "-e", path, workdir=where).wait() == 0:
            got.append(path)
        else:
            print(f"[ccs distant] {path} : rien à rapatrier", file=sys.stderr, flush=True)
    if not got:
        return got
    p = sb.exec("tar", "czf", "-", "--", *got, workdir=where, text=False)
    with open(conf["out"], "wb") as f:
        for chunk in p.stdout:
            f.write(chunk)
    if p.wait():
        raise RuntimeError("rapatriement raté : " + p.stderr.read().decode(errors="replace")[-300:])
    return got


def main(path):
    conf = json.load(open(path, encoding="utf-8"))
    status = conf["status"]
    import modal

    sb = None
    stopping = []

    def stop(signum, frame):
        stopping.append(signum)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        app = modal.App.lookup(conf.get("app") or "ccs-distant", create_if_missing=True)
        kw = {"app": app, "image": _image(modal, conf), "timeout": int(conf.get("timeout") or 3600),
              "workdir": WORKDIR}
        if conf.get("gpu"):
            kw["gpu"] = conf["gpu"]
        if conf.get("cpu"):
            kw["cpu"] = float(conf["cpu"])
        if conf.get("memory"):
            kw["memory"] = int(conf["memory"])
        sb = modal.Sandbox.create("sleep", "infinity", **kw)
        print(f"[ccs distant] bac à sable {sb.object_id} prêt ; envoi du projet…",
              file=sys.stderr, flush=True)
        sb.exec("mkdir", "-p", WORKDIR).wait()
        _upload(sb, conf["archive"])
        where = WORKDIR + ("" if conf["rel"] in ("", ".") else "/" + conf["rel"])
        p = sb.exec("bash", "-c", conf["command"], workdir=where, text=False)
        threads = [threading.Thread(target=_pump, args=(p.stdout, sys.stdout.buffer), daemon=True),
                   threading.Thread(target=_pump, args=(p.stderr, sys.stderr.buffer), daemon=True)]
        for t in threads:
            t.start()
        code = p.wait()
        for t in threads:
            t.join(timeout=10)
        got = _fetch(sb, conf) if code == 0 else []
        _status(status, code=code, error="", fetched=got)
        return 0
    except KeyboardInterrupt:
        _status(status, code=130, error="interrompu", fetched=[])
        return 0
    except Exception as e:  # noqa: BLE001 — tout échec de Modal remonte à CCS par le statut
        _status(status, code=None, error=f"{type(e).__name__} : {e}"[:500], fetched=[])
        return 0
    finally:
        if sb is not None:
            try:
                sb.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
