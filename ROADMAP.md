# Feuille de route — CCS

Plusieurs comptes Claude Code sur un PC Linux, comme un seul. Détails de chaque
version : `CHANGELOG.md` ; conceptions et plans : `docs/superpowers/`. Phases terminées
(1 à 35, 39, correctifs) : `docs/ROADMAP-fait.md`.

## Reste à faire (résumé)

- **Jarvis, essais réels** (laptop-maison en ligne) : 36.5 phrase depuis le téléphone hors du
  Wi-Fi, 36.7d essai Pixel et iPhone, 40.3 oreilles sur chaque appareil, puis 36.8 release
- **Réseau maillé** : 38.4 fusion de Ricochet (38.4b attend la décision de Charles), 38.5 retrait
  de l'ancien transport du relais, 38.6 tests et releases
- **Essai** : 37.4 « ajouter un PC » sur un vrai nouveau PC
- **Plus tard** : 37.5 « Ajouter un PC » dans les applis, 31.10 onglets shell du bureau

## Phase 41 — Onglets Réseau, Fichiers et Jarvis sur le bureau (1.10.0) ✅

Charles (24/11/2026) : l'application du bureau n'a pas les onglets Réseau, Jarvis et Fichiers du web.

- [x] 1. Onglet Réseau : appareils du réseau maillé (chemin, « Mesurer » par `tailscale ping`) puis machines, travaux, lancement et secours Ricochet (la page Machines quitte les Réglages)
- [x] 2. Onglet Fichiers : arbre d'un dossier (personnel au départ, « Changer de dossier ») et éditeur
- [x] 3. Onglet Jarvis : ouvre la page Jarvis du serveur CCS dans le navigateur, ou mène aux Réglages sans serveur
- [x] 4. `gui --page reseau|fichiers|jarvis`, Ctrl+1 à Ctrl+6, tests
- [x] 5. Release 1.10.0

## Phase 31 — Relance après une limite, sur toutes les interfaces (0.36.0)

Charles (21/11/2026) : une session arrêtée par une limite de Claude Code doit repartir seule
quand la limite est levée, sur le bureau, la TUI, le web, Android et l'iPhone.

- [x] 1. `limit_resume` : heure de levée (fenêtre de 5 h, semaine, autre compte libéré), marqueurs « planned » / « lifted », verrou du hook, une bascule et une notification pour toutes les sessions bloquées
- [x] 2. Hook StopFailure : relance prévue dès la limite (aucun compte libre, bascule impossible, pause), heure dans la notification, dossier de la conversation gardé
- [x] 3. Service, application et pont font avancer les marqueurs (le premier qui a le verrou agit)
- [x] 4. Onglets du terminal et chats du bureau : bandeau « relance prévue à HH:MM », « continue » à la levée
- [x] 5. Chats du pont (web, Android, iPhone, TUI) : note dans le fil, « continue » à la levée ; marqueur de secours si le hook n'a rien écrit ; notes du pont affichées dans la TUI
- [x] 6. Terminaux de la version web : `claude` lancé à la main relancé aussi
- [x] 7. Hors de CCS : notification, ou `claude --resume … -p continue` en arrière-plan (réglage)
- [x] 8. Réglage `limit_resume` (bureau, web, Android, iPhone), tests, docs, release 0.36.0
- [x] 9. Essai réel par Charles lors d'une vraie limite (bureau, téléphone)
- [ ] 10. Plus tard : onglets shell du bureau où `claude` est lancé à la main (aujourd'hui : notification)

## Phase 36 — Oreilles de Jarvis

Charles (22/11/2026) : CCS devient le transport des « oreilles » de Jarvis (assistant vocal,
projet voisin `~/Work/perso/Jarvis`, plan `docs/oreilles-ccs.md` de Jarvis) : parler à Jarvis
avec un bouton depuis la version web, puis depuis les applis, même hors de la maison. Le cerveau
tourne sur `laptop-maison` (port 7341, WebSocket sur TLS épinglé) ; le pont du serveur l'atteint
par le tunnel Ricochet. CCS ne fait que relayer : le cerveau garde l'appairage, le jeton et la
vérification de la voix.

- [x] 1. Pont : `jarvis_link` (tunnel `ricochet-agent tunnel`, TLS 1.3 épinglé sur l'empreinte SHA-256 du certificat, client WebSocket) et `bridge_jarvis` (`jarvis.open`, `send`, `close`, `settings`, `configure` ; événements `jarvis.message`, `jarvis.closed`), réglages `jarvis.machine`, `jarvis.port`, `jarvis.fingerprint`
- [x] 2. ccs-web : `/api/jarvis/oreille` (mêmes contrôles que `/api/ws` : origine, session, jeton d'application ou Portier, revérification, déconnexion), relais texte et binaire, limites de taille, erreur claire (`relay_error`, code 4011)
- [x] 3. Web : page « Jarvis » (appairage par l'adresse `jarvis://pair?…` ou code + empreinte, jeton gardé dans le navigateur ; bouton maintenir / toucher pour parler, micro rééchantillonné en 16 kHz, texte et voix de la réponse)
- [x] 4. Tests (faux cerveau TLS local, faux `ricochet-agent`, ccs-web de bout en bout, page dans node), README, CHANGELOG
- [ ] 5. Essai réel par Charles : `jarvis pair`, une phrase depuis le téléphone hors du Wi-Fi (le pont joint laptop-maison par le réseau maillé, 100.64.0.5 : plus besoin d'autoriser le port 7341 dans le tunnel Ricochet ; Jarvis 0.6.1 y tourne depuis le 23/11)
- [x] 6. Bureau (GTK) : menu principal → « Parler à Jarvis… » ouvre la page web Jarvis du serveur appairé
- [x] 7. Applis Android et iPhone : bouton Jarvis sur le même relais (voir README, « Parler à Jarvis »)
  - [x] 7a. Logique commune testée (`logique/Jarvis.kt`, `Logique/Jarvis.swift`) : adresse `jarvis://pair?…`, messages `pair` / `hello` / `wake` / `listen_start` / `listen_end`, lecture des réponses du cerveau et du relais, trames `0x01`, rééchantillonnage 16 kHz, phrase (14 s, silence, rien dit)
  - [x] 7b. Android : écran Plus → Parler à Jarvis (appairage, bouton maintenir / toucher), `AudioRecord` + `AudioTrack`, coffre chiffré, permission micro, raccourci d'appli et liens `ccs://jarvis`, `jarvis://pair`
  - [x] 7c. iPhone : même écran, `AVAudioEngine` + `AVAudioPlayer`, trousseau, App Intent « Parler à Jarvis », liens `ccs://jarvis`, `jarvis://pair`
  - [ ] 7d. Construire sur Codemagic (workflows `android` et `ios-natif`, jamais compilé ici) et essayer sur le Pixel et l'iPhone — construit et installé (1.8.0 Pixel, 1.8.1 iPhone par SideStore) ; reste l'essai avec laptop-maison
- [ ] 8. Release (version mineure) après l'essai réel

## Phase 37 — Ajouter un PC en une ligne (1.2.0, Ricochet 0.6.0)

Charles (22/11/2026) : faciliter le plus possible l'ajout d'un PC au réseau de machines. Choix :
le relais garde 15 min, pour une seule lecture, le script d'installation de la machine
(`/rejoindre/<code>`) ; CCS le demande avec le jeton opérateur et donne la ligne à coller.

- [x] 1. Ricochet : `POST /api/machines` accepte `utilisateur`, `ports`, `cles_ssh` et renvoie `lien` ; `GET /rejoindre/{code}` sert le script (agent, configuration, serveur SSH, clés autorisées) une seule fois ; interface : case « Joignable en SSH », clés, ligne courte
- [x] 2. CCS : `ccs distant ajouter`, méthode `machines.add`, section « Ajouter un PC » de la page Machines du web ; tests, README, CHANGELOG
- [x] 3. Releases Ricochet 0.7.0 et CCS 1.2.0, relais mis à jour, `jeton_operateur` dans `client.toml` du VPS
- [ ] 4. Essai réel par Charles sur un nouveau PC
- [ ] 5. Plus tard : « Ajouter un PC » dans l'appli du bureau, Android et iPhone ; option qui installe aussi CCS et Claude Code (sessions entières sur la machine, piste 13 de la phase 21)

## Phase 38 — Réseau maillé de tous les appareils (network.mawena.cloud)

Charles (23/11/2026) : fusionner Ricochet dans CCS et relier tous ses appareils par internet comme
sur un réseau local, en passant par le LAN quand deux appareils y sont ensemble. Choix : WireGuard
en maillage avec **Headscale** (coordination, sur le VPS) et le client **tailscale** sur chaque
appareil (appli de l'App Store sur l'iPhone : pas de NetworkExtension avec SideStore). Chemin choisi
tout seul : LAN, puis direct par internet (percement de NAT), puis relais DERP du VPS. Noms de
domaine en anglais : `network.mawena.cloud`, noms des machines en `<machine>.mesh.mawena.cloud`.

- [x] 1. VPS : Headscale 0.29.7 (`network.mawena.cloud` derrière nginx, DERP intégré, STUN UDP 3478), VPS inscrit (100.64.0.1)
- [x] 1b. Inscrire pc-bureau et laptop-maison (`ccs reseau cle --nom <machine>`, puis les deux lignes en root) — pc-bureau (`lp-work`, 100.64.0.2), laptop-maison (100.64.0.5, 23/11)
- [x] 2. CCS : `ccs reseau` (fait en 1.3.0 : état, machines, chemin LAN/direct/relais, clé d'inscription jetable) ; le lien « Ajouter un PC » installe aussi tailscale et inscrit la machine (1.6.0)
- [x] 3. Onglet « Réseau » à droite de Sessions (Charles, 23/11 : jolie DA, icônes ; web d'abord, installé, puis Android, puis iPhone)
  - [x] Web : carte du réseau, fiches (adresses publiées, trafic, ping réel, renommer, retirer), ajout PC / Android / iPhone (1.4.0)
  - [x] Android (1.5.0)
  - [x] iPhone (1.5.0)
  - [x] Web : l'ajout d'appareil ne revient plus sur « PC Linux » au rafraîchissement (1.5.1)
- [ ] 4. Fusion de Ricochet dans le dépôt CCS (crates Rust, paquets) ; `ccs distant`, root et travaux passent par les IP du réseau maillé
  - [x] 4a. `ccs distant` (et donc les travaux) en SSH direct sur l'adresse du réseau maillé, Ricochet en secours (1.6.0) ; root n'utilise Ricochet que pour le nom de la machine
  - [ ] 4b. Déplacer le code de Ricochet dans le dépôt (à décider avec Charles : coût de construction Rust à chaque release)
- [ ] 5. Pixel inscrit le 23/11 (`pixel-4-xl`, 100.64.0.3, appli Tailscale par adb) : pc-bureau ↔ Pixel passe par le LAN (10.228.2.44, 18 ms) ; VPS ↔ Pixel par relais DERP. iPhone inscrit le 23/11 (`iphone`, 100.64.0.4). Reste le retrait de l'ancien transport du relais. (Le Pixel est sur le même réseau local que pc-bureau : leur liaison doit passer par le LAN, à vérifier avec `ccs reseau etat`.) Pixel et iPhone dans le réseau (appli Tailscale, serveur personnalisé) ; retrait de l'ancien transport du relais
- [ ] 6. Tests, README, CHANGELOG, releases
- [x] 9. Tout par le réseau maillé, Ricochet en secours (liste des machines, `ccs distant`, Jarvis) ; fiche du serveur nommée « Serveur CCS » ; page Machines fondue dans l'onglet Réseau (1.7.0)
- [x] 7. Root : mot de passe gardé pour toujours, chiffré (AES-256-GCM, `root_vault`), revérifié après redémarrage ; web sans compte à rebours (1.3.0)
- [x] 8. Root « pour toujours » : plus de bandeau rouge nulle part (Charles, 23/11) ; `root.status` rend `kept: false, stored: true`, donc rien à reconstruire dans les applis (1.3.1)

## Phase 40 — Jarvis maître de tout le réseau CCS

Charles (23/11/2026) : Jarvis doit avoir un accès global au réseau CCS (sessions, sous-agents,
machines, travaux), pour des ordres comme « tue le premier sous-agent de la session GliGli ». Et
utiliser Claude (comptes CCS) comme cerveau d'appoint quand les données ne sont pas sensibles, le
cerveau local de laptop-maison prenant le relais quand plus aucun compte n'a de quota.

- [x] 1. Outils de Jarvis côté CCS (CCS 1.8.0 : `jarvis.*` ; côté Jarvis : branche feature/outils-ccs) : méthodes du pont exposées à Jarvis (lister sessions et sous-agents, arrêter, lancer, état des machines et travaux), avec confirmation vocale pour les actions destructrices
- [x] 2. (Jarvis 0.6.0 : `routage = local` par défaut tant que la règle n'est pas validée ; famille, adresse, micros de la maison sans ordre explicite restent locaux) Routage du cerveau : Claude (`ccs meilleur`) si la demande n'est pas sensible et qu'un compte a du quota, sinon le cerveau local ; règle de sensibilité à fixer avec Charles
- [ ] 3. Oreilles partout (iPhone, Pixel, lp-work, lp-home) avec dédoublonnage quand plusieurs entendent la même phrase — dédoublonnage fait côté cerveau (Jarvis 0.6.1 : une phrase traitée une fois, le bouton gagne toujours) ; reste les oreilles sur chaque appareil
