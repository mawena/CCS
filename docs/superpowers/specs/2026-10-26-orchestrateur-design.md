# CCS 0.2.0 — orchestrateur multi-comptes

Date : 2026-10-26 · Statut : validé en conversation (« vas y sur ça »)

## Intention

Tirer le maximum de plusieurs abonnements modestes (2 ou 3 comptes Pro) en
organisant automatiquement leurs fenêtres de 5 h : quand un compte est épuisé,
un autre est disponible, et du quota frais arrive régulièrement. Le README doit
rendre clair ce cas d'usage : un palier intermédiaire entre Pro (20 $) et Max
(100 $), sans promettre de contourner les conditions d'Anthropic.

## Règles (validées)

1. **Enchaîner** : pendant la plage horaire active, un compte au repos dont le
   créneau du jour est arrivé reçoit une requête minimale (warm-up) qui démarre
   sa fenêtre. Après la fin d'une fenêtre, la suivante démarre aussitôt.
2. **Décaler** : le premier créneau du jour de chaque compte participant est
   `début de plage + k × 5 h / N` (k = rang du compte par nom, N = comptes
   participants). Ensuite, enchaînement pur ; recalage chaque jour.
3. **Utiliser d'abord le quota qui expire** : bascule anticipée vers un compte
   dont la fenêtre se termine dans ≤ 60 min avec ≥ 30 % restants, si sa fin
   de fenêtre est plus proche que celle du compte actif. Au plus une toutes les
   30 min ; bascule manuelle < 5 min respectée ; données fraîches obligatoires.
4. **Répartir la semaine** : un compte en avance de plus de 10 points sur le
   rythme hebdomadaire passe en réserve (choisi en dernier). Un compte ≥ 95 %
   sur la semaine ne participe plus aux démarrages.

## Comportements

- Plage active par défaut 08:00 → 02:00 (passe minuit), tous les jours ;
  aucun démarrage hors plage.
- Réveil précis : le service se réveille 30 s après la prochaine fin de fenêtre
  ou le prochain créneau, au lieu d'attendre son relevé de 5 min.
- Une tentative de démarrage par compte au plus toutes les 15 min.
- Démarrage : même mécanisme que le warm-up (dossier de configuration
  temporaire, jamais de renouvellement du jeton actif pendant qu'une session
  tourne), journalisé `warmup` avec `mode: "orchestrateur"`.
- Planning : pour chaque compte, fenêtre en cours et fenêtres prévues jusqu'à
  la fin de la plage ; recharges à venir. Exposé dans `state.json`, `ccs plan`
  et un onglet « Planning ».
- Orchestrateur désactivé par défaut (nouvelles installations) ; `ccs orch on`,
  interrupteur dans Réglages. Les créneaux fixes de 0.1.0 restent disponibles.

## Non-objectifs

Pas d'activité hors plage horaire ; pas de prédiction du travail futur de
l'utilisateur ; aucune modification de la bascule à seuil (98 %) existante.

## Décisions de Claude

- Plage par défaut 08:00 → 02:00 (Charles n'a pas précisé ; son usage montre
  une activité jusqu'à 2 h).
- Rang de décalage par ordre alphabétique des profils (stable, prévisible).
- Seuils 60 min / 30 % / 30 min / réserve 10 pts, réglables.
- Orchestrateur activé sur le poste de Charles à la livraison (il l'a demandé),
  désactivé par défaut pour les autres.
