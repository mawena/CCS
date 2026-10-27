# Feuille de route — CCS

Plusieurs comptes Claude Code sur un PC Linux, comme un seul. Détails de chaque
version : `CHANGELOG.md` ; conceptions et plans : `docs/superpowers/`.

## Phase 1 — Multi-comptes et usage (0.1.0) ✅

- [x] `ccs` : profils, bascule atomique, sauvegarde du jeton renouvelé
- [x] Usage de tous les comptes sans reconnexion
- [x] Prévisions, rythme hebdomadaire, capacité, meilleur compte
- [x] Bascule automatique à 98 % avec garde-fous
- [x] Alertes bureau, warm-up planifié, analyse des journaux
- [x] Application « Comptes Claude », indicateur, service `ccs-daemon`
- [x] Paquet Debian, README, licence MIT

## Phase 2 — Orchestrateur (0.2.0 → 0.2.1) ✅

- [x] Enchaînement et décalage des fenêtres de 5 h pendant une plage horaire
- [x] Quota qui expire d'abord, réserve hebdomadaire
- [x] `ccs plan`, `ccs orch`, onglet Planning
- [x] Fenêtres à 0 % reconnues, décalage sur les démarrages réels
- [x] Erreurs 429 tolérées, relance du service après mise à jour

## Phase 3 — Sessions et intégration Claude Code (0.3.0) ✅

- [x] Sessions ouvertes : état, consommation, reprise, terminal, terminer
- [x] Notifications « a terminé » / « attend ta réponse »
- [x] `ccs integrate` : ligne d'état et bascule après blocage (hook `StopFailure`)
- [x] Boutons « Basculer sur … » dans les notifications
- [x] Icône jauge et menu d'informations

## Phase 4 — Propositions pour 0.4.0 (à choisir)

Recommandées :
- [ ] `ccs doctor` : bilan de santé (service, version, extension, intégration, connexions) avec la commande qui corrige
- [ ] Prévision de fin de semaine par compte, alerte 2 jours avant
- [ ] Mode pause (bascule auto et orchestrateur suspendus 1 h / 4 h / jusqu'à demain)
- [ ] Avertissement de nouvelle version et relance automatique de l'icône
- [ ] Conseiller de formule (2–3 Pro ou Max) avec équivalent en dollars

Autres :
- [ ] Conseil de modèle près des limites (Opus → Sonnet)
- [ ] Bilan de la semaine
- [ ] Raccourci clavier global
- [ ] Rappel quand une session attend depuis plus de 10 min
- [ ] Journal lisible des bascules dans l'application
- [ ] Compte par projet

## Points mineurs reportés

- [ ] Réveil précis au début de la plage horaire
- [ ] Réglages invalides édités à la main : valeurs par défaut au lieu d'un échec
- [ ] Heure locale exacte (changement d'heure) pour les plages couvrant 2 h – 3 h
- [ ] `ccs best` : ignorer les comptes en erreur
- [ ] Moniteur de sessions créé même si `~/.claude/sessions` apparaît après le démarrage
