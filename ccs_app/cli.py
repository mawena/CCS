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


def build_parser():
    parser = argparse.ArgumentParser(
        prog="claude-accounts",
        description="Usage, prévisions et bascule entre comptes Claude Code.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("gui", help="ouvre l'application (défaut)").set_defaults(func=cmd_gui)
    sub.add_parser("print", help="affiche l'usage de tous les comptes").set_defaults(func=cmd_print)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Compatibilité avec l'ancienne option.
    argv = ["print" if a == "--print" else a for a in argv]
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", cmd_gui)
    return func(args) or 0
