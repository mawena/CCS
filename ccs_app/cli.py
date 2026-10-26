"""Point d'entrée `claude-accounts`."""

import argparse
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
    sub.add_parser("tray", help="indicateur de la barre du haut").set_defaults(func=cmd_tray)
    an = sub.add_parser("analyze", help="analyse des journaux locaux")
    an.add_argument("--days", type=int, default=7)
    an.set_defaults(func=cmd_analyze)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Compatibilité avec l'ancienne option.
    argv = ["print" if a == "--print" else a for a in argv]
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", cmd_gui)
    return func(args) or 0
