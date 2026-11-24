"""`ccs market …` : commandes de Market (Facebook Marketplace au Togo), appelées surtout par
Claude dans le chat Market. Voir `market.py`."""

import dataclasses
import json
import sys

ACTIONS = {"search": "chercher", "seller": "vendeur", "item": "annonce", "status": "etat",
           "login": "connexion"}


def add_parser(sub, command, sub_action):
    """Sous-commande `market` (`command`, `sub_action` : les assistants `_command` et `_action`
    de la CLI ; anciens noms français acceptés, absents de l'aide)."""
    mk = command(sub, "market", "Market : chercher sur Facebook Marketplace au Togo")
    mk_sub = mk.add_subparsers(dest="action", required=True, metavar="<action>")

    def action(name, help):
        return sub_action(mk_sub, name, ACTIONS[name], help)
    s = action("search", "annonces d'une recherche : prix | titre | ville | lien")
    s.add_argument("query", help="mots cherchés")
    s.add_argument("--min", type=int, help="prix minimum (CFA)")
    s.add_argument("--max", type=int, help="prix maximum (CFA)")
    s.add_argument("--city", help="ville Marketplace (défaut : lome)")
    s.add_argument("--limit", type=int, help="annonces au plus")
    v = action("seller", "toutes les annonces d'un vendeur (lien ou numéro)")
    v.add_argument("url")
    v.add_argument("--limit", type=int, help="annonces au plus (défaut : 600)")
    i = action("item", "détails d'une annonce : état, description, vendeur")
    i.add_argument("url")
    action("status", "session Facebook, Chrome, tunnel par pc-bureau")
    action("login", "connexion à Facebook dans Chrome, sur l'écran de pc-bureau (une fois)")
    for p in (s, v, i):
        p.add_argument("--json", action="store_true", help="sortie JSON")
    mk.set_defaults(func=cmd_market)
    return mk


ALIASES = {old: name for name, old in ACTIONS.items()}


def cmd_market(args, market=None):
    if market is None:
        from . import market
    action = ALIASES.get(args.action, args.action)
    err = lambda text: print(text, file=sys.stderr)  # noqa: E731
    try:
        if action == "status":
            ok, text = market.status()
            print(text)
            return 0 if ok else 1
        if action == "login":
            market.login()
            return 0
        if action == "search":
            cards = market.run(lambda fb: fb.search(args.query, args.city, args.min, args.max, args.limit), log=err)
            return _print_cards(cards, args.json, "Aucune annonce pour cette recherche.")
        if action == "seller":
            res = market.run(lambda fb: fb.seller(args.url, args.limit), log=err)
            if args.json:
                print(json.dumps({**res, "items": [dataclasses.asdict(c) for c in res["items"]]},
                                 ensure_ascii=False))
                return 0
            print(f"Vendeur : {res['name'] or '?'} ({res['url']}) : {len(res['items'])} annonces")
            return _print_cards(res["items"], False, "Aucune annonce chez ce vendeur.")
        if action == "item":
            it = market.run(lambda fb: fb.item(args.url), log=err)
            print(json.dumps(it, ensure_ascii=False) if args.json else market.format_item(it))
            return 0
    except market.MarketError as e:
        err(str(e))
        return 2 if isinstance(e, market.TunnelError) else 3 if isinstance(e, market.SessionError) else 1
    except KeyboardInterrupt:
        err("Interrompu.")
        return 130
    return 1


def _print_cards(cards, as_json, empty):
    from . import market
    if as_json:
        print(json.dumps([dataclasses.asdict(c) for c in cards], ensure_ascii=False))
    elif cards:
        print(market.format_cards(cards))
    else:
        print(empty)
    return 0
