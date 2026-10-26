"""Bascule automatique : décision (pure) et exécution (via `ccs use`)."""

from dataclasses import dataclass

from . import core
from .forecast import best_account, effective_percent

STALE_S = 600
COOLDOWN_S = 300
MANUAL_RESPECT_S = 300
MANUAL_OVERRIDE = 99.5


@dataclass
class Decision:
    action: str  # "none" | "switch" | "exhausted"
    target: str | None
    reason: str
    source: str | None = None
    source_reset: float | None = None


def none(reason):
    return Decision("none", None, reason)


def _blocked_until(a, now, max_session, max_weekly):
    """Moment où le compte redevient utilisable (None si inconnu)."""
    times = []
    for lim in a.limits:
        cap = max_session if lim.kind == "session" else max_weekly
        if effective_percent(lim, now) >= cap and lim.resets_at:
            times.append(lim.resets_at)
    return max(times) if times else None


def decide(accounts, active, fc, settings, now, events, poll_s):
    cfg = settings["auto_switch"]
    if not cfg["enabled"]:
        return none("bascule automatique désactivée")
    if active is None:
        return none("compte actif non enregistré dans un profil")
    act = next((a for a in accounts if a.name == active), None)
    if act is None or not act.limits or act.fetched_at is None:
        return none("pas de données pour le compte actif")
    ts = now.timestamp()
    if ts - act.fetched_at > STALE_S:
        return none("données du compte actif périmées")

    current = act.max_effective(now)
    projected = effective_percent(act.session, now)
    if fc is not None and fc.rate_per_min:
        projected += fc.rate_per_min * poll_s / 60
    if current < cfg["threshold"] and projected < 100:
        return none(f"{active} à {current:.0f} %")

    switches = [e for e in events if e.type == "switch"]
    autos = [e for e in switches if e.detail.get("mode") == "auto"]
    if autos and ts - autos[-1].ts < COOLDOWN_S:
        return none("bascule automatique récente")
    last = switches[-1] if switches else None
    if (last and last.detail.get("mode") == "manual" and last.profile == active
            and ts - last.ts < MANUAL_RESPECT_S and current < MANUAL_OVERRIDE):
        return none("bascule manuelle récente respectée")

    exclude = {active}
    for e in autos:
        left = e.detail.get("from")
        until = e.detail.get("from_reset")
        if left and (until is None or until > ts):
            exclude.add(left)

    # Une cible doit avoir des données fraîches et sans erreur (jeton révoqué,
    # réseau…) : on ne bascule jamais sur la foi d'un vieux pourcentage.
    eligible = [a for a in accounts if a.name == active or
                (not a.error and a.fetched_at is not None and ts - a.fetched_at <= STALE_S)]
    source_reset = act.session.resets_at.timestamp() if act.session and act.session.resets_at else None
    rec = best_account(eligible, now, exclude,
                       max_session=cfg["target_max_session"], max_weekly=cfg["target_max_weekly"])
    if rec:
        return Decision("switch", rec.name,
                        f"{active} à {current:.0f} % → {rec.name} ({rec.reason})",
                        active, source_reset)

    upcoming = []
    for a in eligible:
        if a.name == active or not a.limits:
            continue
        t = _blocked_until(a, now, cfg["target_max_session"], cfg["target_max_weekly"])
        if t:
            upcoming.append((t, a.name))
    if upcoming:
        t, name = min(upcoming)
        nxt = f"prochain disponible : {name} à {t.astimezone():%H:%M}"
    else:
        nxt = "prochain disponible : inconnu"
    return Decision("exhausted", None,
                    f"tous les comptes sont presque épuisés ; {nxt}", active, source_reset)


def execute(decision, store, now):
    if decision.action != "switch":
        return False
    r = core.run_ccs(["use", decision.target])
    ts = now.timestamp()
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().replace("ccs: ", "")
        store.add_event(ts, "error", decision.target, {"op": "auto_switch", "message": msg})
        return False
    store.add_event(ts, "switch", decision.target, {
        "mode": "auto", "from": decision.source, "from_reset": decision.source_reset,
        "reason": decision.reason})
    return True
