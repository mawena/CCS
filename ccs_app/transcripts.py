"""Analyse des journaux locaux de Claude Code (~/.claude/projects/**/*.jsonl)."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import core

FAMILIES = ("opus", "sonnet", "haiku", "fable")


@dataclass
class UsageRow:
    ts: float
    project: str
    model: str
    input: int
    output: int
    cache_write: int
    cache_read: int
    file: str = ""          # journal de la conversation (gros consommateurs)

    @property
    def weighted(self):
        """Poids approximatif dans les limites : la sortie coûte plus, le cache lu moins."""
        return self.input + self.cache_write + self.output * 5 + self.cache_read * 0.1


def model_family(model):
    m = (model or "").lower()
    return next((f for f in FAMILIES if f in m), m or "inconnu")


def weighted_tokens(tokens):
    """Poids d'une réponse (entrée, sortie, cache écrit 5 min, cache écrit 1 h, cache lu),
    comme `UsageRow.weighted`."""
    inp, out, w5m, w1h, read = tokens
    return inp + w5m + w1h + out * 5 + read * 0.1


def project_label(cwd, path, projects_dir):
    """Nom du projet d'une réponse : dossier de travail, sinon dossier du journal."""
    return _project(cwd, Path(path), Path(projects_dir))


def _project(cwd, file, projects_dir):
    if cwd:
        if Path(cwd) == core.paths().home:
            return "~"
        return Path(cwd).name or cwd
    try:
        return file.relative_to(projects_dir).parts[0]
    except ValueError:
        return "inconnu"


def scan(projects_dir, since):
    projects_dir = Path(projects_dir)
    if not projects_dir.is_dir():
        return []
    rows = {}
    for f in projects_dir.rglob("*.jsonl"):
        try:
            if f.stat().st_mtime < since:
                continue
        except OSError:
            continue
        _read_file(f, since, projects_dir, rows)
    return list(rows.values())


def scan_file(path, since=0):
    """Réponses d'une seule conversation (fichier .jsonl)."""
    rows = {}
    _read_file(Path(path), since, Path(path).parent, rows)
    return list(rows.values())


def _read_file(f, since, projects_dir, rows):
    try:
        fh = f.open(errors="replace")
    except OSError:
        return
    with fh:
        for raw in fh:
            if '"assistant"' not in raw:
                continue
            try:
                d = json.loads(raw)
                msg = d["message"]
                u = msg["usage"]
                ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
                row = UsageRow(
                    ts, _project(d.get("cwd"), f, projects_dir), model_family(msg.get("model")),
                    int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0),
                    int(u.get("cache_creation_input_tokens") or 0),
                    int(u.get("cache_read_input_tokens") or 0), str(f))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if d.get("type") != "assistant" or ts < since:
                continue
            if row.weighted > 0:  # messages internes (<synthetic>) sans usage réel
                rows[msg.get("id") or f"{f}:{ts}"] = row


@dataclass
class Report:
    total: float = 0.0
    by_project: dict = field(default_factory=dict)
    by_model: dict = field(default_factory=dict)
    by_hour: list = field(default_factory=lambda: [0.0] * 24)
    by_account: dict = field(default_factory=dict)
    cache_read: int = 0
    fresh_input: int = 0
    days: int = 7
    # gros consommateurs : journal → {"project", "weighted", "answers", "context", "cache_write"}
    by_conversation: dict = field(default_factory=dict)
    top: list = field(default_factory=list)       # `top_consumers`, rempli par `aggregate`


def aggregate(rows, periods, days):
    r = Report(days=days)
    for row in rows:
        w = row.weighted
        r.total += w
        r.by_project[row.project] = r.by_project.get(row.project, 0) + w
        r.by_model[row.model] = r.by_model.get(row.model, 0) + w
        r.by_hour[datetime.fromtimestamp(row.ts).hour] += w
        account = next((name for start, end, name in periods if start <= row.ts < end), "inconnu")
        r.by_account[account] = r.by_account.get(account, 0) + w
        r.cache_read += row.cache_read
        r.fresh_input += row.input + row.cache_write
        if row.file:
            c = r.by_conversation.setdefault(row.file, {"project": row.project, "weighted": 0.0, "answers": 0,
                                                         "context": 0, "cache_write": 0, "output": 0})
            c["weighted"] += w
            c["answers"] += 1
            c["context"] += row.input + row.cache_read + row.cache_write
            c["cache_write"] += row.input + row.cache_write
            c["output"] += row.output
    r.top = top_consumers(r)
    r.by_conversation = {}      # détail interne : seul le classement part vers les appareils
    return r


TOP_N = 8
BIG_CONTEXT = 100_000         # tokens relus en moyenne à chaque réponse : contexte long
REWRITE_SHARE = 0.25          # part du contexte réécrite dans le cache : cache souvent perdu
MANY_ANSWERS = 300


def top_consumers(report, n=TOP_N):
    """Les conversations qui pèsent le plus, avec la cause probable et le conseil. Liste de
    dicts : `title`, `project`, `file`, `share` (% de l'usage), `answers`, `avg_context`,
    `rewrite_share` (% du contexte réécrit dans le cache), `causes` (phrases)."""
    from . import sessions
    out = []
    ranked = sorted(report.by_conversation.items(), key=lambda kv: -kv[1]["weighted"])[:n]
    for path, c in ranked:
        if report.total <= 0 or c["answers"] <= 0:
            break
        avg = c["context"] / c["answers"]
        rewrite = c["cache_write"] / c["context"] if c["context"] else 0.0
        causes = []
        if avg >= BIG_CONTEXT:
            causes.append(f"contexte long ({fmt_tokens(avg)} tokens relus à chaque réponse) : "
                          "/compact, ou une nouvelle session par sujet")
        if rewrite >= REWRITE_SHARE:
            causes.append(f"cache souvent perdu ({100 * rewrite:.0f} % du contexte réécrit) : "
                          "pauses de plus d'une heure, ou conversation reprise le lendemain")
        if c["answers"] >= MANY_ANSWERS:
            causes.append(f"très longue conversation ({c['answers']} réponses) : la découper en sujets")
        out.append({"title": sessions.journal_title(path) or Path(path).stem[:8], "project": c["project"],
                    "file": path, "share": round(100 * c["weighted"] / report.total, 1),
                    "answers": c["answers"], "avg_context": int(avg), "rewrite_share": round(100 * rewrite, 1),
                    "causes": causes})
    return out


def advice(report):
    if report.total <= 0:
        return []
    tips = []
    project, value = max(report.by_project.items(), key=lambda kv: kv[1])
    share = 100 * value / report.total
    if share > 40 and len(report.by_project) > 1 or share > 80:
        tips.append(f"« {project} » représente {share:.0f} % de ton usage : regroupe tes demandes "
                    f"et lance /compact sur les longues sessions de ce projet.")
    opus = 100 * report.by_model.get("opus", 0) / report.total
    if opus > 70:
        tips.append(f"{opus:.0f} % de ton usage passe par Opus : pour les tâches simples "
                    f"(recherche, petites modifications), Sonnet ou Haiku consomment bien moins.")
    peak = max(range(24), key=lambda h: report.by_hour[h])
    if report.by_hour[peak] > 0:
        tips.append(f"Ton pic d'usage est vers {peak} h : programme un warm-up 2 à 3 h avant "
                    f"pour que la fenêtre de 5 h se réinitialise pendant ta période chargée.")
    reads = report.cache_read
    if reads + report.fresh_input and reads / (reads + report.fresh_input) < 0.3:
        tips.append("Peu de réutilisation du cache : garde tes sessions ouvertes plutôt que "
                    "d'en relancer souvent de nouvelles sur le même sujet.")
    accounts = {k: v for k, v in report.by_account.items() if k != "inconnu"}
    if len(accounts) > 1:
        top, v = max(accounts.items(), key=lambda kv: kv[1])
        if 100 * v / report.total > 75:
            tips.append(f"« {top} » porte l'essentiel de l'usage : `ccs meilleur` répartit mieux "
                        f"la charge entre tes comptes.")
    return tips[:5]


def fmt_tokens(value):
    for unit, size in (("M", 1e6), ("k", 1e3)):
        if value >= size:
            return f"{core.fr(value / size)} {unit}"
    return f"{value:.0f}"
