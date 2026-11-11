# Phase 11 (0.8.0) — conception

Validée par Charles le 11/11/2026 (« je prends tout », puis « vas y »). Ce document
sert de contrat commun aux sous-agents : comportement attendu, choix faits, fichiers
de chacun, interfaces que le raccordement (vague 2) appellera.

## Intention

Huit fonctions autour de trois idées : faire travailler les comptes quand Charles
n'est pas là (file de tâches, notifications sur le téléphone), ne rien perdre
(archive des conversations, fiche « où j'en étais », sauvegarde chiffrée), économiser
la machine et le quota (mémoire des sessions, alerte de contexte lourd, budget par
projet).

## Règles communes (non négociables)

- Tout en français : textes, messages, commits (conventionnels), docstrings.
- Aucun calcul lourd hors de la file Gagarine : toute suite de tests, même partielle,
  passe par `gagarine file "<nom>" <Go> <cœurs> -- <commande>` (un fichier de tests :
  `1 1` ; la suite complète : `2 2`). Le hook refuse le reste : relancer telle quelle la
  commande qu'il propose, ne jamais contourner.
- Ne jamais lire, afficher ni copier les jetons de `~/.claude-accounts` ; les tests
  travaillent dans des dossiers temporaires (`CCS_HOME`, `HOME`, `CLAUDE_CONFIG_DIR`,
  `XDG_DATA_HOME`, `GNUPGHOME`…), jamais sur les vraies données.
- Aucune vraie notification (bureau ou téléphone), aucun vrai appel réseau, aucune
  vraie installation dans les tests ; ne pas toucher à l'application ouverte, à
  l'icône, au service `ccs-daemon` ni aux réglages GNOME de Charles.
- Ne jamais interroger l'API d'usage (429). Ne jamais lancer un vrai `claude` dans les
  tests (faux binaire).
- Jamais de `pkill`/`pgrep -f` génériques : ne tuer que des pid lancés soi-même.
- Commits au nom de l'identité git configurée, sans `Co-Authored-By` ni attribution.
- Le contenu des conversations de Charles (`~/.claude/projects`) n'est jamais recopié
  dans le code, les tests, les commits ni les rapports.
- Une permission refusée n'est jamais contournée.

## Les huit fonctions

### 1. File de tâches (`ccs tache`, onglet Planning)

- Une tâche : message, dossier, modèle (optionnel), droits, moment. Moments :
  `quota` (dès qu'un compte a du quota), `HH:MM` (à partir de cette heure, aujourd'hui
  ou demain), `nuit` (meilleur créneau de `best_time` dans la plage de nuit, réglable,
  23:00–07:00 par défaut).
- Exécution sans fenêtre, par le service : `claude -p --output-format stream-json
  --verbose` dans le dossier, sortie écrite dans un journal. Si la commande `gagarine`
  existe, la tâche passe par la file : `gagarine file --priorite fond "ccs tâche <id>"
  1 1 -- …`. Une seule tâche à la fois.
- Droits (via `launch_options`) : `lecture` (mode par défaut : en `-p`, ce qui demande
  une permission est refusé), `modifications` (`acceptEdits`, par défaut), `tout`
  (`bypassPermissions`, même avertissement que la nouvelle session avancée).
- Le compte actif est global : la tâche utilise le compte actif. Avant de la lancer, si
  le compte actif est au-dessus du seuil de bascule, on applique la bascule existante
  (jamais pendant une pause de CCS : la tâche attend).
- Limite atteinte pendant la tâche : bascule (hors pause), puis relance par
  `--resume <session_id>` avec « continue », 3 tentatives au plus.
- À la fin : notification « tâche finie / échouée » (clic → application sur la tâche),
  durée, coût équivalent. La conversation est ensuite une conversation normale
  (reprise dans un onglet).
- Stockage : `~/.claude-accounts/tasks.json` (600, écriture atomique sous verrou),
  journaux `~/.claude-accounts/tasks/<id>.jsonl`.
- Commandes : `ccs tache ajouter "<message>" [-C dossier] [--modele m]
  [--droits lecture|modifications|tout] [--quand quota|nuit|HH:MM]`, `ccs tache`
  (liste), `ccs tache voir <id>` (suit le journal), `ccs tache annuler <id>`,
  `ccs tache supprimer <id>`.

### 2. Notifications sur le téléphone (ntfy, optionnel)

- Désactivé par défaut. Serveur `https://ntfy.sh` par défaut (ou celui de Charles),
  canal secret tiré au hasard (`ccs-` + `secrets.token_urlsafe(18)`).
- Événements (chacun réglable) : session qui attend la réponse, tâche finie ou
  échouée, bascule de compte, tous les comptes épuisés.
- Contenu : nom du projet et état, rien d'autre (jamais un titre de conversation, un
  message, un chemin complet ni un nom de compte).
- « Ne pas déranger » appliqué aussi au téléphone (même exception « attend ta
  réponse »).
- Envoi en arrière-plan, délai court, échec silencieux (journalisé), jamais d'exception.
- Réglages : lien d'abonnement et QR code (si `python3-qrcode` est présent, sinon le
  lien seul), bouton « Essayer ».

### 3. Archive des conversations

- Claude Code efface par défaut les conversations de plus de 30 jours
  (`cleanupPeriodDays`). Le service copie, compressées en gzip, dans
  `${XDG_DATA_HOME:-~/.local/share}/ccs/archive` (700) les conversations inchangées
  depuis 1 jour (fichier `.jsonl` et son dossier frère éventuel), et remet à jour une
  copie si l'original a bougé. Index `index.json` (identifiant, dossier, titre, date,
  taille) pour lister sans décompresser.
- Charge limitée : au plus 20 fichiers ou 100 Mo par passage, un passage toutes les
  30 min ; le premier archivage s'étale sur plusieurs passages.
- Une conversation dont l'original a disparu reste dans l'onglet Sessions (« archivée »)
  avec recherche, aperçu, export et reprise. Reprise : décompression à sa place, date
  de modification remise à maintenant (sinon Claude Code la réeffacerait).
- Gardée sans limite par défaut ; réglage d'âge maximal (jours, 0 = sans limite).
  Taille affichée dans les Réglages et `ccs doctor`.

### 4. Fiche « où j'en étais » (`ccs fiche <id>`, encart de l'aperçu)

- Lue dans le journal, sans appel à Claude : dernière demande de Charles (texte, pas
  les résultats d'outils), début de la dernière réponse, fichiers modifiés (outils
  d'écriture), dernière liste de tâches, dossier, branche git, compte actif à ce
  moment (journal des bascules) s'il est connu, date.
- Marche aussi sur une conversation archivée.

### 5. Sauvegarde chiffrée (`ccs sauvegarde`, `ccs restaurer`, Réglages)

- Archive tar des profils (jetons compris), des réglages, des comptes par projet, des
  budgets et de la configuration des raccourcis ; pas les conversations, ni les états
  passagers, caches et journaux.
- Chiffrement `gpg --symmetric --cipher-algo AES256` ; phrase de passe saisie dans la
  fenêtre de gpg (pinentry), jamais en argument ni en variable d'environnement dans le
  code de production. Fichier créé en 600.
- Restauration : liste du contenu, confirmation avant d'écraser un profil existant
  (`--oui` pour la ligne de commande), écriture atomique en 600. Le compte actif
  n'est pas changé.

### 6. Mémoire des sessions

- Pour chaque session ouverte : RAM (PSS du processus et de ses descendants, à défaut
  RSS), inactivité (depuis la dernière écriture du journal ou l'état de la session).
- Onglet Sessions et `ccs sessions` : RAM par session et totale, durée d'inactivité.
  Bouton « Fermer » (confirmation) sur les sessions inactives depuis plus de 2 h
  (réglable), via `sessions.terminate` ; bandeau « N sessions inactives occupent X Go ».
  Jamais de fermeture automatique.

### 7. Alerte de contexte lourd

- Taille du contexte = dernier usage de réponse du journal (`input_tokens` +
  `cache_read_input_tokens` + `cache_creation_input_tokens`).
- Au-delà de 150 000 tokens (réglable) : une seule notification par session, avec le
  coût d'un message en équivalent dollars (`costs`) et le conseil `/compact` ou nouvelle
  session. Badge dans l'onglet Sessions et dans la ligne d'état de Claude Code.

### 8. Budget par projet (`ccs budget`, onglet Analyse)

- Budget hebdomadaire en équivalent dollars par dossier de projet (un sous-dossier
  compte pour le projet le plus proche), semaine calendaire comme `ccs semaine`.
- Affiche dépensé, budget, pourcentage et part de la consommation totale de la semaine.
- Alertes à 80 % et 100 %, une fois par seuil, par projet et par semaine. Ne bloque
  jamais rien.
- Stockage `~/.claude-accounts/budgets.json` (comme `projects.json`). Calculs mis en
  cache par (chemin, date, taille) du journal.
- Commandes : `ccs budget` (état), `ccs budget <dossier> <montant>`,
  `ccs budget <dossier> aucun`.

## Réglages (clés de `settings.json`)

Chaque module garde ses valeurs par défaut (`DEFAULTS`) et lit sa section avec repli ;
la vague 2 les ajoute à `settings.py` (valeurs par défaut et validation).

```
"tasks":    {"enabled": true, "night": {"start": "23:00", "end": "07:00"}, "max_attempts": 3}
"phone":    {"enabled": false, "server": "https://ntfy.sh", "topic": "",
             "events": {"waiting": true, "task": true, "switch": true, "exhausted": true}}
"archive":  {"enabled": true, "idle_days": 1, "max_age_days": 0}
"sessions": {"idle_hours": 2}
"context_alert": {"enabled": true, "threshold_tokens": 150000}
"budget":   {"enabled": true, "alert_pcts": [80, 100]}
```

## Découpage et propriété des fichiers

Vague 1 (en parallèle, chacun ses fichiers et leurs tests) :

| Agent | Fonctions | Fichiers |
|---|---|---|
| A | 1 | `ccs_app/tasks.py`, `ccs_app/task_runner.py`, `ccs_app/gui/tasks_view.py`, tests associés |
| B | 2, 8 | `ccs_app/phone.py`, `ccs_app/budget.py`, `ccs_app/gui/phone_group.py`, `ccs_app/gui/budget_view.py`, tests associés |
| C | 3, 4 | `ccs_app/archive.py`, `ccs_app/fiche.py`, `ccs_app/gui/fiche_view.py`, `ccs_app/conversations.py`, `ccs_app/gui/preview_dialog.py`, `ccs_app/gui/conversation_list.py`, tests associés |
| D | 5 | `ccs_app/backup.py`, `ccs_app/gui/backup_group.py`, tests associés |
| E | 6, 7 | `ccs_app/session_memory.py`, `ccs_app/context_alert.py`, `ccs_app/sessions.py`, `ccs_app/gui/session_cards.py`, `ccs_app/integration.py`, tests associés |

Vague 2 (raccordement, après fusion de la vague 1) :

- Service et commandes : `daemon.py`, `settings.py`, `cli.py`, `bin/ccs`, `doctor.py`,
  `debian/control`, `tests/ccs_e2e.sh` et leurs tests.
- Application : `gui/prefs.py`, `gui/planning.py`, `gui/analysis.py`,
  `gui/sessions_page.py`, `gui/app.py`, `tray.py` et leurs tests.

Vague 3 : documentation (README, `docs/utilisation.md`, `docs/architecture.md`, pages
man, CHANGELOG). Puis release mineure 0.8.0, `.deb`, release GitHub, dépôt APT.

Chaque module de la vague 1 expose une fonction `command(args)` pour sa commande `ccs`
(analyse des arguments comprise, renvoie le code de sortie) et, s'il a une part
périodique, une fonction `tick(now, settings, …)` ou équivalente sans effet de bord
caché, que le service appellera ; les notifications sont des dictionnaires d'alerte
comme ceux de `alerts.py`, envoyés par l'appelant.
