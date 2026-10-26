# CCS — assistant d'usage multi-comptes : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer `ccs` + `claude-accounts` en un outil empaqueté (.deb) qui collecte l'usage de tous les comptes Claude Code, prévoit, recommande, bascule automatiquement avant la coupure, alerte et analyse l'usage local.

**Architecture:** Un paquet Python `ccs_app` (logique pure testée + daemon systemd utilisateur + GUI GTK4 + indicateur GTK3) autour d'un historique SQLite ; `ccs` (bash) reste l'unique implémentation de la bascule, appelée aussi par le daemon et la GUI.

**Tech Stack:** Python 3.12 (stdlib : sqlite3, unittest, urllib, fcntl), PyGObject (GTK 4.14 + libadwaita 1.5 ; GTK 3 + AyatanaAppIndicator3), bash + jq, systemd utilisateur, debhelper 13.

**Spec:** `docs/superpowers/specs/2026-10-26-ccs-assistant-usage-design.md`

## Global Constraints

- Ubuntu 24.04 / Linux seulement ; Python ≥ 3.10, aucune dépendance hors apt.
- Stockage : `~/.claude-accounts/` (700), fichiers 600, écritures atomiques (tmp + rename).
- Jamais `claude auth logout` ; jamais de renouvellement du jeton du compte actif si un processus `claude` tourne ; tout renouvellement sous `store_lock()`.
- Jetons jamais écrits dans les journaux, events, state.json ou sorties.
- Collecte : 300 s normal, 60 s rapproché (compte actif ≥ 85 % ou ETA < 15 min) ; ≤ 1 requête/min/compte.
- Bascule auto : seuil 98 %, cible session < 80 % et semaine < 95 %, ≤ 1 bascule auto / 5 min, pas de retour vers un compte quitté pour épuisement avant son reset, bascule manuelle < 5 min respectée sauf ≥ 99,5 %.
- Alertes : session 80 % et 95 %, limite estimée < 20 min, semaine > rythme + 15 pts, une fois par seuil et par fenêtre.
- Tous les chemins dérivés de `HOME`, `CLAUDE_CONFIG_DIR`, `CCS_HOME` **au moment de l'appel** (tests en HOME isolé).
- Textes d'interface en français. Commits conventionnels en français. git flow : une `feature/<nom>` par tâche, `git flow feature finish`.
- Les tests ne touchent jamais aux vrais jetons ni au réseau (HTTP simulé).

## Review Focus

- Compte connecté non enregistré dans un profil → aucune bascule auto, pas de crash, bandeau GUI/statut le signale (Task 4).
- Réseau coupé ou API en 401/429/5xx → dernier usage connu affiché avec son âge ; données plus vieilles que 10 min jamais utilisées pour décider une bascule (Task 4, Task 6).
- `resets_at` déjà passé → la limite est considérée remise à 0 % jusqu'au prochain relevé (pas de faux « tous épuisés ») (Task 3).
- `limits[]` sans `session` ou avec des `kind` inconnus → pas de crash ; la décision de bascule utilise le pourcentage max de toutes les limites du compte (Task 3, Task 4).
- Fichiers JSON corrompus/vides (profil, settings, state) → valeurs par défaut, pas de crash, pas d'écrasement d'un profil valide (Task 1, Task 2).

---

### Task 1: Dépôt, cœur Python et reprise de l'existant

**Files:**
- Create: `bin/ccs` (copie de `~/.local/bin/ccs`), `bin/claude-accounts`, `ccs_app/__init__.py`, `ccs_app/core.py`, `ccs_app/cli.py`, `Makefile`, `.gitignore`, `tests/__init__.py`, `tests/helpers.py`, `tests/test_core.py`, `tests/ccs_e2e.sh`
- Source à reprendre : `~/.local/bin/claude-accounts` (fonctions non-GUI → `core.py`, GUI → Task 9, `print_usage` → `cli.py`)

**Interfaces:**
- Produces (`ccs_app/core.py`):
  - `class Paths: home, config_dir, creds, global_json, store: Path` ; `paths() -> Paths` (lit l'environnement à chaque appel)
  - `load_json(path) -> dict` (`{}` si absent/corrompu) ; `atomic_write_json(path, data) -> None`
  - `store_lock()` (context manager, fcntl sur `store/.lock`)
  - `@dataclass Profile(name, email, org, plan, active: bool)` ; `list_profiles() -> list[Profile]` (actif en premier) ; `active_profile_name() -> str | None` ; `live_account() -> dict | None` ; `live_logged_in() -> bool`
  - `claude_running() -> bool`
  - `class UsageError(Exception)` ; `http_json(method, url, body=None, headers=None) -> dict`
  - `refresh_tokens(oauth: dict) -> dict` ; `access_token(name, force_refresh=False) -> str`
  - `@dataclass Limit(kind: str, label: str, percent: float, resets_at: datetime | None)` ; `parse_limits(usage: dict | None) -> list[Limit]`
  - `@dataclass UsageResult(usage: dict | None, fetched_at: float | None, error: str | None)` ; `fetch_usage(name) -> UsageResult`
  - `fmt_reset(dt, now=None) -> str` ; `fmt_time(ts) -> str`
  - `ccs_bin() -> str` (`$CCS_BIN`, sinon `bin/ccs` voisin, sinon `which ccs`) ; `run_ccs(args: list[str]) -> subprocess.CompletedProcess`
- Produces (`tests/helpers.py`): `make_home(tmp) -> Path` (HOME isolé avec 2 profils factices `perso` actif / `pro`), `fake_http(responses: dict[str, dict | Exception])` (patch de `core.http_json`)
- `bin/claude-accounts` : ajoute au `sys.path` `../` (dépôt) ou `/usr/lib/ccs`, puis `ccs_app.cli.main(sys.argv[1:])`.

- [ ] **Step 1:** `git flow feature start socle`.
- [ ] **Step 2: Tests qui échouent** (`tests/test_core.py`)

```python
def test_paths_follow_env(self):          # HOME/CCS_HOME modifiés après import → paths() suit
def test_list_profiles_marks_active_first(self):  # [p.name for p in list_profiles()] == ["perso", "pro"]; p[0].active
def test_corrupted_profile_json_is_skipped(self):  # account.json = "{" → profil ignoré, pas d'exception
def test_parse_limits_new_and_legacy(self):  # limits[] → kinds ["session","weekly_all"]; sans limits → five_hour/seven_day
def test_parse_limits_unknown_kind(self):   # kind "foo_bar" → label "Foo bar"
def test_access_token_refreshes_inactive_expired(self):  # expiresAt=0, fake_http token → oauth.json contient le nouveau refreshToken
def test_access_token_never_refreshes_active_when_claude_running(self):  # claude_running patché True → UsageError, aucun appel HTTP
def test_fetch_usage_falls_back_to_cache(self):  # HTTP en erreur → UsageResult(usage=cache, error non vide)
```

- [ ] **Step 3:** `make test` (= `python3 -m unittest discover -s tests -v && bash tests/ccs_e2e.sh`) → FAIL (module absent).
- [ ] **Step 4:** Écrire `core.py` en reprenant le code existant, chemins via `paths()`. `cli.py` : `main(argv)` avec sous-commandes `gui` (défaut, Task 9), `print`. `tests/ccs_e2e.sh` : reprise du scénario déjà validé (save, add via faux `claude`, refresh simulé, use, next, rm, rename, garde « compte non enregistré ») en HOME temporaire, `set -e`, sortie `OK` finale.
- [ ] **Step 5:** `make test` → PASS ; `bin/claude-accounts print` en HOME isolé affiche les 2 profils.
- [ ] **Step 6:** Commit `feat(socle): reprise de ccs et du cœur Python dans le dépôt` ; `git flow feature finish socle`.

### Task 2: Historique SQLite et réglages

**Files:** Create `ccs_app/store.py`, `ccs_app/settings.py`, `tests/test_store.py`, `tests/test_settings.py`

**Interfaces:**
- Consumes: `core.paths`, `core.Limit`, `core.atomic_write_json`, `core.load_json`
- Produces:
  - `class Store(path: Path | None = None)` (défaut `paths().store / "history.db"`, crée le schéma) :
    `add_samples(ts: float, profile: str, limits: list[Limit])`,
    `samples(profile, kind, since: float) -> list[tuple[float, float, float | None]]` (ts, percent, resets_at_ts),
    `add_event(ts, type: str, profile: str | None, detail: dict)`,
    `events(since: float, type: str | None = None, profile: str | None = None) -> list[Event]`,
    `last_event(type, profile=None) -> Event | None`,
    `active_periods(since, until) -> list[tuple[float, float, str]]` (à partir des events `switch`),
    `prune(before: float)` (garde 60 jours).
  - `@dataclass Event(ts, type, profile, detail: dict)` ; types : `switch` (detail `{mode: "manual"|"auto", from}`), `alert` (`{key}`), `warmup`, `error`.
  - `DEFAULTS` = `{"auto_switch": {"enabled": True, "threshold": 98, "target_max_session": 80, "target_max_weekly": 95}, "alerts": {"enabled": True, "session_thresholds": [80, 95], "eta_minutes": 20, "weekly_ahead_points": 15, "resets": True, "auth": True}, "poll": {"normal_s": 300, "fast_s": 60}, "warmup": {}}` ; `load_settings() -> dict` (fusion profonde avec DEFAULTS, fichier corrompu → DEFAULTS) ; `save_settings(s: dict)`.

- [ ] **Step 1:** `git flow feature start historique`.
- [ ] **Step 2: Tests**

```python
def test_samples_roundtrip_and_since_filter(self)
def test_active_periods_from_switch_events(self):  # switch perso@0, pro@100, until=200 → [(0,100,"perso"),(100,200,"pro")]
def test_last_event_by_type_and_profile(self)
def test_prune_removes_old_rows(self)
def test_settings_deep_merge(self):  # fichier {"auto_switch":{"threshold":95}} → threshold 95, enabled True
def test_settings_corrupted_file_gives_defaults(self)
```

- [ ] **Step 3:** Run `python3 -m unittest tests.test_store tests.test_settings` → FAIL.
- [ ] **Step 4:** Implémenter (sqlite3, `PRAGMA journal_mode=WAL`, index `(profile, kind, ts)`).
- [ ] **Step 5:** Run → PASS. Commit `feat(historique): stockage SQLite des relevés et réglages` ; feature finish.

### Task 3: Prévisions, rythme, capacité, meilleur compte

**Files:** Create `ccs_app/forecast.py`, `tests/test_forecast.py`

**Interfaces:**
- Consumes: `core.Limit`
- Produces:
  - `@dataclass AccountState(name, active: bool, limits: list[Limit], fetched_at: float | None, error: str | None)` avec propriétés `session -> Limit | None` (kind `session`, sinon label legacy « Session »), `weekly -> Limit | None` (kind `weekly_all`), `max_percent -> float`.
  - `effective_percent(limit, now) -> float` : 0 si `resets_at` ≤ now.
  - `@dataclass SessionForecast(rate_per_min: float | None, eta: datetime | None, verdict: str, minutes_before_reset: float | None)` ; verdict ∈ `"limit"`, `"ok"`, `"stable"`, `"unknown"`.
  - `session_forecast(samples: list[tuple[float, float]], limit: Limit | None, now: datetime) -> SessionForecast` — régression linéaire sur les points des 45 dernières min de la fenêtre courante (ts ≥ resets_at − 5 h) ; ≥ 2 points et ≥ 10 min d'écart sinon `"unknown"` ; vitesse ≤ 0,01 %/min → `"stable"` ; ETA < reset → `"limit"` sinon `"ok"`.
  - `@dataclass WeeklyPace(elapsed_frac, ideal, margin, per_day_budget, days_left)` ; `weekly_pace(limit: Limit, now) -> WeeklyPace | None`.
  - `capacity(accounts: list[AccountState], now) -> float` = Σ min(100 − session, 100 − semaine)/100 (effective_percent).
  - `@dataclass Recommendation(name, reason: str)` ; `best_account(accounts, now, exclude: set[str] = frozenset(), max_session=90, max_weekly=95) -> Recommendation | None`. Ordre : fenêtre ouverte (session.resets_at futur et percent > 0) avec marge, reset le plus proche d'abord ; puis au repos, plus grande marge hebdo. Comptes en erreur sans données exclus.

- [ ] **Step 1:** `git flow feature start previsions`.
- [ ] **Step 2: Tests**

```python
def test_forecast_limit_before_reset(self):  # 30%→50% en 40 min, reset dans 3 h → verdict "limit", eta ≈ +80 min
def test_forecast_ok_when_reset_first(self):
def test_forecast_unknown_with_one_point(self)
def test_forecast_ignores_previous_window_points(self)
def test_weekly_pace_margin_and_budget(self):  # 35 % à 4 j du reset → ideal ≈ 42.9, margin ≈ 7.9, per_day ≈ 16.25
def test_effective_percent_after_reset_is_zero(self)
def test_capacity_sums_accounts(self):  # (31,35) & (0,10) → 0.69 + 0.90 = 1.59
def test_best_prefers_open_window_soonest_reset(self)
def test_best_skips_exhausted_and_errors(self)
def test_best_returns_none_when_all_exhausted(self)
def test_account_state_without_session_limit(self):  # limits seulement weekly → session None, max_percent = weekly
```

- [ ] **Step 3:** Run `python3 -m unittest tests.test_forecast` → FAIL.
- [ ] **Step 4:** Implémenter (fonctions pures, `now` toujours passé).
- [ ] **Step 5:** Run → PASS. Commit `feat(previsions): fin de session, rythme hebdo, capacité et meilleur compte` ; feature finish.

### Task 4: Décision de bascule automatique

**Files:** Create `ccs_app/autoswitch.py`, `tests/test_autoswitch.py`

**Interfaces:**
- Consumes: `forecast.AccountState`, `forecast.best_account`, `forecast.SessionForecast`, `store.Event`, `core.run_ccs`
- Produces:
  - `@dataclass Decision(action: str, target: str | None, reason: str)` ; action ∈ `"none"`, `"switch"`, `"exhausted"`.
  - `decide(accounts, active: str | None, fc: SessionForecast | None, settings: dict, now: datetime, events: list[Event], poll_s: float) -> Decision`.
    Règles dans l'ordre : désactivé / actif `None` / données de l'actif > 600 s → none ; déclenche si `max_percent ≥ threshold` ou `percent + rate·poll_s/60 ≥ 100` ; bascule auto < 300 s → none ; bascule manuelle < 300 s et max < 99,5 → none ; exclure les comptes quittés par bascule auto (`detail.from`) dont le reset de session de l'époque n'est pas passé ; cible = `best_account(max_session=target_max_session, max_weekly=target_max_weekly)` ; aucune → `"exhausted"` (raison avec prochain reset le plus proche).
  - `execute(decision, store, now) -> bool` : `run_ccs(["use", target])`, puis event `switch` `{mode: "auto", from, reason}`.

- [ ] **Step 1:** `git flow feature start bascule-auto`.
- [ ] **Step 2: Tests**

```python
def test_no_switch_below_threshold(self)
def test_switch_at_threshold_to_best(self)
def test_switch_on_projection(self):  # 96 %, 2 %/min, poll 60 s → switch
def test_respects_cooldown_after_auto_switch(self)
def test_respects_recent_manual_switch_unless_995(self)
def test_no_return_to_exhausted_account_before_reset(self)
def test_exhausted_when_no_target(self):  # reason contient "prochain disponible"
def test_stale_data_never_switches(self)
def test_unsaved_active_account_never_switches(self):  # active=None
def test_uses_max_of_all_limits(self):  # session 50, weekly 99 → switch
```

- [ ] **Step 3:** Run → FAIL. **Step 4:** Implémenter. **Step 5:** Run → PASS.
- [ ] **Step 6:** Commit `feat(bascule): décision de bascule automatique avec garde-fous` ; feature finish.

### Task 5: Alertes et notifications

**Files:** Create `ccs_app/alerts.py`, `ccs_app/notify.py`, `tests/test_alerts.py`

**Interfaces:**
- Consumes: `forecast.*`, `store.Store`, `autoswitch.Decision`
- Produces:
  - `@dataclass Alert(key: str, title: str, body: str, urgency: int)` (0 bas, 1 normal, 2 critique).
  - `pending_alerts(accounts, active, fc, paces: dict[str, WeeklyPace], best: Recommendation | None, settings, now, sent_keys: set[str]) -> list[Alert]` — clés : `session{T}:{profil}:{reset_iso}`, `eta:{profil}:{reset_iso}`, `reset:{profil}:{reset_iso_précédent}`, `weekly_ahead:{profil}:{reset_iso_semaine}`, `auth:{profil}:{jour}`. Le reset est détecté quand la session passe de > 0 à 0 ou que `resets_at` change.
  - `decision_alert(decision) -> Alert | None` (switch → normal ; exhausted → critique, clé par fenêtre).
  - `notify.send(alert) -> None` : `Gio.DBusProxy` sur `org.freedesktop.Notifications.Notify`, app_name « Comptes Claude », icône `io.ccs.ClaudeAccounts` ; échec silencieux journalisé.

- [ ] **Step 1:** `git flow feature start alertes`.
- [ ] **Step 2: Tests**

```python
def test_session_80_then_95_once_each(self)
def test_no_duplicate_when_key_already_sent(self)
def test_eta_alert_under_20_min(self)
def test_reset_alert_when_session_back_to_zero(self)
def test_weekly_ahead_15_points(self)
def test_disabled_types_are_skipped(self)
def test_80_alert_body_suggests_best_account(self)
```

- [ ] **Step 3:** Run → FAIL. **Step 4:** Implémenter. **Step 5:** Run → PASS.
- [ ] **Step 6:** Commit `feat(alertes): notifications de seuils, prévisions et réinitialisations` ; feature finish.

### Task 6: Daemon de collecte

**Files:** Create `ccs_app/daemon.py`, `data/ccs-daemon.service`, `tests/test_daemon.py` ; Modify `ccs_app/cli.py` (sous-commandes `daemon`, `collect`)

**Interfaces:**
- Consumes: tout ce qui précède, `warmup` (Task 7, appel optionnel `warmup.tick` si présent)
- Produces:
  - `collect(store, now: datetime, only: list[str] | None = None) -> list[AccountState]` (fetch en threads, écrit samples / events `error`).
  - `detect_manual_switch(store, now) -> None` (actif ≠ profil du dernier event `switch` → event manuel).
  - `tick(store, settings, now) -> float` (collecte, décision, exécution, alertes, warm-up, `write_state`, renvoie le délai avant le prochain tick : `fast_s` si actif ≥ 85 % ou ETA < 15 min, sinon `normal_s`).
  - `write_state(accounts, forecasts, paces, best, capacity, decision, now) -> None` → `paths().store / "state.json"` : `{"updated_at", "active", "capacity", "best": {name, reason}|null, "auto_switch": {enabled, last}, "accounts": [{name, email, plan, active, error, fetched_at, limits: [{kind,label,percent,resets_at}], forecast: {verdict, eta, rate_per_min, minutes_before_reset}, pace: {ideal, margin, per_day_budget, days_left}}]}`.
  - `run() -> int` : boucle, `SIGUSR1` = tick immédiat, `SIGTERM` propre ; fichier `daemon.pid` ; ne collecte rien sans profil.
  - `request_refresh() -> bool` (SIGUSR1 au pid, False si daemon absent).
  - `data/ccs-daemon.service` : `ExecStart=/usr/bin/claude-accounts daemon`, `Restart=on-failure`, `WantedBy=default.target`.

- [ ] **Step 1:** `git flow feature start daemon`.
- [ ] **Step 2: Tests** (HOME isolé + `fake_http`, `run_ccs` patché)

```python
def test_tick_writes_state_and_samples(self)
def test_tick_fast_cadence_when_active_above_85(self)
def test_tick_executes_auto_switch_and_logs_event(self)
def test_tick_with_network_error_keeps_last_state(self)
def test_manual_switch_detected(self)
def test_no_profiles_is_idle(self)
```

- [ ] **Step 3:** Run → FAIL. **Step 4:** Implémenter. **Step 5:** Run → PASS.
- [ ] **Step 6:** Vérification manuelle : `bin/claude-accounts collect` en HOME isolé contenant une copie du profil réel (jeton frais, pas de renouvellement) → `state.json` cohérent ; supprimer la copie ensuite.
- [ ] **Step 7:** Commit `feat(daemon): collecte périodique, état partagé et bascule automatique` ; feature finish.

### Task 7: Warm-up planifié

**Files:** Create `ccs_app/warmup.py`, `tests/test_warmup.py` ; Modify `ccs_app/daemon.py` (appel dans `tick`)

**Interfaces:**
- Consumes: `core.access_token`, `forecast.AccountState`, `store.Store`
- Produces:
  - Réglage `settings["warmup"][profil] = [{"days": [0..6], "time": "HH:MM"}]`.
  - `due(settings, accounts, now, store) -> list[str]` : créneau atteint dans les 10 dernières min, fenêtre de session au repos, pas d'event `warmup` pour ce profil et ce créneau aujourd'hui.
  - `run(name, store, now) -> bool` : lance `claude -p "ok" --model haiku` avec un `CLAUDE_CONFIG_DIR` temporaire (700) contenant `.credentials.json` = `{"claudeAiOauth": <oauth du profil après access_token()>}` et `.claude.json` = `{"oauthAccount": …, "hasCompletedOnboarding": true}` ; timeout 120 s ; recopie dans le profil un `claudeAiOauth` renouvelé par claude ; supprime le dossier ; event `warmup`.

- [ ] **Step 1:** `git flow feature start warmup`.
- [ ] **Step 2: Tests**

```python
def test_due_at_slot_when_window_idle(self)
def test_not_due_when_window_open(self)
def test_not_due_twice_same_day(self)
def test_not_due_on_other_days(self)
def test_run_uses_isolated_config_dir(self):  # subprocess patché : env CLAUDE_CONFIG_DIR ≠ ~/.claude, ~/.claude/.credentials.json inchangé
```

- [ ] **Step 3:** Run → FAIL. **Step 4:** Implémenter. **Step 5:** Run → PASS.
- [ ] **Step 6:** Commit `feat(warmup): démarrage anticipé de la fenêtre de session` ; feature finish.

### Task 8: Analyse des journaux locaux

**Files:** Create `ccs_app/transcripts.py`, `tests/test_transcripts.py`, `tests/fixtures/projects/…/*.jsonl` ; Modify `ccs_app/cli.py` (`analyze`)

**Interfaces:**
- Consumes: `store.Store.active_periods`, `core.paths`
- Produces:
  - `@dataclass UsageRow(ts: float, project: str, model: str, input: int, output: int, cache_write: int, cache_read: int)` ; propriété `weighted` = input + cache_write + output×5 + cache_read×0,1.
  - `scan(projects_dir: Path, since: float) -> list[UsageRow]` : fichiers modifiés depuis `since`, lignes `type == "assistant"` avec `message.usage`, dédoublonnage par `message.id`, projet = nom de `cwd` (sinon nom du dossier), lignes invalides ignorées.
  - `@dataclass Report(total, by_project: dict, by_model: dict, by_hour: list[float] (24), by_account: dict, days: int)` ; `aggregate(rows, periods) -> Report` (compte « inconnu » hors périodes).
  - `advice(report) -> list[str]` (≤ 5) : projet > 40 % ; Opus > 70 % ; heure de pointe ; part du cache faible (< 30 % de lecture) → conseil de garder les sessions ouvertes plutôt que relancer.

- [ ] **Step 1:** `git flow feature start analyse`.
- [ ] **Step 2: Tests**

```python
def test_scan_reads_usage_and_dedups_message_ids(self)
def test_scan_skips_malformed_lines(self)
def test_aggregate_by_project_model_hour(self)
def test_aggregate_attributes_accounts_from_periods(self)
def test_advice_project_share_and_opus(self)
```

- [ ] **Step 3:** Run → FAIL. **Step 4:** Implémenter. **Step 5:** Run → PASS ; `bin/claude-accounts analyze --days 7` sur les vrais journaux (lecture seule) produit un rapport texte.
- [ ] **Step 6:** Commit `feat(analyse): consommation par projet, modèle, heure et conseils` ; feature finish.

### Task 9: Interface graphique à onglets

**Files:** Create `ccs_app/gui/__init__.py`, `gui/app.py`, `gui/accounts.py`, `gui/history.py`, `gui/analysis.py`, `gui/settings.py`, `gui/charts.py`, `tests/test_charts.py` ; Modify `ccs_app/cli.py`

**Interfaces:**
- Consumes: `state.json` (Task 6), `Store`, `settings`, `transcripts`, `core.run_ccs`, `daemon.request_refresh`, `daemon.collect` (repli si daemon absent)
- Produces:
  - `gui.app.run() -> int` (Adw.Application `io.ccs.ClaudeAccounts`, `Adw.ViewStack` + `Adw.ViewSwitcher` : Comptes, Historique, Analyse, Réglages).
  - `charts.series_to_points(series: list[tuple[float, float]], t0, t1, width, height) -> list[tuple[float, float]]` (pur, testé) ; `charts.LineChart(Gtk.DrawingArea)` : séries colorées, ligne de rythme idéal en pointillés, marqueurs verticaux de bascule.
  - Comptes : bandeau « Meilleur compte maintenant » + bouton Utiliser, capacité totale, cartes existantes + prévision (verdict en clair), rythme hebdo (marge ±, budget/jour), sparkline 24 h, interrupteur « Bascule automatique » en en-tête.
  - Historique : sélecteur 24 h / 7 j, un graphe par compte.
  - Analyse : 7 / 30 jours, barres par projet et par modèle, histogramme horaire, liste de conseils (calcul en thread).
  - Réglages : `Adw.PreferencesPage` (bascule auto + seuils, alertes par type, warm-up par profil : jours + heure, état du service `systemctl --user is-active ccs-daemon` avec bouton Démarrer).
  - Rechargement : `Gio.FileMonitor` sur `state.json` + minuterie 60 s.

- [ ] **Step 1:** `git flow feature start interface`.
- [ ] **Step 2: Test** `test_series_to_points_scales_and_clamps` (0–100 % → hauteur inversée, valeurs hors plage bornées).
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implémenter. **Step 5:** Run → PASS.
- [ ] **Step 6:** Vérification visuelle en HOME isolé (state.json + history.db factices) : captures `import -window` de chaque onglet, contrôle lisible clair/sombre ; clics souris seulement (pas de saisie clavier simulée).
- [ ] **Step 7:** Commit `feat(interface): onglets comptes, historique, analyse et réglages` ; feature finish.

### Task 10: Indicateur barre du haut

**Files:** Create `ccs_app/tray.py`, `data/io.ccs.ClaudeAccounts.Tray.desktop` (autostart) ; Modify `ccs_app/cli.py` (`tray`)

**Interfaces:**
- Consumes: `state.json`, `core.run_ccs`
- Produces: `tray.label_for(state: dict) -> str` (pur, testé : `"◔ 32 %"`, `"⚠ 98 %"` ≥ 95, `"—"` sans données) ; `tray.run() -> int` (GTK 3 + AyatanaAppIndicator3, menu : comptes avec % et bascule, meilleur compte, prévision, Ouvrir Comptes Claude, Bascule automatique on/off) ; relit `state.json` toutes les 30 s.

- [ ] **Step 1:** `git flow feature start indicateur`.
- [ ] **Step 2:** Test `test_label_for` (3 cas ci-dessus) dans `tests/test_tray.py` → FAIL → implémenter → PASS.
- [ ] **Step 3:** Vérification : lancement en HOME isolé, l'icône apparaît (capture de la zone supérieure de l'écran).
- [ ] **Step 4:** Commit `feat(indicateur): usage du compte actif dans la barre du haut` ; feature finish.

### Task 11: Commandes CLI

**Files:** Modify `bin/ccs`, `ccs_app/cli.py`, `tests/ccs_e2e.sh`, `tests/test_cli.py`

**Interfaces:**
- Produces (`claude-accounts`) : `print` (usage + prévision + rythme), `status` (actif, meilleur compte, capacité, bascule auto, état du daemon), `best [--switch]`, `auto on|off`, `collect`, `daemon`, `tray`, `analyze [--days N]`, `gui`.
- Produces (`ccs`) : `best` → `claude-accounts best --switch` ; `auto on|off` ; `status` ; `usage` inchangé ; aide mise à jour. `ccs use` et `ccs` en fin de bascule : message « les sessions ouvertes suivront à leur prochaine requête » au lieu de « relance-les ».

- [ ] **Step 1:** `git flow feature start cli`.
- [ ] **Step 2: Tests** `test_auto_on_off_persists`, `test_best_without_profiles_exit_1`, `test_status_text_contains_best` ; e2e : `ccs auto off` puis `ccs status` contient « désactivée ».
- [ ] **Step 3:** Run → FAIL. **Step 4:** Implémenter. **Step 5:** `make test` → PASS.
- [ ] **Step 6:** Commit `feat(cli): best, status, auto et analyse en ligne de commande` ; feature finish.

### Task 12: Empaquetage, documentation, release

**Files:** Create `debian/{control,changelog,rules,install,links,copyright,source/format,ccs.lintian-overrides}`, `data/io.ccs.ClaudeAccounts.desktop`, `data/io.ccs.ClaudeAccounts.svg`, `README.md`, `CHANGELOG.md`, `docs/utilisation.md`, `docs/architecture.md`, `scripts/build-deb.sh`, `LICENSE` (MIT)

**Interfaces:**
- `debian/control` : `Source/Package: ccs`, `Architecture: all`, `Build-Depends: debhelper-compat (= 13)` (fichiers posés par `debian/install`, sans dh-python), `Depends: bash, jq, procps, python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.4), gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1, ${misc:Depends}`, `Recommends: gnome-shell-extension-appindicator`.
- Arborescence installée : `/usr/bin/ccs`, `/usr/bin/claude-accounts`, `/usr/lib/ccs/ccs_app/`, `/usr/share/applications/io.ccs.ClaudeAccounts.desktop`, `/usr/share/icons/hicolor/scalable/apps/io.ccs.ClaudeAccounts.svg`, `/usr/lib/systemd/user/ccs-daemon.service` (activé via `dh_installsystemduser`), `/etc/xdg/autostart/io.ccs.ClaudeAccounts.Tray.desktop`.
- `scripts/build-deb.sh` : `make test`, `dpkg-buildpackage -us -uc -b`, déplace le `.deb` dans `dist/`, écrit `dist/SHA256SUMS`, lance `lintian` (0 erreur).

- [ ] **Step 1:** `git flow feature start paquet`.
- [ ] **Step 2:** Écrire `debian/`, données, docs, CHANGELOG `[0.1.0] — 2026-10-26`.
- [ ] **Step 3:** `scripts/build-deb.sh` → `dist/ccs_0.1.0_all.deb` ; `dpkg-deb -c` liste les chemins ci-dessus ; `lintian` sans erreur.
- [ ] **Step 4:** Vérification d'installation sans root : `dpkg-deb -x` dans un dossier temporaire, lancer `usr/bin/claude-accounts print` avec `PYTHONPATH` → fonctionne depuis `/usr/lib/ccs` équivalent.
- [ ] **Step 5:** Commit `build(paquet): empaquetage Debian, icône, documentation` ; feature finish.
- [ ] **Step 6:** `git flow release start 0.1.0` → version dans `ccs_app/__init__.py` et `debian/changelog` → rebuild → `git flow release finish -m "v0.1.0" 0.1.0`.
- [ ] **Step 7:** Remise à Charles : commande `sudo apt install ./dist/ccs_0.1.0_all.deb`, puis (avec son accord) suppression de `~/.local/bin/ccs`, `~/.local/bin/claude-accounts`, `~/.local/share/applications/io.ccs.ClaudeAccounts.desktop` qui masquent la version installée ; `systemctl --user daemon-reload && systemctl --user enable --now ccs-daemon` ; lancement de l'indicateur.
