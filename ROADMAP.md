# Feuille de route — CCS

Claude Code partout : tous les appareils (bureau, web, Android, iPhone), toutes les machines
(réseau maillé, calcul réparti), tous les comptes (comme un seul). Détails de chaque
version : `CHANGELOG.md` ; conceptions et plans : `docs/superpowers/`. Phases terminées
(1 à 35, 38, 39, 41, correctifs) : `docs/ROADMAP-fait.md`.

## Reste à faire (résumé)

Tout ce qui reste attend un essai réel par Charles :

- **Jarvis** (laptop-maison en ligne) : 36.5 phrase depuis le téléphone hors du Wi-Fi, 36.7d essai
  Pixel et iPhone, 40.3 oreilles sur chaque appareil, puis 36.8 release
- **Ajouter un PC** : 37.4 essai sur un vrai nouveau PC

En cours : **phase 42, son partagé** (le son d'un appareil joué sur un autre, dans tous les sens).

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
- [x] 5. (1.11.0) « Ajouter un PC » dans l'appli du bureau, Android et iPhone ; option qui installe aussi CCS et Claude Code (sessions entières sur la machine, piste 13 de la phase 21)

## Phase 40 — Jarvis maître de tout le réseau CCS

Charles (23/11/2026) : Jarvis doit avoir un accès global au réseau CCS (sessions, sous-agents,
machines, travaux), pour des ordres comme « tue le premier sous-agent de la session GliGli ». Et
utiliser Claude (comptes CCS) comme cerveau d'appoint quand les données ne sont pas sensibles, le
cerveau local de laptop-maison prenant le relais quand plus aucun compte n'a de quota.

- [x] 1. Outils de Jarvis côté CCS (CCS 1.8.0 : `jarvis.*` ; côté Jarvis : branche feature/outils-ccs) : méthodes du pont exposées à Jarvis (lister sessions et sous-agents, arrêter, lancer, état des machines et travaux), avec confirmation vocale pour les actions destructrices
- [x] 2. (Jarvis 0.6.0 : `routage = local` par défaut tant que la règle n'est pas validée ; famille, adresse, micros de la maison sans ordre explicite restent locaux) Routage du cerveau : Claude (`ccs meilleur`) si la demande n'est pas sensible et qu'un compte a du quota, sinon le cerveau local ; règle de sensibilité à fixer avec Charles
- [ ] 3. Oreilles partout (iPhone, Pixel, lp-work, lp-home) avec dédoublonnage quand plusieurs entendent la même phrase — dédoublonnage fait côté cerveau (Jarvis 0.6.1 : une phrase traitée une fois, le bouton gagne toujours) ; reste les oreilles sur chaque appareil

## Phase 42 — Son partagé sur le réseau maillé

Charles (24/11/2026) : tout appareil du réseau qui peut jouer du son est détecté automatiquement
comme « sortie audio » par les autres, et on envoie le son dans tous les sens : iPhone → pc-bureau,
iPhone → Pixel, pc-bureau → iPhone, etc.

Conception :
- **Annonce** : pas de multicast sur Tailscale, donc pas de mDNS. Chaque appareil CCS annonce au
  serveur CCS (VPS) ce qu'il sait faire : `{appareil, ip maillée, jouer, capter, port}`, renouvelé
  toutes les 30 s, oublié après 90 s. Méthodes du pont `audio.annoncer`, `audio.lister`,
  `audio.envoyer` (demande à la cible de se préparer, puis à la source d'émettre), `audio.arreter`.
- **Transport** : RTP/Opus (RFC 7587) en UDP direct entre adresses 100.64.x, trames de 20 ms,
  48 kHz stéréo, tampon de gigue 60 à 150 ms. Standard : GStreamer/ffmpeg côté Linux, décodeur
  Opus natif côté Android (MediaCodec) et iOS (AudioToolbox). Port UDP 4010.
- **Capter le son** : Linux, moniteur PipeWire de la sortie choisie ; Android 10+,
  AudioPlaybackCapture (accord MediaProjection à chaque départ ; certaines applis l'interdisent) ;
  iPhone, extension de diffusion ReplayKit (lancée depuis le centre de contrôle ; Apple Music,
  Netflix et autres contenus protégés restent muets).
- **Côté PC** : chaque sortie distante apparaît comme une vraie sortie PipeWire (« iPhone de
  Charles ») : n'importe quelle appli peut l'utiliser depuis les réglages du son.
- **Limites** : retard de 100 à 200 ms en direct, nettement plus par un relais Tailscale ; pas
  pour une vidéo synchro par un relais.

- [x] 1. Serveur : registre des sorties audio (annonce, expiration, liste) et méthodes du pont, tests
- [x] 2. Linux : `ccs audio` (lister, envoyer, recevoir), récepteur RTP/Opus, sorties PipeWire virtuelles pour chaque appareil distant, annonce automatique par le démon ; essai pc-bureau ↔ VPS
- [x] 3. Android : récepteur (service au premier plan) et émetteur (AudioPlaybackCapture), annonce, écran « Son » ; APK sur Codemagic
- [x] 4. iPhone : récepteur (lecture en arrière-plan) et extension ReplayKit émettrice, annonce, écran « Son » ; IPA sur Codemagic
- [x] 5. Web et bureau GTK : liste des sorties et bouton « Envoyer le son vers… »
- [ ] 6. Essais réels dans les six sens, README, CHANGELOG, release — lp-work → iPhone marche (24/11) si l'appli est ouverte à l'écran
- [x] 6b. iPhone : recevoir aussi appli en arrière-plan (iOS la suspend : elle rate l'ordre « receive » du pont) — interrupteur « Rester à l'écoute » (écran Son)
- [x] 6c. Latence réduite (trames 10 ms, tampons adaptatifs)
- [x] 6d. Lecteurs MPRIS (VLC, Firefox…) des PC Linux pilotés depuis tous les clients : agent (`audio.report`), pont (`audio.players`, `audio.control`), `ccs audio players` et `control`, section « Lecteurs » de l'écran Son (web, bureau, iPhone, Android)
- [x] 6e. Onglet Son sur toutes les plateformes
  - [x] iPhone : onglet « Son » après Réseau (retiré de Plus)
  - [x] Android : onglet « Son » après Réseau (retiré de Plus)
  - [x] Web : onglet « Son » (#/son) après Réseau, retiré de Réseau
  - [x] Bureau : onglet « Son » (SonPage, Ctrl+4) après Réseau, retiré de Réseau
- [ ] Idée : le téléphone comme lecteur piloté. iOS l'interdit (aucune appli ne peut piloter la lecture des autres) ; Android le permet avec l'accès aux notifications (`MediaSessionManager.getActiveSessions`), à accorder à la main dans les réglages
- [ ] 7. Autres systèmes, dans l'ordre demandé par Charles (Linux, iPhone, Android, puis le reste) :
  agent portable sur macOS (GStreamer, sortie puis source par BlackHole) et Windows (GStreamer,
  `wasapi2src loopback=true`), sans les sorties virtuelles de Linux

## Phase 43 — Sous-agents visibles dans le chat web

Charles (24/11/2026) : dans le chat web, on ne voit pas les sous-agents travailler.

- [x] 1. Sous-agents de fond : le pont lit leur transcription (`subagents/agent-<id>.jsonl`) toutes les 3 s et envoie leurs étapes dans leur vue (`subagents.Tails`)
- [x] 2. Après un rechargement, une reprise ou un `/compact` : pastilles reconstruites depuis `chat.attach` (`agents`), vue remplie depuis la transcription (`chat.agent_log`)
- [ ] 3. Essai réel par Charles (web au téléphone : sous-agent de fond, puis rechargement et `/compact` pendant qu'il tourne)

## Phase 44 — Onglet Réseau du bureau au niveau du web

Charles (24/11/2026) : dans CCS bureau, la partie Réseau n'affiche pas le réseau maillé comme sur
les versions web et mobile.

- [x] 1. `network.overview` partagé par le pont et le bureau ; le bureau appelle `network.*` par le pont du serveur CCS (comme le son partagé), repli sur ce PC
- [x] 2. « Appareils » : fiche dépliable par appareil (genre, en ligne, chemin, adresse à copier, adresses publiées, trafic, Mesurer, Renommer, Retirer confirmé), machine de calcul rattachée
- [x] 3. « Ajouter un appareil » : PC Linux (lien Ricochet ou clé jetable), Android, iPhone
- [x] 4. Ordre du web : Appareils, Son partagé, Travaux, Lancer une commande, Ajouter un appareil, Secours Ricochet ; tests GTK
- [ ] 5. Essai réel par Charles sur pc-bureau (fiches, Mesurer, Renommer/Retirer, clé d'inscription)

## Phase 45 — Market : Facebook Marketplace au Togo

Charles (24/11/2026) : un onglet Market où il pose une question (« le routeur le moins cher
compatible WireGuard à Lomé ») ; Market cherche sur Facebook Marketplace au Togo et répond dans le
chat par un classement avec les liens des annonces. Il peut aussi donner le lien d'un vendeur. Pas
de surveillance ni d'alertes. Décisions : requêtes **toujours par pc-bureau** (`ssh -D` par le
réseau maillé, sortie vérifiée, pas de repli direct) ; compte Facebook personnel (risque connu).

Conception : l'onglet = un chat Claude dédié (`~/.local/share/ccs/market/`, `CLAUDE.md` : mission,
outils, format de réponse) ; Claude appelle `ccs market search|seller|item|status|login` (Bash) et
vérifie les caractéristiques avec WebSearch/WebFetch. Chrome sans interface du VPS (navigateurs de
Playwright, `--no-sandbox` : Ubuntu 24.04 bloque son bac à sable), piloté par CDP avec un petit
client WebSocket écrit dans `market.py` ; cookies exportés une fois par CDP depuis Google Chrome
de pc-bureau (ceux de Chrome Linux sont chiffrés par le trousseau).

- [x] 1. `ccs_app/market.py` : tunnel `ssh -D` vers pc-bureau et vérification de l'adresse de sortie (refus net sans pc-bureau), Chrome sans interface par le tunnel (images bloquées, User-Agent de pc-bureau, fermé après chaque commande), client WebSocket + CDP
- [x] 2. Lecture : cartes `prix | titre | ville` (prix en CFA, ancien prix), page d'annonce (`Détails` → état, description ; `Informations vendeur` → vendeur), page de connexion détectée
- [x] 3. Vendeur : fenêtre `div[role="dialog"]` du vendeur, jamais Messenger ; défilement et union des annonces jusqu'à 5 tours sans nouveauté (limite 600)
- [x] 4. Session : `ccs market login` (Chrome sur l'écran de pc-bureau, export des cookies par CDP, fichier 600), cookies réinjectés et remis à jour à chaque commande
- [x] 5. CLI `ccs market search|seller|item|status|login` (`--json`, anciens noms français cachés), codes de sortie 2 (pc-bureau absent) et 3 (session)
- [x] 6. Chat Market : dossier, `CLAUDE.md`, droits des outils ; `market.open` du pont (rejoint le chat ouvert ou reprend la dernière conversation)
- [x] 7. Onglet Market du web (chat monté dans l'onglet) et du bureau GTK (ouvre le chat dans Sessions)
- [x] 8. Tests (fixtures, faux CDP, faux SOCKS, pont, web dans node, GTK), README, man, interfaces
- [x] 9. Tunnel SOCKS réel vers pc-bureau vérifié depuis le VPS (sortie 156.38.73.89, pas 84.46.246.202) ; Chrome sans interface par ce tunnel
- [ ] 10. Connexion réelle par Charles : `ccs market login` devant pc-bureau
- [ ] 11. Essai réel par Charles : vendeur https://www.facebook.com/marketplace/profile/100058059515617/ (Mozich Trompa, Lomé), « routeur le moins cher compatible WireGuard » → attendu : Cudy AC1200 dual band 22 000 CFA (https://www.facebook.com/marketplace/item/2421778705023492/, client WireGuard d'origine, WR1200) ; alternatives Cudy WR1300 25 000, MikroTik hAP lite 22 000 (déconseillé, instable sous RouterOS 7), TP-Link 842N 7 000 (OpenWrt seulement)
- [ ] 12. Essai réel de la recherche par mot-clé (`/marketplace/lome/search?query=…`) : ville `lome` à confirmer, sélecteurs des cartes à ajuster si besoin
- [ ] 13. Plus tard : onglet Market dans les applis Android et iPhone


## Phase 46 — Fournisseurs de modèles (OpenRouter et autres, budget 50 $/mois)

Charles (24/11/2026) : faire tourner Claude Code chez d'autres fournisseurs (OpenRouter d'abord)
pour des modèles peu censurés, avec un budget de 50 $/mois au plus (clé plafonnée côté fournisseur).
Principe : `claude --settings '<json>' --model <id>` (ANTHROPIC_BASE_URL, alias opus/sonnet/haiku
et sous-agents sur le modèle choisi, `apiKeyHelper` qui lit la clé dans un fichier 600 ; clé
jamais dans la ligne de commande).

- [x] 1. `ccs_app/providers.py` : préréglage OpenRouter, `~/.config/ccs/providers.json`, clé `~/.config/openrouter/cle` (600)
- [x] 2. `ccs provider list|show|models|key|test` (ancien nom `fournisseur` caché), variable `CCS_PROVIDER`
- [x] 3. Branchements : options de lancement, onglets du terminal (libellé), tâches (`--provider`), exécuteur de tâches, chats (fournisseur figé à l'ouverture)
- [x] 4. Dialogue GTK « Nouvelle session » (fournisseur, modèles, clé absente signalée) et web (nouvelle session, chat, `chat.providers` du pont)
- [x] 5. Fusion de develop (commandes en anglais) ; test du pont `chat.open` corrigé (option `provider`)
- [x] 6. Comparatif des prix (OpenRouter, Venice, DeepInfra, Together, Featherless, Chutes, API directes DeepSeek, Moonshot, Z.ai) : modèles puissants avec outils, peu filtrés
- [x] 7. Modèles par défaut à jour dans les préréglages (identifiants vérifiés au catalogue OpenRouter) ; préréglage `deepseek` (API directe compatible Anthropic, la moins chère pour DeepSeek)
- [x] 8. Essai du dialogue GTK sous Xvfb et tests web
- [x] 9. Documentation : README, `docs/man/ccs.1`, CHANGELOG
- [x] 10. Essai réel sur le VPS : `ccs provider test openrouter` répond (GLM 5.3 et Nemotron gratuit) ; l'essai se limite à 256 jetons de sortie (sinon 402 avec peu de crédit)
- [x] 10b. Défaut OpenRouter : DeepSeek V4.1 Flash `deepseek/deepseek-v4.1-flash-1017:floor` (OpenRouter choisit l'hébergeur le moins cher, ~0,03-0,05/0,10-0,50 $ avec cache), choix de Charles ; GLM 5.3 reste dans la liste
- [ ] 11. Charles : créditer OpenRouter, clé plafonnée à 50 $/mois ; essai d'une vraie session (bureau, web, tâche)
- [x] 12. Release 1.13.0

## Phase 47 — Venice et autres services compatibles OpenAI (proposée)

Venice (modèles « uncensored » avec outils : `glm-5-3-flash-uncensored`,
`deepseek-v4-1-flash-1017-uncensored`, Venice Uncensored 1.2) ne parle que l'API OpenAI.

- [ ] 1. Proxy local claude-code-router (ou LiteLLM) lancé à la demande par CCS, traduit `/v1/messages` vers l'API OpenAI
- [ ] 2. Préréglage `venice` (clé `~/.config/venice/cle`) pointant sur ce proxy ; vérifier l'appel d'outils de bout en bout
- [ ] 3. Arrêt du proxy avec la dernière session (RAM)

## Phase 48 — Nouvelle session : le bureau comme le web

Le dialogue des paramètres d'une session ne s'affichait pas au bureau (ouverture directe d'un
chat) ; il doit se comporter comme la feuille du web.

- [x] 1. Cause : bouton « Nouvelle session » d'un projet et « Nouvelle session » d'un chat au cache expiré sans dialogue ; dialogue de `--nouvelle-session` présenté avant l'affichage de la fenêtre
- [x] 2. Tout nouveau chat passe par le dialogue (bouton du projet, cache expiré, bouton et menu, raccourci) ; la reprise d'une conversation reste directe, comme au web
- [x] 3. Source commune des champs : `chat_options.new_session_form` (modèles, effort, droits, droits par défaut), envoyée au web par `chat.providers`
- [x] 4. Dialogue du bureau : dossier, compte, fournisseur, modèle, effort, droits, boutons Terminal et Ouvrir un chat ; droits par défaut `chat.rights`
- [x] 5. Effort dans `LaunchSpec` (`--effort`, Claude seulement) et dans la feuille web
- [x] 6. Tests : dialogue sous Xvfb (ordre, défauts, effort, boutons, fenêtre pas encore affichée), bouton de projet, cache expiré, `new_session_form`, effort, `chat.providers`
- [x] 7. Release 1.14.0


## Phase 49 — Market en option, ordre des onglets, chat riche

Market devient une option de la nouvelle session ; les onglets finissent par Jarvis, Analyse,
Réglages ; les réponses de Claude affichent images, sons, vidéos et composants (blocs `ccs`).

- [x] 1. Market : option « Market (Marketplace Facebook) » de la nouvelle session (web et bureau), plus d'onglet Market ; la CLI ne change pas
- [x] 2. Onglets : …, Jarvis, Analyse, Réglages (web et bureau)
- [x] 3. Web : images agrandissables, lecteurs de sons et de vidéos (https ou fichiers locaux lus par l'explorateur), blocs `ccs` choix, formulaire, carte, cartes ; CSP `media-src 'self' blob: https:`
- [x] 4. Bureau : choix, carte et cartes, photos https des cartes, lecteurs des médias locaux
- [x] 5. Claude averti par `RICH_HINT` ; Market présente ses annonces en cartes et propose des choix
- [x] 6. Tests (web, bureau sous Xvfb, moteur du chat, marché) ; `docs/chat-riche.md`
- [ ] 7. Vérifier à l'écran : web (téléphone et ordinateur) et bureau, avec une vraie recherche Market
- [x] 8. Bureau : formulaire, images Markdown https et médias distants
- [ ] 9. Rendu riche dans l'appli iOS
- [ ] 10. Rendu riche dans l'appli Android
- [x] 11. Release 1.15.0 (avec les lecteurs et l'onglet Son de la phase 42)
