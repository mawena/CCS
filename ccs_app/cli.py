"""Point d'entrée `claude-accounts`."""

import argparse
import json
import os
import sys
import threading
import time

from . import __version__, core, procname


def cmd_print(_args):
    profiles = core.list_profiles()
    if not profiles:
        print("Aucun profil. Enregistre le compte actuel avec : ccs enregistrer <nom>")
        return 0
    tty = sys.stdout.isatty()
    bold, dim, green, yellow, red, off = (
        ("\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m") if tty else ("",) * 6)
    state = _state()
    results = {}
    threads = [threading.Thread(target=lambda n=p.name: results.__setitem__(n, core.fetch_usage(n)))
               for p in profiles]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for p in profiles:
        r = results[p.name]
        mark = f"{green}●{off}" if p.active else " "
        print(f"{mark} {bold}{p.name}{off}  {dim}{p.plan} · {p.email}{off}")
        for lim in core.parse_limits(r.usage):
            col = red if lim.percent >= 90 else yellow if lim.percent >= 70 else green
            filled = max(0, min(20, round(lim.percent / 5)))
            bar = "█" * filled + "░" * (20 - filled)
            print(f"    {lim.label:<24} {col}{bar}{off} {lim.percent:>3.0f} %  "
                  f"{dim}{core.fmt_reset(lim.resets_at)}{off}")
        extra = next((a for a in state.get("accounts") or [] if a.get("name") == p.name), {})
        fc, pace = extra.get("forecast") or {}, extra.get("pace")
        if fc.get("verdict") == "limit" and fc.get("eta"):
            print(f"    {yellow}⏱ Limite estimée vers "
                  f"{core.parse_dt(fc['eta']).astimezone():%H:%M}{off}")
        if pace:
            sign = "marge" if pace["margin"] >= 0 else "d'avance"
            print(f"    {dim}Semaine : {abs(pace['margin']):.0f} pts {sign} sur le rythme · "
                  f"budget {pace['per_day_budget']:.0f} %/jour{off}")
        if r.error:
            stale = f" (données de {core.fmt_time(r.fetched_at)})" if r.usage else ""
            print(f"    {red}⚠ {r.error}{off}{dim}{stale}{off}")
        print()
    return 0


def cmd_gui(args):
    try:
        from .gui.app import run
    except ImportError as e:
        print(f"Interface graphique indisponible : {e}", file=sys.stderr)
        return 1
    kw = dict(session=getattr(args, "session", None), page=getattr(args, "page", None),
              new_session=getattr(args, "new_session", False))
    if getattr(args, "task", None):
        kw["task"] = args.task
    return run(**kw)


def _page(text):
    """Option --page : nom réel d'un onglet ou son titre en français."""
    from .desktop import PAGE_CHOICES, canonical_page
    name = canonical_page(text)
    if name is None:
        raise argparse.ArgumentTypeError(f"onglet inconnu : « {text} » ({', '.join(PAGE_CHOICES)})")
    return name


def _task_ref(text):
    """Option --task : identifiant d'une tâche de la file."""
    from .desktop import valid_task_id
    if not valid_task_id(text):
        raise argparse.ArgumentTypeError(f"identifiant de tâche illisible : « {text} »")
    return text


def cmd_tache(args):
    from . import tasks
    return tasks.command(list(args.args))


def cmd_root(args):
    from . import root_keeper
    return root_keeper.command(list(args.args))


def cmd_budget(args):
    from . import budget
    from .settings import load_settings
    return budget.command(list(args.args), settings=load_settings())


def cmd_fiche(args):
    from . import fiche
    return fiche.command(list(args.args))


def cmd_sauvegarde(args):
    from . import backup
    return backup.command(["sauvegarde", *args.args])


def cmd_restaurer(args):
    from . import backup
    return backup.command(["restaurer", *args.args])


TELEPHONE_USAGE = "usage : ccs telephone [essai]"


def cmd_telephone(args):
    """`ccs telephone` : état et lien d'abonnement ; `ccs telephone essai` : message d'essai."""
    from . import phone
    from .settings import load_settings
    rest = list(args.args)
    settings = load_settings()
    if rest in (["essai"], ["test"]):
        ok, text = phone.send_test(settings)
        print(text, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if rest:
        print(TELEPHONE_USAGE, file=sys.stderr)
        return 2
    cfg = phone.config(settings)
    link = phone.subscribe_url(cfg)
    print("Notifications sur le téléphone : " + ("activées" if cfg["enabled"] else "désactivées"))
    print(f"  Serveur : {cfg['server']}")
    if link is None:
        print("  Canal   : aucun (crée-le dans Réglages > Téléphone de l'application)")
        return 0
    print(f"  Lien d'abonnement (à ouvrir dans l'application ntfy, à garder secret) : {link}")
    events = ", ".join(label for key, label in phone.EVENTS if cfg["events"].get(key, True))
    print(f"  Événements : {events or 'aucun'}")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(link)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:  # python3-qrcode absent : le lien suffit
        pass
    print("  Essayer : ccs telephone essai")
    return 0


def cmd_auth_serve(_args):
    """Service ccs-auth (root, lancé par systemd)."""
    import asyncio
    from .server import auth
    if os.geteuid() != 0:
        print("ccs auth-serve : réservé au service ccs-auth (root).", file=sys.stderr)
        return 1
    asyncio.run(auth.serve())
    return 0


def cmd_bridge(args):
    """Pont CCS de l'utilisateur courant (service ccs-bridge@, ou --local)."""
    import asyncio
    import logging
    import pwd
    from .server import bridge, paths
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    user = pwd.getpwuid(os.getuid()).pw_name
    local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin")   # Claude Code (installeur officiel)
    if local_bin not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = local_bin + ":" + os.environ.get("PATH", "/usr/bin:/bin")
    if args.local:
        from .remote.client import default_socket
        sock = args.socket or default_socket()
        os.makedirs(os.path.dirname(str(sock)), mode=0o700, exist_ok=True)
        key = None
    else:
        sock = args.socket or paths.bridge_socket(user)
        try:
            key = paths.bridge_key(user).read_bytes()
        except OSError:
            print("ccs bridge : clé du pont absente (lancé hors de ccs-auth ?)", file=sys.stderr)
            return 1
    b = bridge.build(user, key, local=args.local)
    asyncio.run(b.serve(sock))
    if b.restart:          # CCS mis à jour : même commande, nouveau code (même pid)
        from . import core
        exe = core.ccs_bin()
        os.execv(exe, [exe, "bridge", "--local", "--socket", str(sock)])
    return 0


def cmd_web_serve(_args):
    """Service ccs-web (utilisateur système ccs-web, lancé par systemd)."""
    import asyncio
    from .server import web
    asyncio.run(web.serve())
    return 0


def cmd_serveur(args):
    """Serveurs CCS connus : appairage (mot de passe Ubuntu + code, une fois), liste, retrait."""
    import getpass
    from .remote import servers
    if args.action == "liste":
        items = servers.load()
        if not items:
            print("Aucun serveur CCS. Ajoute-en un : ccs serveur ajouter <adresse>")
        for s in items:
            print(f"{s.name:<28} {s.url}  ({s.user})")
        return 0
    if args.action == "retirer":
        if servers.remove(args.cible):
            print(f"Serveur {args.cible} retiré (le jeton reste valable sur le serveur : révoque-le dans ses Réglages).")
            return 0
        print(f"Serveur inconnu : {args.cible}", file=sys.stderr)
        return 1
    try:
        url = servers.normalize_url(args.cible)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    name = args.nom or f"ccs sur {os.uname().nodename}"
    user = input(f"Identifiant Ubuntu sur {url} : ").strip() or getpass.getuser()
    password = getpass.getpass("Mot de passe : ")
    result = servers.pair(url, user, password, "", name)
    if isinstance(result, dict) and result.get("status") == "enroll":
        from .server import totp
        print("Première connexion : ajoute ce code dans ton application (Aegis, Google Authenticator…).")
        print(f"Clé : {result['secret']}")
        try:
            import qrcode
            qr = qrcode.QRCode(border=1)
            qr.add_data(totp.uri(user, result["secret"], url.split("://", 1)[1]))
            qr.print_ascii(invert=True)
        except ImportError:
            pass
        result = servers.finish_enroll(url, user, result["pending"], input("Code à 6 chiffres : ").strip(), name)
    elif isinstance(result, dict) and result.get("status") == "code":
        result = servers.pair(url, user, password, input("Code à 6 chiffres : ").strip(), name)
    if isinstance(result, servers.Server):
        print(f"Serveur {result.name} appairé : ccs tui --serveur {result.name}")
        return 0
    if result.get("status") == "blocked":
        print(f"Trop d'essais : réessaie dans {max(1, result.get('retry_after', 60) // 60)} min.", file=sys.stderr)
    else:
        print(result.get("message") or "Appairage refusé.", file=sys.stderr)
    return 1


def cmd_tui(args):
    """CCS en plein écran dans le terminal : en local, ou vers un serveur appairé."""
    from .remote import client, servers
    from .tui import app
    if args.serveur:
        server = servers.get(args.serveur)
        if server is None:
            print(f"Serveur inconnu : {args.serveur}. Appaire-le d'abord : ccs serveur ajouter <adresse>",
                  file=sys.stderr)
            return 1
        transport, label = client.WebTransport(server), server.name
    else:
        transport, label = client.LocalTransport(), "local"
    app.run(transport, label)
    return 0


def cmd_shell_distant(args):
    """Relais entre ce terminal et un shell d'un serveur CCS (onglet « Terminal » distant)."""
    import asyncio
    import signal
    import termios
    import tty
    from .remote import client, servers, shell
    server = servers.get(args.serveur)
    if server is None:
        print(f"Serveur inconnu : {args.serveur}", file=sys.stderr)
        return 1

    def size():
        try:
            s = os.get_terminal_size(sys.stdout.fileno())
            return s.columns, s.lines
        except OSError:
            return 80, 24

    async def main():
        c = client.BridgeClient(client.WebTransport(server), retry_delays=())
        await c.connect()
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        resized = asyncio.Event()
        loop.add_signal_handler(signal.SIGWINCH, resized.set)

        def write(data):
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        try:
            return await shell.relay(c, args.cwd, reader, write, size, resized)
        finally:
            await c.close()

    saved = termios.tcgetattr(sys.stdin) if sys.stdin.isatty() else None
    try:
        if saved is not None:
            tty.setraw(sys.stdin)
        return asyncio.run(main())
    except (client.AuthError, ConnectionError, OSError) as e:
        print(f"\r\nServeur {server.name} : {e}\r", file=sys.stderr)
        return 1
    finally:
        if saved is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)


def cmd_totp(args):
    """Réinitialise le code de double authentification d'un utilisateur (root)."""
    from .server import totp
    if os.geteuid() != 0:
        print("Il faut les droits root : sudo ccs totp reinitialiser <utilisateur>", file=sys.stderr)
        return 1
    try:
        done = totp.reset(args.user)
    except ValueError:
        print(f"Nom d'utilisateur invalide : {args.user}", file=sys.stderr)
        return 1
    print(f"Code de {args.user} réinitialisé : il en choisira un nouveau à sa prochaine connexion."
          if done else f"{args.user} n'avait pas de code enregistré.")
    return 0


def cmd_daemon(_args):
    from . import daemon
    return daemon.run()


def cmd_collect(_args):
    from . import daemon
    if daemon.request_refresh():
        print("Collecte demandée au service.")
        return 0
    daemon.collect_once()
    print(f"État écrit dans {daemon.state_path()}")
    return 0


def cmd_analyze(args):
    import time
    from . import transcripts
    from .store import Store
    since = time.time() - args.days * 86400
    rows = transcripts.scan(core.paths().config_dir / "projects", since)
    periods = Store().active_periods(since, time.time())
    r = transcripts.aggregate(rows, periods, args.days)
    if not rows:
        print(f"Aucune activité Claude Code sur les {args.days} derniers jours.")
        return 0
    fmt = transcripts.fmt_tokens
    print(f"Usage des {args.days} derniers jours : {fmt(r.total)} tokens pondérés "
          f"({len(rows)} réponses)\n")
    for title, data in (("Par projet", r.by_project), ("Par modèle", r.by_model),
                        ("Par compte", r.by_account)):
        print(title)
        for name, v in sorted(data.items(), key=lambda kv: -kv[1])[:8]:
            print(f"  {name:<28} {100 * v / r.total:5.1f} %  {fmt(v):>9}")
        print()
    peak = max(r.by_hour) or 1
    print("Par heure")
    for h in range(24):
        if r.by_hour[h]:
            print(f"  {h:02d} h {'█' * max(1, round(30 * r.by_hour[h] / peak))}")
    tips = transcripts.advice(r)
    if tips:
        print("\nConseils")
        for t in tips:
            print(f"  • {t}")
    return 0


def cmd_tray(_args):
    from . import tray
    return tray.run()


def _state():
    from . import daemon
    return core.load_json(daemon.state_path())


def cmd_status(_args):
    from . import daemon
    from .settings import load_settings
    st = _state()
    s = load_settings()
    if not st.get("accounts"):
        print("Statut : aucune donnée pour l'instant (lance « ccs usage » ou démarre le service).")
    else:
        act = next((a for a in st["accounts"] if a.get("active")), None)
        if act:
            parts = ", ".join(f"{l['label'].split(' ')[0].lower()} {l['percent']:.0f} %"
                              for l in act.get("limits") or [])
            print(f"Compte actif : {act['name']} ({parts or 'pas de données'})")
            fc = act.get("forecast") or {}
            if fc.get("verdict") == "limit" and fc.get("eta"):
                print(f"Prévision : limite de session vers {core.parse_dt(fc['eta']).astimezone():%H:%M}")
        else:
            print("Compte actif : non enregistré dans un profil")
        best = st.get("best")
        print(f"Meilleur compte : {best['name']} — {best['reason']}" if best
              else "Meilleur compte : aucun disponible")
        print(f"Capacité restante : {core.fr(st.get('capacity') or 0)} session(s)")
        if st.get("updated_at"):
            print(f"Données de {core.fmt_time(st['updated_at'])}")
    auto = s["auto_switch"]
    print("Bascule automatique : " + (f"activée (seuil {auto['threshold']} %)" if auto["enabled"]
                                      else "désactivée"))
    o = s["orchestrator"]
    print("Orchestrateur : " + (f"activé (plage {o['active_hours']['start']} → "
                                f"{o['active_hours']['end']})" if o["enabled"] else "désactivé"))
    paused = _pause_line()
    if paused:
        print(paused)
    silence = _silence_line()
    if silence:
        print(silence)
    print("Service : " + ("en marche" if daemon.running_pid() else "arrêté"))
    return 0


def _pause_line():
    from datetime import datetime, timezone
    from . import pause
    now = datetime.now(timezone.utc)
    st = pause.pause_state(now)
    if st is None:
        return None
    return (f"En pause {pause.label(st, now)} : bascule automatique et orchestrateur suspendus "
            "(ccs pause off pour reprendre)")


def _silence_line():
    from datetime import datetime, timezone
    from . import quiet
    now = datetime.now(timezone.utc)
    st = quiet.quiet_state(now)
    if st is None:
        return None
    if st.source == "plage":
        return f"Ne pas déranger (plage de silence) {quiet.label(st, now)} : notifications retenues"
    return (f"Ne pas déranger {quiet.label(st, now)} : notifications retenues "
            "(ccs silence off pour reprendre)")


def _notify(title, body=""):
    """Résultat d'une commande lancée par un raccourci clavier (--notifier) : notification
    passagère ; rien si le bureau est injoignable."""
    from . import notify
    return notify.message(title, body) is not None


def cmd_notify(args):
    return 0 if _notify(args.title, args.body or "") else 1


def _pause_notice(choice, st, was, now):
    """(titre, texte) de la notification de `ccs pause … --notifier`."""
    from . import pause
    if st is not None:
        return (f"Pause {pause.label(st, now)}",
                "Bascule automatique et orchestrateur suspendus.")
    if choice in pause.RESUME and was is not None:
        return "Pause levée", "La bascule automatique et l'orchestrateur reprennent."
    return "Pas de pause en cours", "La bascule automatique et l'orchestrateur suivent les réglages."


def cmd_pause(args):
    from datetime import datetime, timezone
    from . import daemon, pause
    now = datetime.now(timezone.utc)
    before = pause.pause_state(now)
    code, message = pause.command(_status_word(args.choice), now)
    if code != 0:
        print(message, file=sys.stderr)
        if args.notifier:
            _notify("Pause impossible", message)
        return code
    print(message)
    after = pause.pause_state(now)
    if after != before:
        daemon.request_refresh()  # le service relit la pause et met à jour l'état partagé
    if args.notifier:
        _notify(*_pause_notice(args.choice, after, before, now))
    return 0


def cmd_doctor(_args):
    from . import doctor
    return doctor.main()


def _usable_best(st):
    """(meilleur compte, comptes ignorés) d'après l'état : un compte dont le dernier relevé
    est en erreur (connexion perdue, jeton refusé, relevé absent ou trop ancien) n'est
    jamais recommandé. Le choix du service est gardé s'il est utilisable (réserve
    comprise) ; sinon il est recalculé sans les comptes ignorés."""
    import time
    from datetime import datetime, timezone
    from .forecast import account_issue, accounts_from_state, best_account
    now = time.time()
    ignored = []
    for a in st.get("accounts") or []:
        # État d'une ancienne version sans date de relevé : on ne juge que l'erreur.
        fetched = a["fetched_at"] if "fetched_at" in a else now
        why = account_issue(a.get("error"), fetched, now)
        if why:
            ignored.append((a.get("name"), why))
    best = st.get("best")
    bad = {name for name, _ in ignored}
    if not ignored or (best and best.get("name") not in bad):
        return best, ignored
    usable = [a for a in accounts_from_state(st) if a.name not in bad]
    rec = best_account(usable, datetime.now(timezone.utc))
    return (rec and {"name": rec.name, "reason": rec.reason}), ignored


def cmd_best(args):
    notifier = getattr(args, "notifier", False)

    def notice(title, body=""):
        if notifier:
            _notify(title, body)
    if not core.list_profiles():
        print("Aucun profil. Enregistre le compte actuel avec : ccs enregistrer <nom>")
        notice("Bascule impossible", "Aucun profil : enregistre le compte actuel avec « ccs enregistrer <nom> ».")
        return 1
    from . import daemon, switch_log
    st = _state()
    if not daemon.state_fresh(st):
        # Jamais de bascule sur la foi d'un état ancien : relevé d'abord.
        if daemon.request_refresh():
            import time
            deadline = time.time() + 20
            while time.time() < deadline and not daemon.state_fresh(_state()):
                time.sleep(0.5)
        else:
            daemon.collect_once()
        st = _state()
    best, ignored = _usable_best(st)
    for who, why in ignored:
        print(f"{who} ignoré : {why}")
    if not best:
        if ignored:
            print("Aucun compte utilisable pour l'instant.")
            notice("Aucun compte utilisable",
                   "\n".join(f"{who} ignoré : {why}" for who, why in ignored))
        else:
            print("Aucun compte disponible pour l'instant.")
            notice("Aucun compte disponible",
                   "Tous les comptes sont épuisés ou indisponibles pour l'instant.")
        return 1
    name = best["name"]
    print(f"Meilleur compte : {name} — {best['reason']}")
    if getattr(args, "voir", False):  # `ccs meilleur --voir` : sans basculer
        notice(f"Meilleur compte : {name}", best["reason"])
        return 0
    if name == core.active_profile_name():
        print("C'est déjà le compte actif.")
        notice(f"Déjà sur {name}", f"C'est le meilleur compte : {best['reason']}")
        return 0
    # Origine pour le journal des bascules : à la main, ou par un raccourci clavier.
    switch_log.note_origin(name, "raccourci" if notifier else "ccs")
    r = core.run_ccs(["use", name])
    print((r.stdout + r.stderr).strip())
    if r.returncode == 0:
        daemon.request_refresh()
        notice(f"Bascule sur {name}", f"Meilleur compte : {best['reason']}")
    else:
        switch_log.clear_origin()  # aucune bascule : la note ne doit rien attribuer plus tard
        notice("Bascule impossible", (r.stderr or r.stdout).strip())
    return r.returncode


def cmd_auto(args):
    from . import daemon
    from .settings import load_settings, save_settings
    s = load_settings()
    s["auto_switch"]["enabled"] = args.state == "on"
    save_settings(s)
    daemon.request_refresh()
    print("Bascule automatique " + ("activée" if args.state == "on" else "désactivée"))
    return 0


def cmd_orch(args):
    from . import daemon
    from .settings import load_settings, save_settings
    s = load_settings()
    s["orchestrator"]["enabled"] = args.state == "on"
    save_settings(s)
    daemon.request_refresh()
    h = s["orchestrator"]["active_hours"]
    print("Orchestrateur " + (f"activé (plage {h['start']} → {h['end']})" if args.state == "on"
                              else "désactivé"))
    return 0


def _hm(iso):
    return f"{core.parse_dt(iso).astimezone():%H:%M}"


def cmd_plan(_args):
    st = _state()
    o = st.get("orchestrator")
    if not o:
        print("Planning : aucune donnée pour l'instant (démarre le service : ccs etat).")
        return 0
    head = "activé" if o.get("enabled") else "désactivé (ccs orchestrateur on)"
    if o.get("period"):
        head += f" · plage {_hm(o['period'][0])} → {_hm(o['period'][1])}"
    elif o.get("enabled"):
        head += " · hors plage horaire"
    if o.get("next_wake"):
        head += f" · prochain réveil {_hm(o['next_wake'])}"
    print(f"Orchestrateur : {head}")
    reserve = set(o.get("reserve") or [])
    names = sorted({w["name"] for w in o.get("plan") or []} |
                   {a["name"] for a in st.get("accounts") or []})
    for name in names:
        parts = [f"{_hm(w['start'])}–{_hm(w['end'])}" + (" (en cours)" if w["kind"] == "current" else "")
                 for w in o.get("plan") or [] if w["name"] == name]
        tag = "  [réserve : semaine en avance]" if name in reserve else ""
        print(f"  {name:<14} {' · '.join(parts) or 'au repos'}{tag}")
    ends = sorted((core.parse_dt(w["end"]), w["name"]) for w in o.get("plan") or [])
    if ends:
        print("Recharges : " + " · ".join(f"{e.astimezone():%H:%M} {n}" for e, n in ends[:8]))
    return 0


def _duration(seconds):
    minutes = int(seconds // 60)
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def cmd_sessions(_args):
    import time
    from . import sessions, transcripts
    found = sessions.list_sessions()
    if not found:
        print("Aucune session Claude Code ouverte.")
        return 0
    from . import context_alert, session_memory
    from .settings import load_settings
    settings = load_settings()
    active = core.active_profile_name() or "compte non enregistré"
    print(f"{len(found)} session(s) ouverte(s) — toutes sur le compte actif : {active}")
    try:
        memory = session_memory.snapshot(found, settings=settings)
    except Exception:  # /proc illisible : on affiche le reste
        memory = {}
    heavy = {}
    if settings["context_alert"]["enabled"]:
        try:
            heavy = context_alert.contexts_for(found)
        except Exception:
            heavy = {}
    for s in found:
        u = sessions.conversation_usage(s)
        mem = memory.get(s.pid)
        ctx = heavy.get(s.pid)
        ram = f"  {session_memory.line_text(mem)}" if mem else ""
        badge = (f"  [{context_alert.badge_text(ctx)}]"
                 if ctx is not None and context_alert.is_heavy(ctx, settings) else "")
        print(f"  {s.project:<16} {sessions.state_label(s):<28} depuis {_duration(time.time() - s.started_at):<9}"
              f" {u.model:<7} {transcripts.fmt_tokens(u.weighted):>8} tokens  (pid {s.pid}, {s.name}){ram}{badge}")
    if memory:
        total = session_memory.summary(memory)
        print(f"Mémoire des sessions : {session_memory.fmt_bytes(total.total)} au total.")
        banner = session_memory.banner_text(total)
        if banner:
            print(f"{banner}. Ferme celles dont tu n'as plus besoin pour libérer la RAM.")
    return 0


def _project_filter(convs, wanted):
    """Dossiers de l'historique désignés par un nom de projet ou un chemin."""
    import os
    from . import conversations as conv, sessions
    if not wanted:
        return None
    path = os.path.abspath(os.path.expanduser(wanted))
    return {cwd for cwd, _ in conv.projects(convs)
            if cwd == path or sessions.project_name(cwd).casefold() == wanted.casefold()}


def cmd_conversations(args):
    from dataclasses import asdict
    from . import conversations as conv
    convs = conv.scan()
    origin = "vscode" if args.vscode else "terminal" if args.terminal else None
    folders = _project_filter(convs, args.project)
    if folders is not None and not folders:
        print(f"Aucun projet « {args.project} » dans l'historique.", file=sys.stderr)
        return 1
    found = [c for c in conv.search(convs, " ".join(args.query), origin=origin)
             if folders is None or c.cwd in folders]
    shown = found if args.all else found[:args.limit]
    if args.json:
        print(json.dumps([dict(asdict(c), project=c.project) for c in shown], ensure_ascii=False, indent=2))
        return 0
    if not found:
        print("Aucune conversation." if not convs else "Aucune conversation ne correspond.")
        return 0
    tty = sys.stdout.isatty()
    bold, dim, green, red, off = ("\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[0m") if tty else ("",) * 5
    opened = conv.open_ids()
    moved_to = conv.suggest_folders(convs)
    home = str(core.paths().home)
    for label, group in conv.group_by_day(shown):
        print(f"{bold}{label}{off}")
        for c in group:
            flag = f"  {green}● ouverte{off}" if c.session_id in opened else ""
            if not c.folder_exists:
                moved = moved_to.get(c.session_id)
                flag = (f"  {red}✗ dossier introuvable{off}" + (
                    f" {dim}(déplacé vers {moved.replace(home, '~', 1)} ?){off}" if moved else ""))
            if c.archived:
                flag += f"  {dim}◌ archivée{off}"
            n = f"{c.prompts} demande{'s' if c.prompts > 1 else ''}"
            print(f"  {c.session_id[:8]}  {conv.ago(c.updated_at):<13} {c.project[:18]:<18} "
                  f"{c.origin_label:<8} {c.title}  {dim}({n}){off}{flag}")
        print()
    if len(found) > len(shown):
        print(f"{dim}… et {len(found) - len(shown)} de plus (--tous pour tout afficher){off}")
    where = f" dans {args.project}" if args.project else ""
    print(f"{dim}{len(found)} conversation(s){where}. Reprendre : ccs reprendre <identifiant> "
          f"[--vscode]{off}".replace(home, "~"))
    return 0


def cmd_resume(args):
    import os
    from . import conversations as conv, sessions
    convs = conv.scan()
    try:
        c = conv.find(convs, args.ref)
    except LookupError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    try:
        if args.dir:
            c = conv.relocate(c, args.dir)
        elif not c.folder_exists:
            moved = conv.suggest_folder(c, convs)
            hint = f"Indique son nouvel emplacement : ccs reprendre {args.ref} --dossier <dossier>"
            if not moved:
                print(f"Erreur : dossier introuvable : {c.cwd or '?'}\n{hint}", file=sys.stderr)
                return 1
            question = (f"Le dossier {c.cwd} n'existe plus.\n"
                        f"Reprendre depuis {moved} (dossier du même nom) ? [o/N] ")
            if not sys.stdin.isatty():
                print(f"Erreur : dossier introuvable : {c.cwd}\nPeut-être déplacé vers {moved}. {hint}",
                      file=sys.stderr)
                return 1
            if input(question).strip().lower() not in ("o", "oui", "y", "yes"):
                print(hint, file=sys.stderr)
                return 1
            c = conv.relocate(c, moved)
    except OSError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    problem = conv.resume_problem(c, conv.open_ids())
    if problem:
        print(f"Erreur : « {c.title} » est {problem}." if "ouverte" in problem
              else f"Erreur : {problem}", file=sys.stderr)
        return 1
    if c.archived:
        try:
            c = conv.ensure_conversation(c)
        except (OSError, ValueError) as e:
            print(f"Erreur : restauration de la conversation archivée impossible : {e}", file=sys.stderr)
            return 1
        print(f"Conversation archivée restaurée dans {c.path}.", file=sys.stderr)
    if args.print:
        print(conv.resume_command(c))
        return 0
    if args.vscode:
        try:
            conv.resume_vscode(c, wait=True)
        except FileNotFoundError as e:
            print(f"Erreur : {e}", file=sys.stderr)
            return 1
        print(f"« {c.title} » rouverte dans VS Code ({c.cwd}).")
        return 0
    if args.new_terminal:
        conv.resume_terminal(c)
        print(f"« {c.title} » rouverte dans un nouveau terminal.")
        return 0
    os.chdir(c.cwd)
    claude = sessions._claude_bin()
    os.execvp(claude, [claude, "--resume", c.session_id])


def cmd_title(args):
    from . import conversations as conv
    try:
        c = conv.find(conv.scan(), args.ref)
        title = conv.rename(c.session_id, " ".join(args.title), path=c.path)
    except (LookupError, ValueError, OSError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    print(f"« {c.title} » s'appelle maintenant « {title} ».")
    return 0


def _conversation(ref):
    """Conversation désignée comme pour `ccs reprendre` / `ccs titre` ; None (erreur affichée) sinon."""
    from . import conversations as conv
    try:
        return conv.find(conv.scan(), ref)
    except LookupError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return None


def _cost_text(c):
    from . import costs
    from . import conversations as conv
    return costs.format_cost(conv.cost_for_path(c.path))


def cmd_preview(args):
    import os
    from . import preview
    c = _conversation(args.ref)
    if c is None:
        return 1
    try:
        text = preview.markdown_for(c, cost=_cost_text(c))
    except OSError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:  # `ccs apercu … | head` : lecteur parti, pas de trace Python
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return 0


def cmd_export(args):
    from pathlib import Path
    from . import preview
    c = _conversation(args.ref)
    if c is None:
        return 1
    dest = Path(args.file).expanduser() if args.file else Path.cwd()
    if dest.is_dir():
        dest = dest / preview.suggested_filename(c)
    try:
        written = preview.export_markdown(c, dest.absolute(), cost=_cost_text(c))
    except OSError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    print(written)
    return 0


def _waiting(text):
    """Message d'attente sur la sortie d'erreur quand c'est un terminal ; renvoie la
    fonction qui l'efface."""
    tty = sys.stderr.isatty()
    if tty:
        sys.stderr.write(text)
        sys.stderr.flush()

    def done():
        if tty:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()
    return done


def cmd_formule(_args):
    from . import advisor
    done = _waiting("Calcul du conseil : relevés du service et journaux de Claude Code…")
    try:
        advice = advisor.compute()
    except Exception as e:  # noqa: BLE001 — historique ou journaux illisibles : message, pas de trace
        done()
        print(f"Conseil impossible : {e}", file=sys.stderr)
        return 1
    done()
    print(advisor.format_text(advice))
    return 0


MAX_WEEKS_BACK = 520


def _weeks_back(text):
    """Option --precedente : nombre de semaines avant la semaine écoulée (0 à 520)."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"nombre de semaines invalide : « {text} »") from None
    if not 0 <= n <= MAX_WEEKS_BACK:
        raise argparse.ArgumentTypeError(f"nombre de semaines entre 0 et {MAX_WEEKS_BACK} : « {text} »")
    return n


def cmd_semaine(args):
    from datetime import datetime, timezone
    from . import daemon, weekly_report
    from .settings import load_settings
    now = datetime.now(timezone.utc)
    try:
        accounts = daemon.states_from_state(_state())
    except (KeyError, TypeError, ValueError):
        accounts = []  # état illisible : semaine du lundi 9:00 (ou du jour réglé)
    try:
        weeks = weekly_report.week_choices(accounts, now, load_settings(), count=args.precedente + 1)
        start, end = weeks[args.precedente + 1]
        done = _waiting("Calcul du bilan : relevés du service et journaux de Claude Code…")
        try:
            report = weekly_report.build_report(start, end)
        finally:
            done()
    except Exception as e:  # noqa: BLE001 — historique ou journaux illisibles : message, pas de trace
        print(f"Bilan impossible : {e}", file=sys.stderr)
        return 1
    print(weekly_report.format_text(report))
    return 0


def cmd_silence(args):
    from datetime import datetime, timezone
    from . import daemon, quiet
    now = datetime.now(timezone.utc)
    before = quiet.quiet_state(now)
    code, message = quiet.command([_status_word(a) for a in args.args[:1]] + list(args.args[1:]), now)
    if code != 0:
        print(message, file=sys.stderr)
        if args.notifier:
            _notify("Silence impossible", message)
        return code
    print(message)
    after = quiet.quiet_state(now)
    if after != before:
        daemon.request_refresh()  # le service relit le silence et met à jour l'état partagé
    if args.notifier:
        _notify(*_silence_notice(after, before, now))
    return 0


def _silence_notice(st, was, now):
    """(titre, texte) de la notification de `ccs silence … --notifier`."""
    from . import quiet
    if st is not None and st != was:
        return (f"Ne pas déranger {quiet.label(st, now)}",
                "Les notifications sont retenues puis résumées.")
    if st is None and was is not None:
        return "Silence levé", "Les notifications reprennent."
    if st is not None:
        return f"Ne pas déranger {quiet.label(st, now)}", "Aucun changement."
    return "Pas de silence en cours", "Les notifications arrivent normalement."


def cmd_moment(args):
    from . import best_time
    argv = [x for name in ("duree", "sur") if getattr(args, name) is not None
            for x in (f"--{name}", getattr(args, name))]
    code, text = best_time.command(argv)
    print(text, file=sys.stdout if code == 0 else sys.stderr)
    return code


def cmd_mois(args):
    from . import monthly_report
    done = _waiting("Calcul du rapport : relevés du service et journaux de Claude Code…")
    try:
        code, text = monthly_report.command(args)
    finally:
        done()
    print(text, file=sys.stdout if code == 0 else sys.stderr)
    return code


def cmd_mise_a_jour(args):
    from . import installer
    code, text = installer.command(["--verifier"] if args.verifier else [],
                                   out=lambda line: print(line, flush=True))
    print(text, file=sys.stdout if code == 0 else sys.stderr)
    return code


def cmd_chat(args):
    """Chats de CCS : `effacer` demande `/clear` à la fin du tour en cours (lancé par Claude)."""
    from . import chat_engine
    token = (os.environ.get(chat_engine.CLEAR_TOKEN_VAR)
             or os.environ.get(chat_engine.OLD_CLEAR_TOKEN_VAR, ""))
    if not token:
        print("Pas dans un chat de CCS (ou effacement automatique désactivé dans les réglages) : "
              "rien à effacer.", file=sys.stderr)
        return 1
    try:
        chat_engine.request_clear(token)
    except (OSError, ValueError) as e:
        print(f"Demande d'effacement impossible : {e}", file=sys.stderr)
        return 1
    print("La conversation sera effacée (/clear) à la fin de ce tour.")
    return 0


def _job_line(job, now):
    """Une ligne de `ccs distant travaux`."""
    when = job.get("ended") or job.get("started") or job.get("created") or now
    ago = max(int(now - when), 0)
    ago = f"{ago} s" if ago < 60 else f"{ago // 60} min" if ago < 3600 else f"{ago // 3600} h"
    from . import distant_jobs
    state = distant_jobs.label(job.get("state"))
    if job.get("code") is not None and job.get("state") in ("done", "failed"):
        state += f" ({job['code']})"
    line = f"{job['id']}  {state:<12} {job.get('machine') or '-':<14} {job.get('text', '')}  (il y a {ago})"
    if job.get("why"):
        line += f"\n        {job['why']}"
    return line


def cmd_distant(args):
    """Calcul réparti : machines du réseau Ricochet et commandes lancées dessus."""
    from . import distant, distant_jobs
    try:
        if args.action == "machines":
            machines = distant.fetch_machines()
            lines = distant.describe(machines, distant.load_overrides(), probe=not args.vite)
            print("\n".join(lines) if lines else "Aucune machine dans Ricochet.")
            return 0
        if args.action == "ajouter":
            r = distant.add_machine(args.id, name=args.nom, user=args.utilisateur, limit=args.limite)
            print(f"« {r['id']} » est déclarée. Sur la nouvelle machine, colle dans un terminal "
                  f"(lien valable {r['expires_s'] // 60} min, une seule fois) :\n\n  {r['command']}\n\n"
                  "Elle installe l'agent Ricochet et le serveur SSH, autorise la clé SSH de ce "
                  "serveur et la rend joignable par `ccs distant`.")
            return 0
        if args.action == "travaux":
            now = time.time()
            jobs = distant_jobs.list_jobs()
            print("\n".join(_job_line(j, now) for j in jobs) if jobs else "Aucun travail.")
            return 0
        if args.action == "arreter":
            if not distant_jobs.stop(args.id):
                print(f"Travail {args.id} introuvable ou déjà fini.", file=sys.stderr)
                return 1
            print(f"Travail {args.id} arrêté.")
            return 0
        if args.action == "journal":
            job = distant_jobs.get(args.id)
            if job is None:
                print(f"Travail {args.id} introuvable.", file=sys.stderr)
                return 1
            text = distant_jobs.read_log(args.id)
            if text:
                sys.stdout.write(text if text.endswith("\n") else text + "\n")
            else:
                print("Pas de journal (travail lancé sans --detache)." if not job.get("detached")
                      else "Journal vide pour l'instant.")
            return 0
        command = list(args.commande)
        if command[:1] == ["--"]:
            command = command[1:]
        if args.quand:
            distant.schedule(args.quand)  # refuse tout de suite une heure invalide
        if args.detache and not args.travail:
            if not command:
                raise distant.DistantError("Aucune commande : ccs distant lancer -- <commande>")
            job_id = distant_jobs.start(command, os.getcwd(), machine=args.machine, when=args.quand,
                                        tool=args.outil, fetch=args.rapatrier,
                                        include=args.inclure, with_git=args.avec_git)
            print(f"Travail {job_id} lancé en arrière-plan. Suivi : ccs distant travaux, "
                  f"ccs distant journal {job_id} ; arrêt : ccs distant arreter {job_id}")
            return 0
        return distant.launch(command, machine=args.machine, tool=args.outil,
                              fetch=args.rapatrier, include=args.inclure, with_git=args.avec_git,
                              when=args.quand, job_id=args.travail, detached=args.detache)
    except distant.DistantError as e:
        print(e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def cmd_reseau(args):
    """Réseau maillé (Headscale) : appareils, chemin de chaque liaison, clés d'inscription."""
    from . import network
    try:
        action = args.action or "etat"
        if action == "etat":
            print("\n".join(network.describe(network.status())))
        elif action == "ping":
            print(network.ping_text(network.ping(args.machine)))
        elif action == "cle":
            key = network.auth_key(args.utilisateur, args.duree)
            print(f"Clé jetable (une machine, {args.duree}). Sur la machine, en root :\n")
            print("\n".join("  " + line for line in network.join_lines(key, args.nom)))
        elif action == "serveur":
            for n in network.server_nodes():
                state = "en ligne" if n["online"] else "hors ligne"
                print(f"{n['name']:<20} {(n['ips'] or ['-'])[0]:<16} {state:<10} "
                      f"{n['host']}")
        return 0
    except network.NetworkError as e:
        print(e, file=sys.stderr)
        return 1


def cmd_journal(args):
    from . import switch_log
    try:
        code, text = switch_log.command(None if args.tout else args.jours)
    except Exception as e:  # noqa: BLE001 — historique illisible
        print(f"Journal illisible : {e}", file=sys.stderr)
        return 1
    print(text, file=sys.stdout if code == 0 else sys.stderr)
    return code


def cmd_projet(args):
    import os
    from . import project_accounts
    try:
        cwd = os.getcwd()
    except OSError as e:
        print(f"Dossier courant introuvable : {e}", file=sys.stderr)
        return 1
    code, text = project_accounts.command(args.args, cwd=cwd)
    print(text, file=sys.stdout if code == 0 else sys.stderr)
    return code


def cmd_raccourcis(args):
    from . import shortcuts
    code, text = shortcuts.command(args.args)
    # L'état sur un autre bureau (code 1) donne les commandes à associer : sortie normale.
    status = not args.args or _status_word(args.args[0]) == "status"
    (sys.stdout if code == 0 or status else sys.stderr).write(text)
    return code


def cmd_statusline(_args):
    from datetime import datetime, timezone
    from . import integration
    payload = integration.read_stdin_json()  # contexte de la session : modèle utilisé…
    try:
        text = integration.statusline_text(_state(), datetime.now(timezone.utc), payload)
    except Exception:  # affichée dans chaque session : jamais de trace Python
        text = "CCS : état illisible"
    print(text)
    return 0


def cmd_hook(args):
    from . import integration
    if args.event == "stop-failure":
        try:
            integration.stop_failure(integration.read_stdin_json())
        except Exception as e:
            print(f"ccs : hook en échec : {e}", file=sys.stderr)
    return 0  # un hook ne doit jamais faire échouer Claude Code


def cmd_integrate(args):
    from . import integration
    try:
        if args.action == "on":
            msgs = integration.install()
            msgs.append("Relance tes sessions Claude Code pour voir la ligne d'état.")
        elif args.action == "off":
            msgs = integration.uninstall()
        else:
            st = integration.status()
            msgs = [
                "Ligne d'état : " + {"ccs": "installée", "autre": "une autre ligne d'état est configurée",
                                     None: "non installée"}[st["statusline"]],
                "Bascule après blocage : " + ("installée" if st["hook"] else "non installée"),
            ]
    except integration.IntegrationError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    print("\n".join(msgs))
    return 0


NOTIFIER_HELP = ("notification bureau du résultat (raccourcis clavier) ; une bascule est notée "
                 "« raccourci » dans le journal")

# Mot d'état des arguments (`pause`, `silence`, `raccourcis`, `integration`) : « etat » dans
# l'aide, « status » (ancien) toujours accepté.
STATUS_WORDS = ("etat", "état", "status")


def _status_word(word):
    """« etat » / « état » → « status », le mot des modules ; le reste inchangé."""
    return "status" if word in STATUS_WORDS else word


def _command(sub, name, help=None, old=(), **kw):
    """Sous-commande `name`. `old` : anciens noms et doublons, acceptés mais absents de l'aide.
    Sans `help`, la commande est interne : acceptée, absente de l'aide."""
    if help is None:
        return sub.add_parser(name, aliases=list(old), **kw)
    parser = sub.add_parser(name, aliases=list(old), help=help, **kw)
    shown = sub._choices_actions[-1]   # ligne de l'aide : le nom seul, sans les anciens
    shown.metavar = shown.dest = name
    return parser


def _old_option(parser, *names, **kw):
    """Ancien nom d'une option : accepté, absent de l'aide (la valeur par défaut vient de
    l'option principale, de même `dest`)."""
    kw.setdefault("default", argparse.SUPPRESS)
    return parser.add_argument(*names, help=argparse.SUPPRESS, **kw)


def _integration_action(text):
    word = _status_word(text)
    if word not in ("on", "off", "status"):
        raise argparse.ArgumentTypeError(f"choix inconnu : « {text} » (on, off, etat)")
    return word


# Commandes qui analysent elles-mêmes leurs options (-C, --droits, --oui…) : argparse ne voit
# pas leurs arguments. (nom, anciens noms, aide, fonction)
SELF_PARSED = (
    ("tache", ("taches", "tasks"), "file de tâches lancées par le service : ajouter, voir, annuler",
     cmd_tache),
    ("budget", (), "budget hebdomadaire par projet", cmd_budget),
    ("fiche", (), "fiche « où j'en étais » d'une conversation", cmd_fiche),
    ("sauvegarde", ("backup",), "sauvegarde chiffrée des profils et réglages", cmd_sauvegarde),
    ("restaurer", ("restore",), "restaure une sauvegarde chiffrée", cmd_restaurer),
    ("telephone", ("phone",), "notifications sur le téléphone : état, lien, essai", cmd_telephone),
    ("root", (), "commande root, mot de passe demandé aux appareils : root -- <commande>, etat, oublier",
     cmd_root),
)
DELEGATED = {n: func for name, old, _help, func in SELF_PARSED for n in (name, *old)}


def build_parser():
    """Toutes les commandes de `claude-accounts` et de `ccs` (hors bascule de profil, propre à
    `bin/ccs`) : c'est la seule table des noms. Les noms affichés sont français ; les anciens
    (anglais, doublons) restent acceptés sans paraître dans l'aide."""
    parser = argparse.ArgumentParser(
        prog="claude-accounts",
        description="Usage, prévisions et bascule entre comptes Claude Code.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<commande>")

    gui = _command(sub, "appli", "ouvre l'application (défaut)", old=["gui", "app"])
    gui.add_argument("--session", metavar="PID:ID",
                     help="affiche cette session Claude Code (pid, identifiant de conversation, "
                          "ou les deux) : clic sur une notification")
    gui.add_argument("--page", metavar="ONGLET", type=_page,
                     help="affiche cet onglet : accueil, sessions, analyse, ou une partie : "
                          "comptes, planning, historique, terminaux, reglages (fenêtre des réglages)")
    gui.add_argument("--tache", dest="task", metavar="ID", type=_task_ref,
                     help="affiche cette tâche dans la section Planning de l'Accueil : clic sur une notification")
    _old_option(gui, "--task", dest="task", type=_task_ref)
    gui.add_argument("--nouvelle-session", dest="new_session", action="store_true",
                     help="ouvre « Nouvelle session… » (dossier, compte, modèle, permissions)")
    _old_option(gui, "--new-session", dest="new_session", action="store_true")
    gui.set_defaults(func=cmd_gui)

    _command(sub, "usage", "affiche l'usage de tous les comptes", old=["print", "u"]).set_defaults(
        func=cmd_print)
    _command(sub, "etat", "compte actif, meilleur compte, capacité", old=["état", "status", "st"]).set_defaults(
        func=cmd_status)
    best = _command(sub, "meilleur", "bascule sur le meilleur compte maintenant", old=["best", "b"])
    best.add_argument("--voir", action="store_true", help="affiche seulement le meilleur compte, sans basculer")
    _old_option(best, "--basculer", "--switch", dest="switch", action="store_true")   # bascule par défaut
    best.add_argument("--notifier", action="store_true", help=NOTIFIER_HELP)
    best.set_defaults(func=cmd_best)
    auto = _command(sub, "auto", "bascule automatique on/off")
    auto.add_argument("state", choices=["on", "off"])
    auto.set_defaults(func=cmd_auto)
    orch = _command(sub, "orchestrateur", "orchestrateur on/off", old=["orch"])
    orch.add_argument("state", choices=["on", "off"])
    orch.set_defaults(func=cmd_orch)
    pa = _command(sub, "pause", "suspend la bascule automatique et l'orchestrateur")
    pa.add_argument("choice", nargs="?", default="status", metavar="1h|4h|demain|manuel|off|etat",
                    help="durée de la pause, « off » pour reprendre, « etat » (défaut) pour l'état")
    pa.add_argument("--notifier", action="store_true", help=NOTIFIER_HELP)
    pa.set_defaults(func=cmd_pause)
    si = _command(sub, "silence", "ne pas déranger : retient les notifications", old=["quiet"])
    si.add_argument("args", nargs="*", metavar="1h|4h|demain|off|reprendre|etat",
                    help="durée du silence, « off » ou « reprendre » pour le lever, « etat » (défaut)")
    si.add_argument("--notifier", action="store_true", help=NOTIFIER_HELP)
    si.set_defaults(func=cmd_silence)
    _command(sub, "plan", "planning des fenêtres de 5 h", old=["planning"]).set_defaults(func=cmd_plan)
    _command(sub, "sessions", "sessions Claude Code ouvertes (mémoire, contexte lourd)",
             old=["ps"]).set_defaults(func=cmd_sessions)
    for name, old, helptext, func in SELF_PARSED:
        p = _command(sub, name, helptext, old=old)
        p.add_argument("args", nargs=argparse.REMAINDER, help="arguments de la commande")
        p.set_defaults(func=func)

    convs = _command(sub, "conversations", "historique des conversations Claude Code du PC",
                     old=["conv", "historique"])
    convs.add_argument("query", nargs="*", help="mots à chercher (titre, demandes, projet)")
    convs.add_argument("-p", "--projet", dest="project", help="nom ou dossier du projet")
    _old_option(convs, "--project", dest="project")
    origin = convs.add_mutually_exclusive_group()
    origin.add_argument("--vscode", action="store_true", help="seulement les conversations de VS Code")
    origin.add_argument("--terminal", action="store_true", help="seulement celles du terminal")
    convs.add_argument("-n", "--limite", dest="limit", type=int, default=30, metavar="N",
                       help="nombre affiché (30 par défaut)")
    _old_option(convs, "--limit", dest="limit", type=int)
    convs.add_argument("--tous", dest="all", action="store_true", help="tout afficher")
    _old_option(convs, "--all", dest="all", action="store_true")
    convs.add_argument("--json", action="store_true", help="sortie JSON")
    convs.set_defaults(func=cmd_conversations)
    res = _command(sub, "reprendre", "reprend une conversation de l'historique", old=["resume"])
    res.add_argument("ref", help="identifiant de la conversation (4 premiers caractères au moins)")
    where = res.add_mutually_exclusive_group()
    where.add_argument("--vscode", action="store_true", help="dans VS Code (extension Claude Code)")
    where.add_argument("--nouveau-terminal", dest="new_terminal", action="store_true",
                       help="dans un nouveau terminal")
    _old_option(where, "--new-terminal", dest="new_terminal", action="store_true")
    where.add_argument("--afficher", dest="print", action="store_true", help="affiche seulement la commande")
    _old_option(where, "--print", dest="print", action="store_true")
    res.add_argument("--dossier", dest="dir", metavar="DOSSIER", help="reprendre depuis ce dossier (projet déplacé)")
    _old_option(res, "--dir", dest="dir")
    res.set_defaults(func=cmd_resume)
    ttl = _command(sub, "titre", "renomme une conversation de l'historique (comme /rename)", old=["title"])
    ttl.add_argument("ref", help="identifiant de la conversation (4 premiers caractères au moins)")
    ttl.add_argument("title", nargs="+", metavar="titre", help="nouveau titre")
    ttl.set_defaults(func=cmd_title)
    pv = _command(sub, "apercu", "affiche une conversation en Markdown, avec son coût",
                  old=["aperçu", "preview"])
    pv.add_argument("ref", help="identifiant de la conversation (4 premiers caractères au moins)")
    pv.set_defaults(func=cmd_preview)
    ex = _command(sub, "exporter", "exporte une conversation dans un fichier Markdown", old=["export"])
    ex.add_argument("ref", help="identifiant de la conversation (4 premiers caractères au moins)")
    ex.add_argument("file", nargs="?", metavar="fichier.md",
                    help="fichier ou dossier de destination (défaut : <titre>.md dans le dossier courant)")
    ex.set_defaults(func=cmd_export)
    an = _command(sub, "analyse", "où part ton usage : projets, modèles, heures, conseils",
                  old=["analyze", "stats"])
    an.add_argument("--jours", dest="days", type=int, default=7, metavar="N", help="N derniers jours (7 par défaut)")
    _old_option(an, "--days", dest="days", type=int)
    an.set_defaults(func=cmd_analyze)
    integ = _command(sub, "integration", "ligne d'état et bascule après blocage dans Claude Code",
                     old=["integrate"])
    integ.add_argument("action", nargs="?", default="status", type=_integration_action,
                       metavar="on|off|etat", help="installe, retire, ou « etat » (défaut)")
    integ.set_defaults(func=cmd_integrate)

    fo = _command(sub, "formule", "conseiller de formule : combien de comptes Pro, Max ou Ultra pour ton usage",
                  old=["conseil"])
    fo.set_defaults(func=cmd_formule)
    se = _command(sub, "semaine", "bilan de la semaine écoulée")
    se.add_argument("--precedente", type=_weeks_back, default=0, metavar="N",
                    help="bilan de N semaines plus tôt (0 : la semaine écoulée)")
    _old_option(se, "--precedent", dest="precedente", type=_weeks_back)
    se.set_defaults(func=cmd_semaine)
    from . import monthly_report
    mo = _command(sub, "mois", "rapport du mois écoulé")
    monthly_report.add_arguments(mo)
    mo.set_defaults(func=cmd_mois)
    bt = _command(sub, "moment", "meilleur moment pour lancer une grosse tâche")
    bt.add_argument("--duree", metavar="3h", help="durée de la tâche (3 h par défaut)")
    bt.add_argument("--sur", metavar="24h", help="horizon cherché (24 h par défaut)")
    bt.set_defaults(func=cmd_moment)
    jo = _command(sub, "journal", "journal des bascules, avec leur raison")
    period = jo.add_mutually_exclusive_group()
    period.add_argument("--jours", type=int, default=7, metavar="N", help="N derniers jours (7 par défaut)")
    _old_option(period, "--days", dest="jours", type=int)
    period.add_argument("--tout", action="store_true", help="tout l'historique gardé")
    jo.set_defaults(func=cmd_journal)
    _command(sub, "bilan", "bilan de santé (code de sortie 1 au moindre problème)", old=["doctor"]).set_defaults(
        func=cmd_doctor)
    mj = _command(sub, "mise-a-jour", "installe la dernière version de CCS (paquet .deb de GitHub)",
                  old=["maj"])
    mj.add_argument("--verifier", action="store_true", help="indique seulement s'il y a une nouvelle version")
    mj.set_defaults(func=cmd_mise_a_jour)
    pr = _command(sub, "projet", "compte par projet : liste, compte d'un dossier, association")
    pr.add_argument("args", nargs="*", metavar="<dossier>|<compte>|aucun",
                    help="sans argument : liste ; un dossier : son compte ; un compte ou « aucun » : "
                         "pour le dossier courant ; dossier puis compte")
    pr.set_defaults(func=cmd_projet)
    ra = _command(sub, "raccourcis", "raccourcis clavier globaux (GNOME)", old=["shortcuts"])
    ra.add_argument("args", nargs="*", metavar="etat|on|off|definir",
                    help="etat (défaut) ; on|off [action…] ; definir <action> <raccourci>")
    ra.set_defaults(func=cmd_raccourcis)
    tu = _command(sub, "tui", "CCS en plein écran dans le terminal")
    tu.add_argument("--serveur", help="nom ou adresse d'un serveur appairé (sinon : cette machine)")
    tu.set_defaults(func=cmd_tui)
    sv = _command(sub, "serveur", "serveurs CCS distants (appairage, liste, retrait)", old=["server"])
    sv_sub = sv.add_subparsers(dest="action", required=True, metavar="<action>")
    sva = sv_sub.add_parser("ajouter", help="appaire ce poste avec un serveur CCS")
    sva.add_argument("cible", help="adresse, par exemple ccs.mawena.cloud")
    sva.add_argument("--nom", help="nom de cet appareil sur le serveur")
    sv_sub.add_parser("liste", help="serveurs appairés")
    svr = sv_sub.add_parser("retirer", help="oublie un serveur")
    svr.add_argument("cible")
    sv.set_defaults(func=cmd_serveur)
    tp = _command(sub, "totp", "double authentification du serveur CCS (root)")
    tp_sub = tp.add_subparsers(dest="action", required=True, metavar="<action>")
    tr = tp_sub.add_parser("reinitialiser", help="efface le code d'un utilisateur")
    tr.add_argument("user", metavar="utilisateur")
    tp.set_defaults(func=cmd_totp)
    di = _command(sub, "distant", "calcul réparti : lancer une commande sur une autre machine (Ricochet)")
    di_sub = di.add_subparsers(dest="action", required=True, metavar="<action>")
    dim = di_sub.add_parser("machines", help="machines du réseau, leur charge et leurs outils")
    dim.add_argument("--vite", action="store_true", help="sans interroger les machines (outils déjà connus)")
    dil = di_sub.add_parser("lancer", help="envoie le projet, lance la commande ailleurs, rapporte les fichiers",
                            usage="ccs distant lancer [options] -- <commande>")
    dil.add_argument("--machine", help="machine voulue (sinon : la moins chargée qui a l'outil)")
    dil.add_argument("--outil", help="outil nécessaire (sinon : le premier mot de la commande)")
    dil.add_argument("--rapatrier", action="append", default=[], metavar="CHEMIN",
                     help="fichier ou dossier produit à rapporter ici (répétable)")
    dil.add_argument("--inclure", action="append", default=[], metavar="CHEMIN",
                     help="envoyer aussi ce chemin que git ignore (répétable)")
    dil.add_argument("--avec-git", action="store_true", help="envoyer aussi le dossier .git")
    dil.add_argument("--quand", default="", metavar="nuit|HH:MM",
                     help="partir la nuit (plage des tâches) ou à cette heure")
    dil.add_argument("--detache", action="store_true",
                     help="en arrière-plan : rend la main tout de suite (journal : ccs distant journal <id>)")
    dil.add_argument("--travail", help=argparse.SUPPRESS)   # interne : travail programmé, relancé par le service
    dil.add_argument("commande", nargs=argparse.REMAINDER, help="la commande, après --")
    diaj = di_sub.add_parser("ajouter", help="ajoute un PC au réseau : donne la commande à coller dessus")
    diaj.add_argument("id", help="identifiant de la machine (lettres, chiffres, - et _)")
    diaj.add_argument("--utilisateur", required=True, help="ton compte sur cette machine")
    diaj.add_argument("--nom", help="nom affiché")
    diaj.add_argument("--limite", type=int, help="travaux à la fois sur cette machine (1 à 8)")
    di_sub.add_parser("travaux", help="commandes lancées : en attente, en cours et finies")
    dia = di_sub.add_parser("arreter", help="arrête un travail (ou le retire de la file)")
    dia.add_argument("id")
    dij = di_sub.add_parser("journal", help="sortie d'un travail détaché")
    dij.add_argument("id")
    di.set_defaults(func=cmd_distant)
    nw = _command(sub, "reseau", "réseau maillé de tous les appareils (network.mawena.cloud)")
    nw_sub = nw.add_subparsers(dest="action", metavar="<action>")
    nw_sub.add_parser("etat", help="appareils et chemin de chaque liaison (LAN, direct, relais)")
    nwp = nw_sub.add_parser("ping", help="chemin et latence réels vers un appareil")
    nwp.add_argument("machine")
    nwc = nw_sub.add_parser("cle", help="clé d'inscription jetable (sur le serveur)")
    nwc.add_argument("--utilisateur", default="charles", help="utilisateur Headscale")
    nwc.add_argument("--duree", default="15m", help="validité (15m, 1h…)")
    nwc.add_argument("--nom", help="nom de la machine dans le réseau")
    nw_sub.add_parser("serveur", help="appareils connus du serveur et leurs adresses publiées")
    nw.set_defaults(func=cmd_reseau)
    ch = _command(sub, "chat", "chats de CCS (commandes pour Claude)")
    ch_sub = ch.add_subparsers(dest="action", required=True, metavar="<action>")
    ch_sub.add_parser("effacer", help="vide la conversation (/clear) à la fin du tour en cours")
    ch.set_defaults(func=cmd_chat)

    # Internes (services systemd, pont, hooks de Claude Code, `ccs … --notifier`) : absentes
    # de l'aide, hors du gel de la 1.0.
    _command(sub, "daemon").set_defaults(func=cmd_daemon)
    _command(sub, "collect").set_defaults(func=cmd_collect)
    _command(sub, "tray").set_defaults(func=cmd_tray)
    _command(sub, "statusline").set_defaults(func=cmd_statusline)
    hook = _command(sub, "hook")
    hook.add_argument("event", choices=["stop-failure"])
    hook.set_defaults(func=cmd_hook)
    nt = _command(sub, "notify")
    nt.add_argument("title", metavar="titre")
    nt.add_argument("body", nargs="?", metavar="texte")
    nt.set_defaults(func=cmd_notify)
    _command(sub, "auth-serve").set_defaults(func=cmd_auth_serve)
    _command(sub, "web-serve").set_defaults(func=cmd_web_serve)
    sd = _command(sub, "shell-distant")
    sd.add_argument("serveur")
    sd.add_argument("cwd")
    sd.set_defaults(func=cmd_shell_distant)
    br = _command(sub, "bridge")
    br.add_argument("--socket")
    br.add_argument("--local", action="store_true")
    br.set_defaults(func=cmd_bridge)
    ec = _command(sub, "est-commande")   # pour `bin/ccs` : ce nom est-il une commande ?
    ec.add_argument("name")
    ec.set_defaults(func=lambda args: 0 if args.name in command_names() else 1)
    return parser


def command_names(parser=None):
    """Tous les noms acceptés (principaux, anciens, internes) des commandes de `claude-accounts`."""
    parser = parser or build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return frozenset(action.choices)
    return frozenset()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    procname.setup(argv)
    # Ancienne option, remplacée par la commande `usage` : acceptée, absente de l'aide.
    if argv[:1] == ["--print"]:
        argv[0] = "usage"
    if argv and argv[0] in DELEGATED:
        return DELEGATED[argv[0]](argparse.Namespace(args=argv[1:])) or 0
    parser = build_parser()
    if argv and not argv[0].startswith("-") and argv[0] not in command_names(parser):
        print(f"ccs : commande ou profil inconnu : {argv[0]} (commandes : ccs aide ; profils : ccs liste)",
              file=sys.stderr)
        return 1
    args = parser.parse_args(argv)
    func = getattr(args, "func", cmd_gui)
    return func(args) or 0
