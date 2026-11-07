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


def cmd_gui(args):
    try:
        from .gui.app import run
    except ImportError as e:
        print(f"Interface graphique indisponible : {e}", file=sys.stderr)
        return 1
    return run(session=getattr(args, "session", None), page=getattr(args, "page", None),
               new_session=getattr(args, "new_session", False))


def _page(text):
    """Option --page : nom réel d'un onglet ou son titre en français."""
    from .desktop import PAGE_CHOICES, page_name
    name = page_name(text)
    if name is None:
        raise argparse.ArgumentTypeError(f"onglet inconnu : « {text} » ({', '.join(PAGE_CHOICES)})")
    return name


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
    code, message = pause.command(args.choice, now)
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


def cmd_best(args):
    notifier = getattr(args, "notifier", False)

    def notice(title, body=""):
        if notifier:
            _notify(title, body)
    if not core.list_profiles():
        print("Aucun profil. Enregistre le compte actuel avec : ccs save <nom>")
        notice("Bascule impossible", "Aucun profil : enregistre le compte actuel avec « ccs save <nom> ».")
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
    best = st.get("best")
    if not best:
        print("Aucun compte disponible pour l'instant.")
        notice("Aucun compte disponible", "Tous les comptes sont épuisés ou indisponibles pour l'instant.")
        return 1
    name = best["name"]
    print(f"Meilleur compte : {name} — {best['reason']}")
    if not args.switch:
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


def _conversation(ref):
    """Conversation désignée comme pour `ccs resume` / `ccs title` ; None (erreur affichée) sinon."""
    from . import conversations as conv
    try:
        return conv.find(conv.scan(), ref)
    except LookupError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return None


def _cost_text(c):
    from . import costs
    return costs.format_cost(costs.conversation_cost(c.path))


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
    except BrokenPipeError:  # `ccs preview … | head` : lecteur parti, pas de trace Python
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
    status = not args.args or args.args[0] in ("status", "etat", "état")
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


def build_parser():
    parser = argparse.ArgumentParser(
        prog="claude-accounts",
        description="Usage, prévisions et bascule entre comptes Claude Code.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    gui = sub.add_parser("gui", help="ouvre l'application (défaut)")
    gui.add_argument("--session", metavar="PID:ID",
                     help="affiche cette session Claude Code (pid, identifiant de conversation, "
                          "ou les deux) : clic sur une notification")
    gui.add_argument("--page", metavar="ONGLET", type=_page,
                     help="affiche cet onglet : sessions, comptes, planning, historique, analyse, "
                          "terminaux ou reglages")
    gui.add_argument("--new-session", action="store_true",
                     help="ouvre « Nouvelle session… » (dossier, compte, modèle, permissions)")
    gui.set_defaults(func=cmd_gui)
    sub.add_parser("print", help="affiche l'usage de tous les comptes").set_defaults(func=cmd_print)
    sub.add_parser("daemon", help="service de collecte (systemd)").set_defaults(func=cmd_daemon)
    sub.add_parser("collect", help="collecte immédiate").set_defaults(func=cmd_collect)
    sub.add_parser("status", help="compte actif, meilleur compte, capacité").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="bilan de santé (code de sortie 1 au moindre problème)").set_defaults(
        func=cmd_doctor)
    pa = sub.add_parser("pause", help="suspend la bascule automatique et l'orchestrateur")
    pa.add_argument("choice", nargs="?", default="status", metavar="1h|4h|demain|manuel|off|status",
                    help="durée de la pause, « off » pour reprendre, « status » (défaut) pour l'état")
    pa.add_argument("--notifier", action="store_true", help=NOTIFIER_HELP)
    pa.set_defaults(func=cmd_pause)
    best = sub.add_parser("best", help="meilleur compte maintenant")
    best.add_argument("--switch", action="store_true", help="bascule dessus")
    best.add_argument("--notifier", action="store_true", help=NOTIFIER_HELP)
    best.set_defaults(func=cmd_best)
    fo = sub.add_parser("formule", aliases=["conseil"],
                        help="conseiller de formule : combien de comptes Pro, Max ou Ultra pour ton usage")
    fo.set_defaults(func=cmd_formule)
    se = sub.add_parser("semaine", help="bilan de la semaine écoulée")
    se.add_argument("--precedente", type=_weeks_back, default=0, metavar="N",
                    help="bilan de N semaines plus tôt (0 : la semaine écoulée)")
    se.set_defaults(func=cmd_semaine)
    jo = sub.add_parser("journal", help="journal des bascules, avec leur raison")
    period = jo.add_mutually_exclusive_group()
    period.add_argument("--jours", type=int, default=7, metavar="N", help="N derniers jours (7 par défaut)")
    period.add_argument("--tout", action="store_true", help="tout l'historique gardé")
    jo.set_defaults(func=cmd_journal)
    pr = sub.add_parser("projet", help="compte par projet : liste, compte d'un dossier, association")
    pr.add_argument("args", nargs="*", metavar="<dossier>|<compte>|aucun",
                    help="sans argument : liste ; un dossier : son compte ; un compte ou « aucun » : "
                         "pour le dossier courant ; dossier puis compte")
    pr.set_defaults(func=cmd_projet)
    ra = sub.add_parser("raccourcis", aliases=["shortcuts"], help="raccourcis clavier globaux (GNOME)")
    ra.add_argument("args", nargs="*", metavar="status|on|off|set",
                    help="status (défaut) ; on|off [action…] ; set <action> <raccourci>")
    ra.set_defaults(func=cmd_raccourcis)
    nt = sub.add_parser("notify", help="notification bureau (pour ccs … --notifier)")
    nt.add_argument("title", metavar="titre")
    nt.add_argument("body", nargs="?", metavar="texte")
    nt.set_defaults(func=cmd_notify)
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
    pv = sub.add_parser("preview", aliases=["apercu"],
                        help="affiche une conversation en Markdown, avec son coût")
    pv.add_argument("ref", help="identifiant de la conversation (4 premiers caractères au moins)")
    pv.set_defaults(func=cmd_preview)
    ex = sub.add_parser("export", help="exporte une conversation dans un fichier Markdown")
    ex.add_argument("ref", help="identifiant de la conversation (4 premiers caractères au moins)")
    ex.add_argument("file", nargs="?", metavar="fichier.md",
                    help="fichier ou dossier de destination (défaut : <titre>.md dans le dossier courant)")
    ex.set_defaults(func=cmd_export)
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
