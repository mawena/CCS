# CCS 0.3.0 — sessions, intégration Claude Code, notifications actives

Date : 2026-10-26 · Statut : validé (« quand c'est done … push, build et release »,
sur la recommandation proposée : indicateur, sessions, ligne d'état, boutons de
notification, bascule après blocage).

## Sessions Claude sur le PC

Source : `~/.claude/sessions/<pid>.json` (`pid`, `sessionId`, `name`, `cwd`,
`status` ∈ busy / idle / waiting…, `waitingFor`, `startedAt`, `updatedAt`,
`kind`, `entrypoint`). Lecture seule ; les fichiers `.key` ne sont jamais lus.
Une fiche n'est retenue que si le processus existe et s'appelle `claude`.

- **Voir** : onglet Sessions, sous-menu de l'indicateur, `ccs sessions` — nom,
  projet, état (travaille / attend ta réponse : motif / au repos), depuis quand,
  consommation de la conversation (tokens pondérés, modèle) lue dans
  `~/.claude/projects/<slug>/<sessionId>.jsonl`.
- **Être prévenu** : notification quand une session passe de « travaille » à
  « au repos » (« X a terminé ») ou « en attente » (« X attend ta réponse »),
  si elle travaillait depuis au moins 60 s. Réglage `alerts.sessions`.
  Surveillance immédiate (moniteur de fichiers), pas au relevé de 5 min.
- **Agir** : ouvrir le dossier, ouvrir un terminal dans le dossier, reprendre
  une conversation récente du projet (`claude --resume <id>`) ou en démarrer une
  nouvelle dans un terminal, terminer une session (SIGTERM, après confirmation,
  dans l'application seulement).

## Intégration Claude Code (`ccs integrate on|off|status`)

Modifie `~/.claude/settings.json` sur demande explicite, atomiquement, avec une
sauvegarde `settings.json.ccs-backup` ; ne remplace jamais une `statusLine`
existante ; n'ajoute/retire que ses propres entrées.

- **Ligne d'état** : `claude-accounts statusline` (lit `state.json`, < 50 ms) :
  `◑ mawena2 35 % ↻17:20 · ⏱14:50 · semaine 49 % · 2 comptes`.
- **Bascule après blocage** : hook `StopFailure` (matcher `rate_limit`) →
  `claude-accounts hook stop-failure` : relevé si l'état a plus de 10 min, choix
  du meilleur autre compte (données fraîches, sans erreur bloquante), bascule,
  événement `switch` mode `blocage`, notification « Limite atteinte dans X :
  basculé sur Y — tape « continue » ». Aucun compte → notification avec le
  prochain compte disponible.

## Notifications actives

Les alertes de seuil (80 / 95 %), de fin imminente et « tous épuisés » portent
un bouton « Basculer sur <meilleur compte> » quand il existe. Le service écoute
`ActionInvoked` (D-Bus) et exécute `ccs use` (journalisé comme bascule
manuelle).

## Indicateur

Icône jauge dynamique et menu d'informations (déjà livrés sur develop) +
sous-menu « Sessions (n) » : chaque session avec son état ; actions : ouvrir un
terminal ici, ouvrir le dossier.

## Non-objectifs

Pas de prise de contrôle d'une session (pas d'envoi de messages via le socket
de Claude Code) ; pas de focus de la fenêtre de terminal existante ; pas de
compte par projet.
