"""Accueil et réglages côté pont (version web) : cartes de comptes (rythme, prévision, statut
lisible), bilan de santé, tâches de nuit (journal, suppression) et téléphone (essai, QR code).

Le bureau fait les mêmes textes dans `gui/accounts.py`, qui dépend de GTK : le pont ne peut pas
l'importer sur un serveur sans écran, d'où la copie des quelques fonctions de texte ci-dessous.
"""

import asyncio
import base64
import dataclasses
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

from .. import account_colors, core, daemon, doctor, phone, settings, task_runner, tasks
from ..forecast import weekly_forecast_text
from . import rpc, totp

MAIN_KINDS = ("session", "weekly_all")
ERROR_MAX = 160
LOG_LINES = 300            # lignes de journal renvoyées (la fin)
LOG_BYTES = 512 * 1024     # fin du fichier lue au plus
_HTTP_RE = re.compile(r"^HTTP (\d{3})\s*:?\s*(.*)$", re.S)
_ID_RE = re.compile(r"^[0-9]{1,9}$")


# ---- textes des cartes (mêmes mots que le bureau) ---------------------------------------

def forecast_text(fc, now):
    if not fc or fc.get("verdict") in (None, "unknown"):
        return None
    rate = fc.get("rate_per_min") or 0
    if fc["verdict"] == "limit":
        eta = core.parse_dt(fc.get("eta"))
        mins = fc.get("minutes_before_reset")
        tail = f", {mins:.0f} min avant la réinitialisation" if mins else ""
        return f"⏱ Limite estimée vers {eta.astimezone():%H:%M}{tail}" if eta else None
    if fc["verdict"] == "ok":
        return f"✓ Tient jusqu'à la réinitialisation au rythme actuel ({rate * 60:.0f} %/h)"
    return "Usage stable en ce moment"


def pace_text(pace):
    if not pace:
        return None
    margin, days = pace["margin"], pace["days_left"]
    head = (f"Semaine : {margin:.0f} pts de marge sur le rythme" if margin >= 0
            else f"Semaine : {-margin:.0f} pts d'avance sur le rythme")
    return f"{head} · budget {pace['per_day_budget']:.0f} %/jour ({core.fr(days)} j restants)"


def friendly_error(raw):
    """Erreur d'usage d'un compte dite en clair (jamais le JSON brut de l'API)."""
    text = " ".join(str(raw or "").split())
    m = _HTTP_RE.match(text)
    if m:
        code, rest = int(m.group(1)), m.group(2)
        if code == 401 or "authentication_error" in rest:
            return "Connexion refusée par Anthropic : reconnecte ce compte (« ccs ajouter » dans un terminal)."
        if code == 403:
            return "Accès refusé par Anthropic pour ce compte."
        if code == 429:
            return "Trop de demandes à Anthropic pour l'instant : nouvel essai automatique plus tard."
        if code >= 500:
            return f"Anthropic ne répond pas (erreur {code}) : nouvel essai automatique plus tard."
        message = None
        try:
            data = json.loads(rest)
            err = data.get("error") if isinstance(data, dict) else None
            message = (err or {}).get("message") if isinstance(err, dict) else None
        except ValueError:
            pass
        text = f"Erreur {code} : {message}" if message else f"Erreur {code} de l'API d'Anthropic."
    return text if len(text) <= ERROR_MAX else text[:ERROR_MAX - 1].rstrip() + "…"


def status_of(a, now):
    """{text, kind} : la chose la plus importante à savoir sur un compte, ou None."""
    if a.get("error"):
        stale = f" (données de {core.fmt_time(a['fetched_at'])})" if a.get("limits") and a.get("fetched_at") else ""
        return {"text": f"⚠ {friendly_error(a['error'])}{stale}", "kind": "error"}
    fc, wf = a.get("forecast") or {}, a.get("weekly_forecast") or {}
    if fc.get("verdict") == "limit" and (text := forecast_text(fc, now)):
        return {"text": text, "kind": "warning"}
    if wf.get("verdict") == "limit" and (text := weekly_forecast_text(wf, now)):
        return {"text": text, "kind": "warning"}
    if fc.get("verdict") == "ok" and (text := forecast_text(fc, now)):
        return {"text": text, "kind": "success"}
    return None


def _gauge(lim, now):
    reset = core.parse_dt(lim.get("resets_at"))
    try:
        pct = float(lim.get("percent") or 0)
    except (TypeError, ValueError):
        pct = 0.0
    return {"kind": lim.get("kind"), "label": str(lim.get("label") or ""), "percent": pct,
            "reset": core.fmt_reset(reset, now) if reset else ""}


def _card(a, color, now):
    limits = [lim for lim in (a.get("limits") or []) if isinstance(lim, dict)]
    main = [lim for lim in limits if lim.get("kind") in MAIN_KINDS] or limits[:2]
    others = [lim for lim in limits if lim not in main]
    status = status_of(a, now)
    shown = status["text"] if status else None
    details = []
    for text in (forecast_text(a.get("forecast"), now), pace_text(a.get("pace")),
                 weekly_forecast_text(a.get("weekly_forecast"), now)):
        if text and text != shown:
            details.append(text)
    if a.get("fetched_at") and not a.get("error"):
        details.append(f"Relevé à {core.fmt_time(a['fetched_at'])}")
    return {"name": a.get("name"), "plan": a.get("plan") or "", "email": a.get("email") or "",
            "org": a.get("org") or "", "active": bool(a.get("active")), "color": color,
            "main": [_gauge(g, now) for g in main], "others": [_gauge(g, now) for g in others],
            "status": status, "error_raw": str(a["error"]) if a.get("error") else None,
            "details": details, "fetched_at": a.get("fetched_at"), "has_data": bool(limits)}


class AdminApi:
    def __init__(self, bridge, urlopen=None):
        self.bridge = bridge
        self._urlopen = urlopen or urllib.request.urlopen
        bridge.add_handlers({
            "accounts.cards": self.cards, "doctor.run": self.doctor_run,
            "tasks.log": self.task_log, "tasks.remove": self.task_remove,
            "phone.test": self.phone_test, "phone.new_topic": self.phone_new_topic,
            "phone.qr": self.phone_qr,
        })

    # ---- comptes ---------------------------------------------------------------------

    async def cards(self, _conn, _params):
        def work():
            now = datetime.now(timezone.utc)
            profiles = core.list_profiles()
            names = [p.name for p in profiles]
            chosen = settings.load_settings().get("appearance", {}).get("account_colors") or {}
            state = core.load_json(daemon.state_path())
            accounts = [a for a in (state.get("accounts") or []) if isinstance(a, dict) and a.get("name")]
            if not accounts:
                accounts = [dataclasses.asdict(p) for p in profiles]
            return {"cards": [_card(a, account_colors.color_for(a["name"], names, chosen), now)
                              for a in accounts],
                    "best": state.get("best"), "auto_switch": state.get("auto_switch"),
                    "updated_at": state.get("updated_at")}
        out = await asyncio.to_thread(work)
        chat = getattr(self.bridge, "hubs", {}).get("chat")
        out["running_chats"] = sum(1 for c in (chat.chats.values() if chat else ())
                                   if c.engine is not None and c.engine.state in ("starting", "busy", "permission"))
        return out

    # ---- bilan de santé --------------------------------------------------------------

    async def doctor_run(self, _conn, _params):
        checks = await asyncio.to_thread(doctor.run_checks)
        order = {doctor.ERREUR: 0, doctor.AVERTISSEMENT: 1, doctor.OK: 2}
        checks = sorted(checks, key=lambda c: order.get(c.statut, 3))     # tri stable
        return {"checks": [{"nom": c.nom, "statut": c.statut, "detail": c.detail, "commande": c.commande}
                           for c in checks],
                "errors": sum(c.statut == doctor.ERREUR for c in checks),
                "warnings": sum(c.statut == doctor.AVERTISSEMENT for c in checks),
                "summary": doctor.summary(checks)}

    # ---- tâches ----------------------------------------------------------------------

    @staticmethod
    def _task(params):
        tid = params.get("id")
        if not isinstance(tid, str) or not _ID_RE.match(tid):
            raise rpc.RpcError("invalide", "Numéro de tâche invalide.")
        return tid

    @staticmethod
    def _tail(path):
        try:
            with open(path, "rb") as f:
                size = f.seek(0, os.SEEK_END)
                f.seek(max(0, size - LOG_BYTES))
                data = f.read()
                cut = size > LOG_BYTES
        except OSError:
            return [], False
        raw = data.decode("utf-8", "replace").splitlines()
        if cut:
            raw = raw[1:]            # première ligne probablement coupée
        lines = [t for t in (task_runner.readable(line) for line in raw) if t]
        flat = [part for t in lines for part in t.split("\n")]
        if len(flat) > LOG_LINES:
            return flat[-LOG_LINES:], True
        return flat, cut

    async def task_log(self, _conn, params):
        tid = self._task(params)

        def work():
            task = tasks.get(tid)
            if task is None:
                return None
            lines, truncated = self._tail(tasks.journal_path(tid))
            return {"task": dataclasses.asdict(task), "when": tasks.when_text(task),
                    "summary": tasks.summary(task), "lines": lines, "truncated": truncated}
        out = await asyncio.to_thread(work)
        if out is None:
            raise rpc.RpcError("introuvable", "Tâche inconnue.")
        return out

    async def task_remove(self, _conn, params):
        tid = self._task(params)
        try:
            task = await asyncio.to_thread(tasks.remove, tid)
        except ValueError:
            raise rpc.RpcError("invalide", "Cette tâche est encore active : annule-la d'abord.") from None
        if task is None:
            raise rpc.RpcError("introuvable", "Tâche inconnue.")
        return {}

    # ---- téléphone (ntfy) ------------------------------------------------------------

    async def phone_test(self, _conn, _params):
        ok, message = await asyncio.to_thread(phone.send_test, settings.load_settings(), self._urlopen)
        return {"ok": ok, "message": message}

    async def phone_new_topic(self, _conn, _params):
        topic = phone.new_topic()

        def work():
            s = settings.load_settings()
            s["phone"]["topic"] = topic
            settings.save_settings(s)
        await asyncio.to_thread(work)
        return {"topic": topic}

    async def phone_qr(self, _conn, _params):
        url = phone.subscribe_url(phone.config(await asyncio.to_thread(settings.load_settings)))
        if url is None:
            raise rpc.RpcError("invalide", "Indique un serveur (http:// ou https://) et crée un canal.")
        try:
            svg = await asyncio.to_thread(totp.qr_svg, url)
        except ImportError:
            raise rpc.RpcError("indisponible", "Le QR code demande le paquet python3-qrcode.") from None
        return {"url": url,
                "image": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode("ascii")}
