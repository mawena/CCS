# Phase 13 (0.11.0) — CCS sur le VPS : conception

Demandée par Charles le 15/11/2026, prioritaire sur la phase 14 (Git, tâches, chat,
téléphone, en pause sur `feature/phase14`). Choix de Charles : connexion **uniquement par
les comptes Ubuntu**, **double authentification obligatoire**, architecture **A** (tout dans
CCS, sur le modèle de Cockpit), une release **0.11.0**.

## Intention

Piloter CCS sans être devant le PC : depuis Internet (`https://ccs.mawena.cloud`, surtout
au téléphone), depuis un terminal sur le VPS (`ccs tui` par SSH), et depuis l'application
GTK du bureau, connectée aux projets du VPS. Installer CCS sur le VPS, c'est un
`apt install` : le service web démarre, Claude Code est installé, il ne reste qu'à créer le
site avec lnmp.

Réussite : depuis le téléphone, Charles se connecte (mot de passe Ubuntu + code), ouvre un
projet du VPS, discute avec Claude, répond aux autorisations, voit les fichiers et la
feuille de route ; il retrouve la même session depuis le bureau GTK et depuis `ccs tui`.

## Objectifs, non-objectifs, anti-objectifs

Objectifs : serveur, connexion, version web responsive, version terminal, bureau connecté,
paquets, mise en ligne, installation de Claude Code. Détail ci-dessous.

Non-objectifs (cette phase) :
- La page Git, « Faire une tâche », les changements de la session, Ctrl+F, les messages
  enregistrés, Compacter, `!`, les réponses du téléphone : phase 14. La version web et le
  bureau connecté les recevront avec elle.
- Des comptes propres à CCS ; l'administration des comptes Ubuntu (on les utilise, on ne les
  crée pas).
- Plusieurs serveurs web CCS derrière un même domaine ; IPv6 et HTTP sans proxy.

Anti-objectifs (échec même si cela « marche ») :
- Une partie exposée à Internet tourne en root, ou une faille du serveur web suffit pour
  piloter le compte d'un utilisateur sans sa session.
- On se connecte sans le code de double authentification, ou `root` peut se connecter.
- La version web est inutilisable au téléphone (texte minuscule, boutons hors d'atteinte,
  défilement horizontal).
- Le bureau GTK devient moins fluide, ou une panne réseau bloque l'interface.

## Règles communes

Celles de la phase 11 (`2026-11-11-phase-11-design.md`, « Règles communes ») restent
valables. En plus :
- Aucun vrai PAM, systemd, nginx ni réseau dans les tests : authentification, lancement des
  ponts et horloge injectés ; serveur testé par `aiohttp.test_utils` sur un port local
  éphémère ; sockets Unix dans un dossier temporaire.
- Jamais de mot de passe, de secret TOTP, de jeton ni de cookie dans un journal, un message
  d'erreur, un test enregistré ou un commit.
- Rien n'est installé ni lancé sur le VPS sans que Charles l'ait demandé ; la mise en ligne
  (DNS, lnmp) reste faite par lui, guidée.

## Architecture

```
navigateur / téléphone / bureau GTK / ccs tui (distant)
        │ HTTPS ccs.mawena.cloud — nginx (site lnmp) → 127.0.0.1:8420
  ccs-web      utilisateur système `ccs-web`, sans droits : pages, API, WebSocket
        │ /run/ccs/auth.sock
  ccs-auth     root, minuscule : PAM + groupe `ccs` + TOTP, sessions, démarre les ponts
        │ systemctl start ccs-bridge@<utilisateur>
  ccs-bridge   sous l'utilisateur connecté : chats (ChatEngine), comptes, fichiers,
               feuille de route, historique, analyse, réglages, terminaux
        └ /run/ccs/bridge/<utilisateur>.sock
```

### ccs-auth (root)
- Service systemd `ccs-auth.service`, socket Unix `/run/ccs/auth.sock` (`0660`,
  `root:ccs-web`), protocole JSON par lignes. Ne parle qu'à `ccs-web`.
- Connexion : refuse `root` et tout utilisateur hors du groupe Unix `ccs` (sans dire
  lequel des deux a échoué) ; vérifie le mot de passe par PAM, service `/etc/pam.d/ccs`
  (`@include common-auth` et `common-account`) ; puis le code TOTP.
- TOTP (`python3-pyotp`) : secret par utilisateur dans `/var/lib/ccs/totp/<utilisateur>`
  (`0600 root`). Sans secret, la connexion renvoie un secret provisoire et son QR code
  (`python3-qrcode`, SVG) ; il n'est enregistré qu'après un premier code juste.
  Réinitialisation : `sudo ccs totp reinitialiser <utilisateur>`.
- Appareil retenu 30 jours : jeton d'appareil (cookie séparé) qui dispense du code, jamais
  du mot de passe.
- Limites : 5 échecs par utilisateur ou par adresse IP en 15 min → refus pendant 15 min ;
  chaque connexion et chaque refus va au journal (utilisateur, IP, motif ; jamais le mot de
  passe).
- Sessions : jeton aléatoire de 32 octets, seule son empreinte est gardée
  (`/var/lib/ccs/sessions.json`, `0600 root`) ; expire après 12 h sans activité et 7 jours
  au plus. Jetons d'application (bureau, `ccs tui`) : longs, nommés, révocables depuis les
  Réglages ; ils remplacent mot de passe et code, une fois l'appareil appairé avec les deux.
- Après une connexion réussie : `systemctl start ccs-bridge@<utilisateur>` et remise à
  `ccs-web` d'un **ticket** (HMAC du jeton de session par un secret propre au pont, connu
  de `ccs-auth` et du pont seulement). Le pont refuse toute requête sans ticket valide :
  compromettre `ccs-web` seul ne suffit pas à piloter un compte.

### ccs-web (sans droits)
- Service `ccs-web.service`, utilisateur système `ccs-web` créé par le paquet ;
  `python3-aiohttp` ; écoute `127.0.0.1:8420` (réglable) et nulle part ailleurs.
- Sert l'interface (`/usr/share/ccs/web/`), l'API de connexion (`/api/login`,
  `/api/logout`, `/api/totp`), et un WebSocket par client (`/api/ws`) relayé vers le pont de
  l'utilisateur.
- Cookies `HttpOnly`, `Secure`, `SameSite=Strict` ; en-têtes stricts (CSP sans script en
  ligne, `frame-ancestors 'none'`) ; WebSocket refusé si `Origin` n'est pas le site ;
  `X-Forwarded-For` cru seulement venant de `127.0.0.1`.

### ccs-bridge (sous l'utilisateur)
- Service gabarit `ccs-bridge@.service` (`User=%i`), lancé par `ccs-auth`, arrêté après
  12 h sans client et sans chat en cours. Socket `/run/ccs/bridge/<utilisateur>.sock`.
- Réutilise les modules sans GTK de CCS : `ChatEngine` (le chat vit dans le pont et survit
  aux déconnexions), `core`/`store` (comptes Claude et usage), `sessions`, `conversations`,
  `preview`, `roadmap`, `file_tree`, `transcripts`, `tasks`, `settings`.
- Protocole : JSON-RPC sur le socket (requêtes, réponses, événements poussés). Les
  événements du chat sont les objets de `chat_protocol` sérialisés avec leur type, pour que
  le bureau GTK reconstruise exactement ce qu'il reçoit en local.
- Markdown rendu côté pont (`python3-markdown-it`, HTML nettoyé), pour que la version web
  n'embarque pas de moteur Markdown.
- Terminaux shell : pseudo-terminal dans le pont, flux par le WebSocket.
- Au premier démarrage, si Claude Code manque pour cet utilisateur, le pont lance
  l'installeur officiel (voir « Paquets ») et le signale.
- Sur le VPS, il n'y a pas de session graphique pour démarrer le service utilisateur
  `ccs-daemon` (usage, bascule automatique, orchestrateur, file de tâches) : si ce service
  n'est pas actif pour l'utilisateur, le pont fait tourner la même boucle (`daemon`) en son
  sein, et l'arrête si le service apparaît. Choix de Claude.

## Version web

- Fichiers statiques écrits à la main, sans outil de construction : `index.html`, modules
  JS, `style.css`, et xterm.js (MIT) embarqué pour les terminaux. Installable sur l'écran
  d'accueil du téléphone (manifeste et service worker, hors ligne : page « reconnexion »).
- Mêmes écrans que le bureau : **Accueil** (comptes Claude, jauges, ligne d'état, file de
  tâches), **Sessions** (onglets de chat et de shell, ouvrir ou reprendre une conversation,
  historique), **Fichiers / Feuille de route** à gauche, fichier ouvert (lecture, édition
  simple, aperçu Markdown), **Analyse**, **Réglages** (dont Appareils : jetons et appareils
  retenus, avec révocation). Même couleur par compte, clair et sombre.
- Chat : messages, Markdown, cartes d'actions repliables, autorisations (Autoriser,
  Toujours, Refuser), questions de Claude, liste de tâches épinglée, file de messages,
  barre modèle / effort / droits, Arrêter, images jointes.
- Téléphone (moins de 720 px de large) : une colonne ; panneau de gauche et fichier en
  tiroirs ; saisie collée en bas, au-dessus du clavier ; cibles tactiles d'au moins 44 px ;
  aucun défilement horizontal hors des blocs de code.
- Connexion : identifiant Ubuntu et mot de passe, puis code ; à la première connexion, QR
  code à scanner et premier code à saisir ; case « Retenir cet appareil 30 jours ».
- Ajout d'un compte Claude sur le VPS : par un onglet shell qui lance `ccs add <nom>` (le
  lien de connexion s'ouvre sur le téléphone ou le PC, le code est collé dans le terminal).

## Version terminal (`ccs tui`)

- Plein écran, `python3-urwid`. Sur le VPS, par SSH : parle au pont local de l'utilisateur
  (lancé au besoin sous lui, sans mot de passe ni code : il est déjà connecté). Ailleurs :
  `ccs tui --serveur https://ccs.mawena.cloud` (appairage par mot de passe et code, puis jeton
  d'application gardé dans `~/.claude-accounts/serveurs.json`, `0600`).
- Écrans : projets et sessions, chat (messages, actions en une ligne, autorisations au
  clavier : 1 / 2 / 3 comme au bureau), feuille de route (cocher), comptes et usage.

## Bureau GTK connecté

- Réglages → **Serveurs** : ajouter un serveur (adresse, identifiant, mot de passe, code ;
  appairage → jeton d'application nommé d'après le PC), le retirer, voir son état.
- Page Sessions : les projets et conversations du serveur apparaissent sous son nom ; un
  onglet ouvert sur un projet distant porte le nom du serveur dans son titre et sa couleur.
- Le chat distant utilise un `RemoteChatEngine` avec la même interface et les mêmes
  événements que `ChatEngine` : `ChatTab` ne voit pas la différence. Fichiers et feuille de
  route passent par l'API (arbre, lecture, écriture, case cochée).
- Onglet shell distant : le terminal VTE lance `ccs shell-distant <serveur> <projet>`, petit
  relais entre le pseudo-terminal local et celui du pont.
- Réseau coupé : bandeau « Serveur injoignable, reconnexion… », reconnexion automatique,
  jamais de blocage de l'interface ; les messages tapés pendant la coupure attendent dans
  la file.

## Paquets

Une source, trois paquets binaires :
- **`ccs`** : commandes, service utilisateur `ccs-daemon`, pont, `ccs tui` ; dépend de
  Python et des modules sans interface (`python3-markdown-it`, `python3-urwid`) ;
  **recommande** `ccs-bureau`.
- **`ccs-bureau`** : l'application GTK et l'icône (dépendances GTK, VTE, GtkSourceView,
  AppIndicator, actuelles de `ccs`). Une mise à jour de `ccs` sur un bureau l'installe
  (nouvelle recommandation), rien ne disparaît.
- **`ccs-serveur`** : `ccs-auth`, `ccs-web`, `ccs-bridge@` et la version web ; dépend de
  `ccs`, `python3-aiohttp`, `python3-pam`, `python3-pyotp`, `python3-qrcode` ; crée
  l'utilisateur `ccs-web` et le groupe `ccs`, active et démarre les services.
- `scripts/build-deb.sh` construit les trois `.deb` (tests une fois), `SHA256SUMS` les
  couvre, `scripts/publier-apt.sh` les publie ensemble dans le dépôt APT, et la release
  GitHub les joint tous.
- Sur le VPS : `sudo apt install --no-install-recommends ccs-serveur` (sans les paquets
  graphiques) puis `sudo adduser charles-gamligo ccs`. Les deux commandes sont dans le README
  et rappelées par `ccs doctor`.
- **Claude Code** : à l'installation de `ccs`, s'il manque, l'installeur officiel
  (`curl -fsSL https://claude.ai/install.sh | bash`) est lancé pour l'utilisateur qui
  installe (`SUDO_USER` ou `PKEXEC_UID`), jamais en root, sans faire échouer le paquet hors
  ligne ; le pont et l'application le reprennent au premier démarrage s'il manque encore.

## Mise en ligne (relevé du VPS le 15/11)

Ubuntu 24.04, nginx et certbot en place, sites gérés par lnmp, port 8420 libre, DNS chez
Hostinger (`dns-parking.com`), `mawena.cloud` → `84.46.246.202`.
1. DNS Hostinger : enregistrement `A`, nom `ccs`, valeur `84.46.246.202`.
2. `sudo lnmp add --id ccs --domain mawena.cloud --sub ccs --proxy 8420` (proxy avec
   WebSocket), puis `sudo lnmp add-ssl ccs` (Let's Encrypt).
3. `ccs doctor` sur le VPS vérifie : services actifs, port, réponse de
   `https://ccs.mawena.cloud/api/health`, certificat, groupe `ccs` non vide, Claude Code.

## Approches considérées

- **A, retenue** : tout dans CCS, sur le modèle de Cockpit (service privilégié minuscule,
  serveur web sans droits, processus par utilisateur). Seule à donner une version web
  identique au bureau et utilisable au téléphone, et une même API pour le web, le terminal
  et le bureau.
- **B, écartée** : extension de Cockpit. Moins de code de sécurité, mais interface enfermée
  dans Cockpit (pas « comme le bureau », peu pratique au téléphone), double authentification
  par un module PAM de plus, bureau et terminal obligés de parler le protocole de Cockpit.
- **Écartée** : la version terminal affichée dans le navigateur, loin du bureau et pénible
  au doigt.

## Choix faits par Claude (à vérifier par Charles)

- Trois paquets (`ccs`, `ccs-bureau`, `ccs-serveur`) ; installation du VPS par
  `apt install --no-install-recommends ccs-serveur`.
- Groupe Unix `ccs` obligatoire ; `root` toujours refusé.
- Sessions : 12 h sans activité, 7 jours au plus ; appareil retenu 30 jours pour le code
  seulement ; 5 échecs en 15 min → 15 min de refus.
- Port 8420 ; serveur web sous un utilisateur système `ccs-web`.
- Markdown rendu côté serveur ; xterm.js embarqué ; aucun outil de construction pour le web.
- Comptes Claude ajoutés sur le VPS par un onglet shell (`ccs add`).
- Pont arrêté après 12 h sans client et sans chat en cours.
- Sur le VPS, le pont fait tourner la boucle du service `ccs-daemon` si celui-ci n'est pas
  actif.

## Laissé au constructeur

Découpage exact des méthodes JSON-RPC, format des messages du WebSocket, dessin des écrans
web dans l'esprit du design 0.10, organisation des modules JS, raccourcis clavier de
`ccs tui`, texte des pages d'aide.
