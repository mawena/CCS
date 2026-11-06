"""Point d'entrée `claude-accounts`."""

import argparse
import json
import sys
import threading

from . import __version__, core


def cmd_print(_args):
    profiles = core.list_profiles()
    if not profiles:
        print("Aucun profil. Enregistre le compte actuel avec : ccs save <nom>")
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


def cmd_gui(_args):
    try:
        from .gui.app import run
    except ImportError as e:
        print(f"Interface graphique indisponible : {e}", file=sys.stderr)
        return 1
    return run()


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
    print("Service : " + ("en marche" if daemon.running_pid() else "arrêté"))
    return 0


def cmd_best(args):
    if not core.list_profiles():
        print("Aucun profil. Enregistre le compte actuel avec : ccs save <nom>")
        return 1
    from . import daemon
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
    best = st.get("best")
    if not best:
        print("Aucun compte disponible pour l'instant.")
        return 1
    print(f"Meilleur compte : {best['name']} — {best['reason']}")
    if not args.switch:
        return 0
    if best["name"] == core.active_profile_name():
        print("C'est déjà le compte actif.")
        return 0
    r = core.run_ccs(["use", best["name"]])
    print((r.stdout + r.stderr).strip())
    if r.returncode == 0:
        daemon.request_refresh()
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
        print("Planning : aucune donnée pour l'instant (démarre le service : ccs status).")
        return 0
    head = "activé" if o.get("enabled") else "désactivé (ccs orch on)"
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
    active = core.active_profile_name() or "compte non enregistré"
    print(f"{len(found)} session(s) ouverte(s) — toutes sur le compte actif : {active}")
    for s in found:
        u = sessions.conversation_usage(s)
        print(f"  {s.project:<16} {sessions.state_label(s):<28} depuis {_duration(time.time() - s.started_at):<9}"
              f" {u.model:<7} {transcripts.fmt_tokens(u.weighted):>8} tokens  (pid {s.pid}, {s.name})")
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
            n = f"{c.prompts} demande{'s' if c.prompts > 1 else ''}"
            print(f"  {c.session_id[:8]}  {conv.ago(c.updated_at):<13} {c.project[:18]:<18} "
                  f"{c.origin_label:<8} {c.title}  {dim}({n}){off}{flag}")
        print()
    if len(found) > len(shown):
        print(f"{dim}… et {len(found) - len(shown)} de plus (--all pour tout afficher){off}")
    where = f" dans {args.project}" if args.project else ""
    print(f"{dim}{len(found)} conversation(s){where}. Reprendre : ccs resume <identifiant> "
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
            hint = f"Indique son nouvel emplacement : ccs resume {args.ref} --dir <dossier>"
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


def cmd_statusline(_args):
    from datetime import datetime, timezone
    from . import integration
    integration.read_stdin_json()  # Claude Code envoie le contexte de la session ; inutile ici
    try:
        text = integration.statusline_text(_state(), datetime.now(timezone.utc))
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


def build_parser():
    parser = argparse.ArgumentParser(
        prog="claude-accounts",
        description="Usage, prévisions et bascule entre comptes Claude Code.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("gui", help="ouvre l'application (défaut)").set_defaults(func=cmd_gui)
    sub.add_parser("print", help="affiche l'usage de tous les comptes").set_defaults(func=cmd_print)
    sub.add_parser("daemon", help="service de collecte (systemd)").set_defaults(func=cmd_daemon)
    sub.add_parser("collect", help="collecte immédiate").set_defaults(func=cmd_collect)
    sub.add_parser("status", help="compte actif, meilleur compte, capacité").set_defaults(func=cmd_status)
    best = sub.add_parser("best", help="meilleur compte maintenant")
    best.add_argument("--switch", action="store_true", help="bascule dessus")
    best.set_defaults(func=cmd_best)
    auto = sub.add_parser("auto", help="bascule automatique on/off")
    auto.add_argument("state", choices=["on", "off"])
    auto.set_defaults(func=cmd_auto)
    orch = sub.add_parser("orch", help="orchestrateur on/off")
    orch.add_argument("state", choices=["on", "off"])
    orch.set_defaults(func=cmd_orch)
    sub.add_parser("plan", help="planning des fenêtres de 5 h").set_defaults(func=cmd_plan)
    sub.add_parser("sessions", help="sessions Claude Code ouvertes").set_defaults(func=cmd_sessions)
    convs = sub.add_parser("conversations", help="historique des conversations Claude Code du PC")
    convs.add_argument("query", nargs="*", help="mots à chercher (titre, demandes, projet)")
    convs.add_argument("-p", "--project", help="nom ou dossier du projet")
    origin = convs.add_mutually_exclusive_group()
    origin.add_argument("--vscode", action="store_true", help="seulement les conversations de VS Code")
    origin.add_argument("--terminal", action="store_true", help="seulement celles du terminal")
    convs.add_argument("-n", "--limit", type=int, default=30, help="nombre affiché (30 par défaut)")
    convs.add_argument("--all", action="store_true", help="tout afficher")
    convs.add_argument("--json", action="store_true", help="sortie JSON")
    convs.set_defaults(func=cmd_conversations)
    res = sub.add_parser("resume", help="reprend une conversation de l'historique")
    res.add_argument("ref", help="identifiant de la conversation (4 premiers caractères au moins)")
    where = res.add_mutually_exclusive_group()
    where.add_argument("--vscode", action="store_true", help="dans VS Code (extension Claude Code)")
    where.add_argument("--new-terminal", action="store_true", help="dans un nouveau terminal")
    where.add_argument("--print", action="store_true", help="affiche seulement la commande")
    res.add_argument("--dir", help="reprendre depuis ce dossier (projet déplacé)")
    res.set_defaults(func=cmd_resume)
    ttl = sub.add_parser("title", help="renomme une conversation de l'historique (comme /rename)")
    ttl.add_argument("ref", help="identifiant de la conversation (4 premiers caractères au moins)")
    ttl.add_argument("title", nargs="+", help="nouveau titre")
    ttl.set_defaults(func=cmd_title)
    sub.add_parser("statusline", help="ligne d'état pour Claude Code").set_defaults(func=cmd_statusline)
    hook = sub.add_parser("hook", help="hooks Claude Code")
    hook.add_argument("event", choices=["stop-failure"])
    hook.set_defaults(func=cmd_hook)
    integ = sub.add_parser("integrate", help="intégration dans Claude Code")
    integ.add_argument("action", choices=["on", "off", "status"])
    integ.set_defaults(func=cmd_integrate)
    sub.add_parser("tray", help="indicateur de la barre du haut").set_defaults(func=cmd_tray)
    an = sub.add_parser("analyze", help="analyse des journaux locaux")
    an.add_argument("--days", type=int, default=7)
    an.set_defaults(func=cmd_analyze)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Compatibilité avec l'ancienne option.
    if argv[:1] == ["--print"]:
        argv[0] = "print"
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", cmd_gui)
    return func(args) or 0
