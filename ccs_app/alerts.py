"""Alertes : quoi notifier, une seule fois par seuil et par fenêtre (pur)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .forecast import effective_percent

# L'API renvoie des heures de réinitialisation qui varient de quelques
# secondes d'un appel à l'autre : on identifie une fenêtre à 10 min près.
WINDOW_ROUND_S = 600
RESET_MOVE = timedelta(minutes=30)
# Une réinitialisation n'est signalée que si le compte était bien entamé :
# avec l'orchestrateur, les fenêtres se renouvellent toutes les 5 h.
RESET_ALERT_MIN = 80


@dataclass
class Alert:
    key: str
    title: str
    body: str
    urgency: int  # 0 bas, 1 normal, 2 critique


def window_id(dt):
    return str(int(round(dt.timestamp() / WINDOW_ROUND_S))) if dt else "none"


def _hhmm(dt):
    return f"{dt.astimezone():%H:%M}"


def _suggestion(best, active):
    if best and best.name != active:
        return f"Meilleur compte : {best.name} ({best.reason}) — ccs {best.name}"
    return ""


def _session_alerts(acc, fc, best, cfg, now, sent):
    s = acc.session
    pct = effective_percent(s, now)
    out = []
    for t in sorted(cfg["session_thresholds"], reverse=True):
        if pct < t:
            continue
        key = f"session{t}:{acc.name}:{window_id(s.resets_at)}"
        if key not in sent:
            out.append(Alert(key, f"{acc.name} : session à {pct:.0f} %",
                             _suggestion(best, acc.name) or "Aucun autre compte disponible.",
                             2 if t >= 95 else 1))
        break  # seul le plus haut seuil franchi compte
    if (fc is not None and fc.verdict == "limit" and fc.eta is not None
            and fc.eta - now <= timedelta(minutes=cfg["eta_minutes"])):
        key = f"eta:{acc.name}:{window_id(s.resets_at if s else None)}"
        if key not in sent:
            body = f"Limite de session estimée vers {_hhmm(fc.eta)}."
            sug = _suggestion(best, acc.name)
            out.append(Alert(key, f"{acc.name} : limite bientôt atteinte",
                             f"{body} {sug}".strip(), 1))
    return out


def _reset_alert(acc, prev, now, sent):
    cur = acc.session
    if prev is None or cur is None or prev.percent < RESET_ALERT_MIN:
        return None
    moved = (cur.resets_at is not None and prev.resets_at is not None
             and cur.resets_at - prev.resets_at > RESET_MOVE)
    if effective_percent(cur, now) > 0 and not moved:
        return None
    key = f"reset:{acc.name}:{window_id(prev.resets_at)}"
    if key in sent:
        return None
    return Alert(key, f"{acc.name} est de nouveau disponible",
                 f"Session réinitialisée ({effective_percent(cur, now):.0f} %).", 0)


def pending_alerts(accounts, active, fc, paces, best, settings, now, sent_keys, previous_sessions):
    cfg = settings["alerts"]
    if not cfg["enabled"]:
        return []
    out = []
    for acc in accounts:
        if acc.name == active and acc.session is not None:
            out += _session_alerts(acc, fc, best, cfg, now, sent_keys)
        if cfg["resets"]:
            a = _reset_alert(acc, previous_sessions.get(acc.name), now, sent_keys)
            if a:
                out.append(a)
        pace = paces.get(acc.name)
        if pace is not None and -pace.margin > cfg["weekly_ahead_points"]:
            key = f"weekly_ahead:{acc.name}:{window_id(acc.weekly.resets_at)}"
            if key not in sent_keys:
                used = acc.weekly.percent
                out.append(Alert(key, f"{acc.name} : semaine en avance sur le rythme",
                                 f"{used:.0f} % utilisés pour {pace.ideal:.0f} % de la semaine "
                                 f"écoulée. Budget : {pace.per_day_budget:.0f} %/jour.", 1))
        if cfg["auth"] and acc.error and "connexion expirée" in acc.error:
            key = f"auth:{acc.name}:{now.date().isoformat()}"
            if key not in sent_keys:
                out.append(Alert(key, f"{acc.name} : connexion expirée",
                                 "Supprime ce profil puis rajoute le compte (ccs add).", 1))
    return out


def decision_alert(decision, now):
    if decision.action == "switch":
        return Alert(f"switch:{now.timestamp():.0f}", f"Bascule automatique vers {decision.target}",
                     decision.reason + ". Les sessions ouvertes suivront à leur prochaine requête.", 1)
    if decision.action == "exhausted":
        reset = None
        if decision.source_reset is not None:
            reset = datetime.fromtimestamp(decision.source_reset, timezone.utc)
        return Alert(f"exhausted:{decision.source}:{window_id(reset)}",
                     "Comptes Claude presque épuisés", decision.reason, 2)
    return None
