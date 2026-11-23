"""Jarvis aux commandes de tout le réseau CCS : sessions, sous-agents, machines et travaux de
toutes les machines, par des méthodes faites pour une IA (réponses compactes, noms approchés).

Sessions d'une machine (`jarvis.local`) : les chats du pont (`kind: "chat"`, pilotables) et les
sessions Claude Code ouvertes dans un terminal (`kind: "terminal"`, fiches `~/.claude/sessions`,
arrêtables en bloc seulement). Les autres machines sont jointes comme pour `machines.attach`
(ssh vers leur pont local, `MachinesApi.connect`), le temps d'un appel, toutes en même temps.

Cibles tolérantes : « la session GliGli » → nom approché (casse, accents, espaces et petits mots
ignorés) sur le titre, le nom de session ou le dossier du projet ; « le premier sous-agent » →
`index: 1` (ou « premier », « dernier »…) parmi les sous-agents qui tournent encore, dans l'ordre
de lancement. Actions destructrices (`jarvis.stop_subagent`, `jarvis.stop_session`) : sans
`confirme: true`, rien n'est fait et la réponse décrit la cible résolue et la question à poser.

Une action sur une autre machine y est renvoyée avec la cible exacte (`chat_id`, `tool_id`,
`pid`, `cwd`) et `local: true` : la machine visée agit chez elle, sans chercher plus loin.
Protocole détaillé : `docs/jarvis.md`.
"""

import asyncio
import difflib
import logging
import os
import re
import socket
import unicodedata

from .. import distant, distant_jobs, project_list, sessions, subagents
from . import rpc
from .bridge_chat import journal_title, transcript_of

log = logging.getLogger("ccs.bridge.pilot")

REMOTE_TIMEOUT = 20          # secondes pour joindre une autre machine et lui répondre
RECENT_JOBS = 5              # travaux finis montrés dans `jarvis.state`
STATES = {"starting": "working", "busy": "working", "permission": "waiting", "waiting": "waiting",
          "idle": "idle", "suspended": "suspended", "stopped": "stopped"}
STATE_LABELS = {"working": "au travail", "waiting": "attend une réponse", "idle": "au repos",
                "suspended": "en veille", "stopped": "arrêtée"}
JOB_LABELS = distant_jobs.LABELS
SMALL_WORDS = {"la", "le", "les", "l", "un", "une", "session", "sessions", "projet", "projets",
               "conversation", "chat", "de", "du", "des", "d", "sur", "machine", "pc", "the"}
ORDINALS = {"premier": 1, "premiere": 1, "1er": 1, "1re": 1, "un": 1, "une": 1,
            "deuxieme": 2, "second": 2, "seconde": 2, "2e": 2, "deux": 2,
            "troisieme": 3, "3e": 3, "trois": 3, "quatrieme": 4, "4e": 4, "quatre": 4,
            "cinquieme": 5, "5e": 5, "cinq": 5, "sixieme": 6, "septieme": 7, "huitieme": 8,
            "neuvieme": 9, "dixieme": 10, "dernier": -1, "derniere": -1}


# ---- noms approchés -------------------------------------------------------------------------

def fold(text):
    """Minuscules, sans accents ; tout ce qui n'est ni lettre ni chiffre devient espace ; les
    petits mots (« la session », « de ») sont retirés. « La session Gli-Gli » → « gli gli »."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    kept = [w for w in words if w not in SMALL_WORDS]
    return " ".join(kept or words)


def score(query, label):
    """Ressemblance de 0 à 100 entre ce qui a été dit et un nom."""
    q, lab = fold(query), fold(label)
    if not q or not lab:
        return 0
    qc, lc = q.replace(" ", ""), lab.replace(" ", "")
    if q == lab or qc == lc:
        return 100
    if lc.startswith(qc) or (f" {q} " in f" {lab} "):
        return 85
    if qc in lc:
        return 70
    ratio = difflib.SequenceMatcher(None, qc, lc).ratio()
    return int(ratio * 60) if ratio >= 0.7 else 0


def best(query, items, labels):
    """Éléments de `items` les mieux notés (liste vide si aucun ne ressemble). `labels(item)` :
    noms possibles de l'élément."""
    scored = [(max((score(query, lab) for lab in labels(it) if lab), default=0), n, it)
              for n, it in enumerate(items)]
    top = max((s for s, _, _ in scored), default=0)
    return [it for s, _, it in scored if top and s == top]


def ordinal(value):
    """Rang donné par Jarvis : entier (1 = premier, -1 = dernier) ou mot (« premier »,
    « deuxième », « dernier »…). None si absent ; `RpcError` s'il est illisible."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise rpc.RpcError("invalide", "Rang invalide.")
    if isinstance(value, int):
        n = value
    elif isinstance(value, str):
        word = fold(value).replace(" ", "")
        n = int(word) if word.lstrip("-").isdigit() else ORDINALS.get(word)
        if n is None:
            raise rpc.RpcError("invalide", f"Rang incompris : « {value} ».")
    else:
        raise rpc.RpcError("invalide", "Rang invalide.")
    if n == 0:
        raise rpc.RpcError("invalide", "Le premier rang est 1 (ou -1 pour le dernier).")
    return n


def pick(items, n):
    """Élément de rang `n` (1 = premier, -1 = dernier), ou None."""
    if n is None or not items:
        return None
    i = n - 1 if n > 0 else len(items) + n
    return items[i] if 0 <= i < len(items) else None


def _confirmed(params):
    return params.get("confirme") is True or params.get("confirm") is True


def _subagent_view(item):
    keep = ("index", "active_index", "description", "type", "state", "background", "started",
            "ended", "summary", "tool_id", "task_id")
    return {k: item.get(k) for k in keep}


def _session_labels(s):
    return [s.get("title"), s.get("name"), s.get("project"), os.path.basename(s.get("cwd") or ""),
            s.get("session_id"), s.get("chat_id")]


def _describe(s):
    where = s.get("machine_name") or s.get("machine") or ""
    return f"{s.get('name')} ({where})" if where else str(s.get("name"))


class PilotApi:
    def __init__(self, bridge, machines=None, chats=None, list_terminal=None, terminate=None,
                 timeout=REMOTE_TIMEOUT):
        self.bridge = bridge
        self.machines = machines            # MachinesApi : liste et liens vers les autres ponts
        self.chats = chats                  # ChatHub : chats de ce pont
        self._list_terminal = list_terminal or sessions.list_sessions
        self._terminate = terminate or sessions.terminate
        self.timeout = timeout
        bridge.add_handlers({
            "jarvis.state": self.state, "jarvis.sessions": self.sessions,
            "jarvis.subagents": self.subagents, "jarvis.stop_subagent": self.stop_subagent,
            "jarvis.stop_session": self.stop_session, "jarvis.start_session": self.start_session,
            "jarvis.local": self.local, "jarvis.projects": self.projects})

    # ---- cette machine ---------------------------------------------------------------------

    def _local_sessions(self):
        """Sessions de cette machine (dans un fil) : chats du pont puis sessions de terminal."""
        out, seen_ids, seen_pids = [], set(), set()
        terminal = []
        try:
            terminal = self._list_terminal()
        except Exception:
            log.exception("sessions de terminal illisibles")
        names = {t.session_id: t.name for t in terminal if t.session_id}
        for chat in list((self.chats.chats if self.chats else {}).values()):
            engine = chat.engine
            sid = engine.session_id or ""
            path = transcript_of(chat.cwd, sid)
            title = journal_title(path) or ""
            items = subagents.numbered(subagents.merge(chat.agents.items(),
                                                       subagents.from_transcript(path)))
            seen_ids.add(sid)
            if engine.pid:
                seen_pids.add(engine.pid)
            out.append(self._session("chat", chat_id=chat.chat_id, pid=engine.pid, session_id=sid,
                                     title=title, label=names.get(sid, ""), cwd=chat.cwd,
                                     raw_state=engine.state, started=chat.opened_at,
                                     items=items, devices=len(chat.conns)))
        for t in terminal:
            if t.session_id in seen_ids or t.pid in seen_pids:
                continue
            path = sessions.transcript_path(t.cwd, t.session_id) if t.session_id else None
            title = ""
            if t.session_id:
                try:
                    title = sessions.conversation_title(t.cwd, t.session_id) or ""
                except Exception:
                    title = ""
            items = subagents.numbered(subagents.from_transcript(path))
            out.append(self._session("terminal", chat_id=None, pid=t.pid, session_id=t.session_id,
                                     title=title, label=t.name, cwd=t.cwd, raw_state=t.state,
                                     started=t.started_at, items=items, devices=0,
                                     proc_start=t.proc_start))
        return out

    @staticmethod
    def _session(kind, *, chat_id, pid, session_id, title, label, cwd, raw_state, started, items,
                 devices, proc_start=None):
        state = STATES.get(raw_state, "idle")
        project = os.path.basename(os.path.normpath(cwd)) if cwd else ""
        label = "" if label and str(label).isdigit() else (label or "")
        return {"kind": kind, "chat_id": chat_id, "pid": pid, "proc_start": proc_start,
                "session_id": session_id or "", "name": title or label or project or "?",
                "title": title, "label": label, "project": project, "cwd": cwd,
                "state": state, "state_label": STATE_LABELS[state], "started": started,
                "devices": devices, "subagents": [_subagent_view(i) for i in items],
                "subagents_running": sum(1 for i in items if i["state"] == "running"),
                "subagents_stoppable": kind == "chat"}

    async def local(self, _conn, _params):
        """Sessions de cette machine seulement (appelé par le serveur sur chaque machine)."""
        return {"sessions": await asyncio.to_thread(self._local_sessions)}

    def _local_projects(self):
        seen, out = set(), []
        try:
            listing = project_list.load()
            added = list((listing.get("added") or {}).keys())
            removed = set((listing.get("removed") or {}).keys())
        except Exception:
            added, removed = [], set()
        try:
            recent = [cwd for cwd, _ in sessions.recent_projects(limit=60)]
        except Exception:
            recent = []
        for cwd in recent + added:
            if cwd in seen or cwd in removed or not os.path.isdir(cwd):
                continue
            seen.add(cwd)
            out.append({"name": os.path.basename(os.path.normpath(cwd)) or cwd, "cwd": cwd})
        return out

    async def projects(self, _conn, _params):
        """Projets connus de cette machine (`{name, cwd}`), pour `jarvis.start_session`."""
        return {"projects": await asyncio.to_thread(self._local_projects)}

    # ---- le réseau -------------------------------------------------------------------------

    async def _machine_list(self):
        """Machines du réseau (vue de `machines.list`) ; celle-ci en tête. Sans calcul réparti
        réglé, cette machine seule."""
        overview = {"machines": []}
        if self.machines is not None:
            try:
                overview = await asyncio.to_thread(distant.machines_overview, self.machines._fetch)
            except Exception:
                log.exception("liste des machines")
        found = [dict(m) for m in overview.get("machines") or []]
        if not any(m.get("local") for m in found):
            host = socket.gethostname()
            found.append({"id": host, "name": host, "online": True, "local": True})
        found.sort(key=lambda m: not m.get("local"))
        return found

    def _resolve_machine(self, machines, wanted):
        if wanted is None or wanted == "":
            return None
        if not isinstance(wanted, str):
            raise rpc.RpcError("invalide", "Machine invalide.")
        hits = best(wanted, machines, lambda m: [m.get("id"), m.get("name"), m.get("mesh")])
        if not hits:
            known = ", ".join(m.get("id") for m in machines)
            raise rpc.RpcError("introuvable", f"Machine « {wanted} » inconnue (connues : {known}).")
        if len(hits) > 1:
            raise rpc.RpcError("conflit", "Plusieurs machines correspondent : "
                               + ", ".join(m["id"] for m in hits) + ".")
        return hits[0]

    async def _call(self, machine_id, method, **params):
        """Appel d'une méthode sur le pont d'une autre machine, le temps d'une requête."""
        if self.machines is None:
            raise rpc.RpcError("introuvable", "Autres machines indisponibles.")
        _m, link, _hello = await self.machines.connect(machine_id, timeout=self.timeout)
        try:
            return await asyncio.wait_for(link.client.call(method, **params), self.timeout)
        except asyncio.TimeoutError:
            raise rpc.RpcError("introuvable", f"{machine_id} : délai dépassé.") from None
        except ConnectionError:
            raise rpc.RpcError("introuvable", f"{machine_id} : lien coupé.") from None
        finally:
            await link.close()

    async def _remote_sessions(self, machine_id):
        try:
            return (await self._call(machine_id, "jarvis.local")).get("sessions") or []
        except rpc.RpcError as e:
            if not e.message.startswith("Méthode inconnue"):
                raise
        # pont d'une version sans Jarvis : ses chats seulement, sans sous-agents
        chats = (await self._call(machine_id, "chat.list")).get("chats") or []
        return [self._session("chat", chat_id=c.get("chat_id"), pid=c.get("pid"),
                              session_id=c.get("session_id"), title=c.get("title") or "", label="",
                              cwd=c.get("cwd") or "", raw_state=c.get("state"), started=None,
                              items=[], devices=c.get("devices") or 0) for c in chats]

    async def _gather(self, machines=None, only=None):
        """(machines, sessions, erreurs) de tout le réseau, ou de la machine `only` seulement."""
        machines = machines if machines is not None else await self._machine_list()
        targets = [m for m in machines if only is None or m["id"] == only["id"]]

        async def one(m):
            if m.get("local"):
                return await asyncio.to_thread(self._local_sessions)
            if not m.get("online"):
                raise rpc.RpcError("introuvable", f"{m['id']} est hors ligne.")
            return await self._remote_sessions(m["id"])

        results = await asyncio.gather(*(one(m) for m in targets), return_exceptions=True)
        found, errors = [], []
        for m, res in zip(targets, results):
            m["reachable"] = not isinstance(res, BaseException)
            if isinstance(res, BaseException):
                msg = res.message if isinstance(res, rpc.RpcError) else str(res) or type(res).__name__
                if not isinstance(res, rpc.RpcError):
                    log.warning("sessions de %s : %r", m["id"], res)
                if m.get("online"):
                    errors.append({"machine": m["id"], "message": msg})
                continue
            for s in res:
                s["machine"], s["machine_name"] = m["id"], m.get("name") or m["id"]
                s["local_machine"] = bool(m.get("local"))
                found.append(s)
        return machines, found, errors

    async def _target_session(self, params):
        """Session visée : exacte (`chat_id` ou `pid`, avec `local: true` : cette machine), sinon
        par nom approché (`session`) sur la machine donnée ou tout le réseau."""
        if params.get("local") is True:
            mine = await asyncio.to_thread(self._local_sessions)
            chat_id, pid = params.get("chat_id"), params.get("pid")
            for s in mine:
                if (chat_id and s["chat_id"] == chat_id) or (pid and s["pid"] == pid and not chat_id):
                    s["machine"], s["local_machine"] = None, True
                    return s
            raise rpc.RpcError("introuvable", "Session introuvable ou déjà fermée.")
        wanted = params.get("session")
        if wanted is None or wanted == "":
            raise rpc.RpcError("invalide", "Session manquante (nom approché ou rang).")
        machines = await self._machine_list()
        machine = self._resolve_machine(machines, params.get("machine"))
        _m, found, errors = await self._gather(machines, machine)
        rank = None
        if isinstance(wanted, int) and not isinstance(wanted, bool):
            rank = ordinal(wanted)
        elif isinstance(wanted, str) and fold(wanted).replace(" ", "") in ORDINALS:
            rank = ordinal(wanted)
        if rank is not None:
            hit = pick(found, rank)
            if hit is None:
                raise rpc.RpcError("introuvable", f"Pas de session de rang {wanted}.")
            return hit
        if not isinstance(wanted, str):
            raise rpc.RpcError("invalide", "Session invalide.")
        hits = best(wanted, found, _session_labels)
        if not hits:
            names = ", ".join(_describe(s) for s in found) or "aucune"
            extra = " (" + "; ".join(f"{e['machine']} : {e['message']}" for e in errors) + ")" if errors else ""
            raise rpc.RpcError("introuvable", f"Aucune session ne ressemble à « {wanted} ». "
                               f"Sessions ouvertes : {names}.{extra}")
        if len(hits) > 1:
            raise rpc.RpcError("conflit", f"Plusieurs sessions correspondent à « {wanted} » : "
                               + ", ".join(_describe(s) for s in hits)
                               + ". Précise la machine ou le nom.")
        return hits[0]

    @staticmethod
    def _summary(machines, found, jobs):
        online = sum(1 for m in machines if m.get("online"))
        working = sum(1 for s in found if s["state"] == "working")
        waiting = sum(1 for s in found if s["state"] == "waiting")
        agents = sum(s["subagents_running"] for s in found)
        active_jobs = sum(1 for j in jobs if j["state"] in distant_jobs.ACTIVE)
        return (f"{online} machine{'s' if online > 1 else ''} en ligne sur {len(machines)} ; "
                f"{len(found)} session{'s' if len(found) > 1 else ''} ({working} au travail, "
                f"{waiting} en attente de réponse) ; {agents} sous-agent{'s' if agents > 1 else ''} "
                f"en cours ; {active_jobs} "
                + ("travaux distants actifs." if active_jobs > 1 else "travail distant actif."))

    @staticmethod
    def _jobs():
        try:
            jobs = distant_jobs.list_jobs()
        except Exception:
            log.exception("travaux distants illisibles")
            return []
        active = [j for j in jobs if j.get("state") in distant_jobs.ACTIVE]
        done = [j for j in jobs if j.get("state") not in distant_jobs.ACTIVE][:RECENT_JOBS]
        return [{"id": j.get("id"), "command": j.get("text"), "machine": j.get("machine"),
                 "state": j.get("state"), "state_label": JOB_LABELS.get(j.get("state"), j.get("state")),
                 "code": j.get("code"), "cwd": j.get("cwd"), "created": j.get("created"),
                 "ended": j.get("ended")} for j in active + done]

    # ---- lecture ---------------------------------------------------------------------------

    async def state(self, _conn, _params):
        """Vue compacte de tout le réseau : machines, sessions (sous-agents en cours seulement),
        travaux distants, erreurs et un résumé en une phrase."""
        machines, found, errors = await self._gather()
        jobs = await asyncio.to_thread(self._jobs)
        view_machines = [{k: m.get(k) for k in ("id", "name", "online", "local", "reachable",
                                                 "cores", "load", "mem_used", "mem_total",
                                                 "running", "waiting")} for m in machines]
        view_sessions = []
        for s in found:
            s = dict(s)
            s["subagents"] = [a for a in s["subagents"] if a["state"] == "running"]
            view_sessions.append(s)
        return {"summary": self._summary(machines, found, jobs), "machines": view_machines,
                "sessions": view_sessions, "jobs": jobs, "errors": errors}

    async def sessions(self, _conn, params):
        """Sessions de tout le réseau (ou de `machine`), sous-agents compris."""
        machines = await self._machine_list()
        machine = self._resolve_machine(machines, params.get("machine"))
        _m, found, errors = await self._gather(machines, machine)
        return {"sessions": found, "errors": errors}

    async def subagents(self, _conn, params):
        """Sous-agents d'une session, dans l'ordre de lancement."""
        s = await self._target_session(params)
        items = s.pop("subagents")
        return {"session": s, "subagents": items}

    # ---- actions ---------------------------------------------------------------------------

    @staticmethod
    def _choose_subagent(s, params):
        items = s["subagents"]
        tool_id = params.get("tool_id")
        if tool_id:
            hit = next((a for a in items if a["tool_id"] == tool_id), None)
            if hit is None:
                raise rpc.RpcError("introuvable", "Sous-agent introuvable dans cette session.")
            return hit
        running = [a for a in items if a["state"] == "running"]
        if not running:
            raise rpc.RpcError("introuvable", f"Aucun sous-agent ne tourne dans la session {s['name']}.")
        rank = ordinal(params.get("index"))
        if rank is None:
            if len(running) == 1:
                return running[0]
            raise rpc.RpcError("conflit", f"{len(running)} sous-agents tournent dans {s['name']} : "
                               + "; ".join(f"{a['active_index']}. {a['description']}" for a in running)
                               + ". Lequel ?")
        hit = pick(running, rank)
        if hit is None:
            raise rpc.RpcError("introuvable", f"Pas de sous-agent de rang {params.get('index')} en cours "
                               f"dans {s['name']} ({len(running)} en cours).")
        return hit

    @staticmethod
    def _target_view(s, agent=None):
        out = {"machine": s.get("machine"), "machine_name": s.get("machine_name"),
               "session": s["name"], "kind": s["kind"], "chat_id": s["chat_id"], "pid": s["pid"],
               "project": s["project"], "state": s["state"]}
        if agent is not None:
            out["subagent"] = {k: agent.get(k) for k in ("active_index", "index", "description",
                                                         "type", "tool_id", "task_id")}
        return out

    async def stop_subagent(self, _conn, params):
        s = await self._target_session(params)
        agent = self._choose_subagent(s, params)
        target = self._target_view(s, agent)
        where = f" sur {s.get('machine_name') or s.get('machine')}" if s.get("machine") else ""
        if s["kind"] != "chat":
            raise rpc.RpcError("refuse", f"La session {s['name']}{where} tourne dans un terminal : "
                               "CCS ne peut pas arrêter un de ses sous-agents seul (seulement toute "
                               "la session, par jarvis.stop_session).")
        if not _confirmed(params):
            return {"done": False, "confirm_needed": True, "action": "stop_subagent",
                    "target": target,
                    "question": f"Arrêter le sous-agent {agent['active_index']} « {agent['description']} » "
                                f"de la session {s['name']}{where} ?"}
        if not s.get("local_machine"):
            res = await self._call(s["machine"], "jarvis.stop_subagent", local=True,
                                   chat_id=s["chat_id"], tool_id=agent["tool_id"], confirme=True)
            return dict(res, target=target)
        chat = self.chats.chats.get(s["chat_id"]) if self.chats else None
        if chat is None:
            raise rpc.RpcError("introuvable", "Session fermée entre-temps.")
        if not agent.get("task_id"):
            raise rpc.RpcError("introuvable", "Identifiant de tâche du sous-agent inconnu "
                               "(Claude Code trop ancien ?) : impossible de l'arrêter seul.")
        if not await asyncio.to_thread(chat.engine.stop_task, agent["task_id"]):
            raise rpc.RpcError("interne", "Claude Code ne tourne plus dans cette session.")
        return {"done": True, "target": target,
                "message": f"Arrêt demandé pour le sous-agent « {agent['description']} »."}

    async def stop_session(self, _conn, params):
        s = await self._target_session(params)
        target = self._target_view(s)
        where = f" sur {s.get('machine_name') or s.get('machine')}" if s.get("machine") else ""
        if not _confirmed(params):
            extra = f", avec {s['subagents_running']} sous-agent(s) en cours" if s["subagents_running"] else ""
            return {"done": False, "confirm_needed": True, "action": "stop_session", "target": target,
                    "question": f"Arrêter la session {s['name']}{where} ({s['state_label']}{extra}) ?"}
        if not s.get("local_machine"):
            exact = {"chat_id": s["chat_id"]} if s["chat_id"] else {"pid": s["pid"]}
            res = await self._call(s["machine"], "jarvis.stop_session", local=True, confirme=True,
                                   **exact)
            return dict(res, target=target)
        if s["kind"] == "chat":
            if self.chats is None or s["chat_id"] not in self.chats.chats:
                raise rpc.RpcError("introuvable", "Session fermée entre-temps.")
            await self.chats.close(None, {"chat_id": s["chat_id"]})
        elif not await asyncio.to_thread(self._terminate, s["pid"], s.get("proc_start")):
            raise rpc.RpcError("introuvable", "Session déjà finie (ou processus qui n'est pas Claude Code).")
        return {"done": True, "target": target, "message": f"Session {s['name']} arrêtée."}

    async def start_session(self, conn, params):
        """Ouvre un chat (session pilotable) dans un projet, sur une machine ; `message` : premier
        message envoyé à Claude. Pas de confirmation : rien n'est détruit."""
        message = params.get("message")
        if message is not None and not isinstance(message, str):
            raise rpc.RpcError("invalide", "Message invalide.")
        if params.get("local") is True:
            return await self._start_here(conn, params.get("cwd"), message, params.get("options"))
        wanted = params.get("project")
        if not isinstance(wanted, str) or not wanted.strip():
            raise rpc.RpcError("invalide", "Projet manquant (nom approché ou chemin).")
        machines = await self._machine_list()
        machine = self._resolve_machine(machines, params.get("machine"))
        if wanted.startswith(("/", "~")):           # chemin exact : sur la machine dite, ou ici
            m = machine or machines[0]
            return await self._start_on(conn, m, wanted, message, params.get("options"))
        targets = [m for m in machines if (machine is None or m["id"] == machine["id"])
                   and m.get("online")]

        async def projects_of(m):
            if m.get("local"):
                return await asyncio.to_thread(self._local_projects)
            return (await self._call(m["id"], "jarvis.projects")).get("projects") or []

        results = await asyncio.gather(*(projects_of(m) for m in targets), return_exceptions=True)
        candidates = []
        for m, res in zip(targets, results):
            if isinstance(res, BaseException):
                continue
            for p in res:
                candidates.append(dict(p, machine=m["id"], machine_name=m.get("name") or m["id"],
                                       local_machine=bool(m.get("local"))))
        hits = best(wanted, candidates, lambda c: [c["name"], os.path.basename(c["cwd"])])
        if not hits:
            raise rpc.RpcError("introuvable", f"Aucun projet ne ressemble à « {wanted} »"
                               + (f" sur {machine['id']}." if machine else "."))
        if len(hits) > 1:
            raise rpc.RpcError("conflit", f"Plusieurs projets correspondent à « {wanted} » : "
                               + ", ".join(f"{h['name']} ({h['machine']})" for h in hits)
                               + ". Sur quelle machine ?")
        hit = hits[0]
        m = next(x for x in machines if x["id"] == hit["machine"])
        return await self._start_on(conn, m, hit["cwd"], message, params.get("options"))

    async def _start_on(self, conn, m, cwd, message, options):
        if m.get("local"):
            res = await self._start_here(conn, cwd, message, options)
        else:
            extra = {"options": options} if isinstance(options, dict) else {}
            res = await self._call(m["id"], "jarvis.start_session", local=True, cwd=cwd,
                                   message=message, **extra)
        return dict(res, machine=m["id"], machine_name=m.get("name") or m["id"])

    async def _start_here(self, conn, cwd, message, options):
        if self.chats is None:
            raise rpc.RpcError("introuvable", "Chats indisponibles sur ce pont.")
        if isinstance(cwd, str) and cwd.startswith("~"):
            cwd = os.path.expanduser(cwd)
        opened = await self.chats.open(conn, {"cwd": cwd, "options": options if isinstance(options, dict) else {}})
        chat = self.chats.chats.get(opened["chat_id"])
        if chat is not None:
            chat.conns.discard(conn)        # Jarvis ne suit pas le fil du chat
        out = {"done": True, "chat_id": opened["chat_id"], "cwd": opened["cwd"],
               "project": os.path.basename(os.path.normpath(opened["cwd"])), "sent": False}
        if message:
            res = await self.chats.send(conn, {"chat_id": opened["chat_id"], "text": message})
            out["sent"] = bool(res.get("ok"))
        return out
