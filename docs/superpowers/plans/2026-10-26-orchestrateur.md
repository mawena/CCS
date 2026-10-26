# CCS 0.2.0 — orchestrateur : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Enchaîner et décaler les fenêtres de 5 h de tous les comptes, consommer d'abord le quota qui expire, répartir la semaine, et documenter le cas d'usage « plusieurs comptes Pro ».

**Architecture:** Logique pure dans `ccs_app/orchestrator.py` (plage horaire, créneaux, démarrages dus, bascule anticipée, planning), branchée dans `Daemon.tick` ; démarrages via `warmup.run` ; planning publié dans `state.json` et affiché par la CLI et un onglet GUI.

**Tech Stack:** identique à 0.1.0 (Python 3 stdlib, PyGObject, bash).

**Spec:** `docs/superpowers/specs/2026-10-26-orchestrateur-design.md`

## Global Constraints

- Plage par défaut `{"start": "08:00", "end": "02:00", "days": [0..6]}`, heure locale, passage de minuit géré.
- Décalage `k × 5 h / N`, k = rang alphabétique parmi les comptes participants (données fraîches, sans erreur, semaine < 95 %).
- Bascule anticipée : fin ≤ 60 min, restant ≥ 30 %, cooldown 30 min, manuelle < 5 min respectée, données ≤ 600 s.
- Réserve : marge hebdo < −10 pts. Une tentative de démarrage / compte / 15 min.
- `orchestrator.enabled` = False par défaut.
- Tests sans réseau ni vrais jetons ; git flow `feature/<nom>` ; commits FR.

## Review Focus

- Plage qui passe minuit (01:30 est actif, 03:00 ne l'est pas ; la période a commencé la veille).
- Un seul compte participant → pas de décalage (offset 0), enchaînement seul.
- Compte en erreur ou périmé → jamais démarré, jamais cible de bascule anticipée.
- Démarrage déjà tenté < 15 min (l'API ne reflète pas encore la nouvelle fenêtre) → pas de doublon.
- Bascule anticipée qui ferait du ping-pong → bloquée par cooldown et par « fin de la cible avant celle de l'actif ».

---

### Task 1: Cœur de l'orchestrateur

**Files:** Create `ccs_app/orchestrator.py`, `tests/test_orchestrator.py` ; Modify `ccs_app/settings.py` (DEFAULTS), `ccs_app/forecast.py` (`best_account(..., reserve=frozenset())`).

**Interfaces (Produces):**
- `DEFAULTS["orchestrator"] = {"enabled": False, "active_hours": {"start": "08:00", "end": "02:00", "days": [0,1,2,3,4,5,6]}, "stagger": True, "expiring_switch": True, "expiring_within_min": 60, "expiring_min_left": 30, "expiring_cooldown_min": 30, "reserve_points": 10, "max_weekly_start": 95}`
- `period_bounds(now, hours) -> tuple[datetime, datetime] | None` (période active contenant `now`, en heure locale ; None hors plage).
- `participants(accounts, now, cfg) -> list[str]` (triés).
- `first_slots(accounts, now, cfg) -> dict[str, datetime]`.
- `reserve_set(accounts, paces, cfg) -> set[str]`.
- `starts_due(accounts, now, cfg, store) -> list[str]` (au repos, participant, `now ≥ créneau`, pas de tentative orchestrateur < 15 min).
- `expiring_decision(accounts, active, now, cfg, events) -> Decision | None` (réutilise `autoswitch.Decision`).
- `@dataclass PlanWindow(name, start, end, kind)` kind ∈ "current", "planned" ; `plan(accounts, now, cfg) -> list[PlanWindow]` ; `next_wake(accounts, now, cfg) -> datetime | None`.

- [ ] Tests (RED) : plage passant minuit, hors plage, jours exclus ; participants (erreur/périmé/semaine ≥ 95 exclus) ; créneaux 2 comptes (+0 / +2 h 30) et 1 compte (+0) ; starts_due (avant créneau non, après oui, fenêtre ouverte non, tentative récente non, hors plage non) ; réserve ; expiring (déclenche, cible périmée non, fin cible après actif non, cooldown, manuelle récente) ; plan (fenêtre courante + enchaînées jusqu'à fin de plage) ; next_wake ; best_account met la réserve en dernier.
- [ ] Implémenter → GREEN → commit `feat(orchestrateur): enchaînement, décalage, quota qui expire et réserve hebdo`.

### Task 2: Branchement dans le service

**Files:** Modify `ccs_app/daemon.py`, `ccs_app/warmup.py` (`run(..., mode="creneau")`), `tests/test_daemon.py`.

**Interfaces:** `Daemon(store, notifier, starter=None)` — `starter(name, now)` lance le démarrage (défaut : thread `warmup.run(name, "auto", store, now, mode="orchestrateur")` après événement « en cours ») ; `tick` : décision seuil d'abord, sinon `expiring_decision` si activé ; démarrages `starts_due` ; délai = min(délai, `next_wake` − now, ≥ 30 s) ; `state.json["orchestrator"] = {"enabled", "active_now", "plan": [{name, start, end, kind}], "next_wake"}`.

- [ ] Tests (RED) : démarrage d'un compte au repos après son créneau ; pas de démarrage si désactivé ; bascule anticipée exécutée ; réveil précis (délai < 300 s quand une fin de fenêtre approche) ; plan dans state.json.
- [ ] Implémenter → GREEN → commit `feat(daemon): orchestrateur dans la boucle de collecte`.

### Task 3: CLI

**Files:** Modify `ccs_app/cli.py`, `bin/ccs`, `tests/test_cli.py`, `tests/ccs_e2e.sh`.

**Interfaces:** `claude-accounts plan` (planning texte depuis `state.json`), `claude-accounts orch on|off` ; `ccs plan`, `ccs orch on|off`, aide mise à jour ; `status` affiche l'état de l'orchestrateur.

- [ ] Tests (RED) : orch on/off persiste ; plan liste fenêtres et recharges ; e2e `ccs orch on` puis `ccs status` contient « Orchestrateur : activé ».
- [ ] Implémenter → GREEN → commit `feat(cli): ccs plan et ccs orch`.

### Task 4: Interface

**Files:** Create `ccs_app/gui/planning.py` ; Modify `gui/app.py`, `gui/prefs.py`, `gui/geometry.py`, `tests/test_charts.py`.

**Interfaces:** `geometry.span_to_x(t, t0, t1, width) -> float` (borné) ; onglet « Planning » (frises par compte : fenêtre en cours remplie selon l'usage, fenêtres prévues en clair, trait « maintenant », liste des recharges) ; Réglages : groupe « Orchestrateur » (activer, plage début/fin, jours, décalage, quota qui expire + seuils, réserve).

- [ ] Test (RED) `test_span_to_x_clamps` → implémenter → GREEN ; vérification visuelle en HOME isolé (souris seulement).
- [ ] Commit `feat(interface): onglet Planning et réglages de l'orchestrateur`.

### Task 5: Documentation et release 0.2.0

**Files:** `README.md` (cas d'usage paliers intermédiaires, orchestrateur, note conditions d'Anthropic, URL du dépôt), `docs/utilisation.md`, `docs/architecture.md`, `CHANGELOG.md`, `docs/man/*.1`, `debian/changelog`, `debian/copyright` (Source), `.gitignore` (`/*.deb`), `ccs_app/__init__.py`.

- [ ] Docs → commit `docs: orchestrateur et usage multi-comptes Pro`.
- [ ] Revue finale (sous-agent) → correctifs.
- [ ] `git flow release start 0.2.0` → version → `scripts/build-deb.sh` → `git flow release finish`.
