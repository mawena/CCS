# CCS — plusieurs comptes Claude Code, comme un seul

**Pro (20 $) ne te suffit plus, mais Max (100 $) c'est trop ?** CCS fait
travailler 2 ou 3 comptes Claude Code ensemble sur ton PC Linux : une seule
commande pour basculer, l'usage de tous les comptes d'un coup d'œil, une bascule
automatique avant la coupure — les sessions déjà ouvertes continuent sur le
compte suivant — et un **orchestrateur** qui organise les fenêtres de 5 h pour
qu'un compte soit disponible quand l'autre est épuisé.

```sh
ccs save perso        # enregistre le compte connecté
ccs add boulot        # connecte et enregistre un deuxième compte
ccs orch on           # l'orchestrateur gère le reste
ccs integrate on      # l'état des comptes en bas de chaque session Claude Code
ccs status            # où j'en suis, quel compte utiliser
```

## Le palier qui manque

| Formule | Prix / mois* | Capacité (Pro = 1×) |
|---|---|---|
| 1 compte Pro | 20 $ | 1× |
| **2 comptes Pro + CCS** | **40 $** | **≈ 2×** |
| **3 comptes Pro + CCS** | **60 $** | **≈ 3×** |
| Max 5× | 100 $ | 5× |
| Max 20× | 200 $ | 20× |

\* Tarifs indicatifs, à vérifier sur la page de prix d'Anthropic.

Soyons clairs : à capacité égale, Max n'est pas plus cher que plusieurs comptes
Pro. CCS sert quand ton besoin se situe **entre** les formules — deux ou trois
fois Pro — ou quand tu as déjà plusieurs comptes (perso et travail, par
exemple). Ce que CCS apporte, c'est que ces comptes se comportent comme un seul :

- tu ne te reconnectes jamais, tu ne surveilles rien ;
- la bascule se fait **avant** la coupure, sans interrompre les sessions ouvertes ;
- l'orchestrateur évite les temps morts : avec 2 comptes décalés, une recharge
  arrive toutes les 2 h 30 au lieu de toutes les 5 h ;
- le quota qui va expirer est utilisé en premier, pour en perdre le moins possible.

> **À lire avant de multiplier les comptes.** Les conditions d'utilisation
> d'Anthropic peuvent encadrer l'usage de plusieurs comptes par une même
> personne : vérifie qu'elles autorisent ton usage. CCS ne relève aucune
> limite : chaque compte garde ses propres limites, CCS aide seulement à bien
> les utiliser. CCS n'est pas un produit Anthropic ; il s'appuie sur les
> fichiers et l'API d'usage de Claude Code, qui peuvent évoluer.

## L'orchestrateur

Pendant ta plage horaire (par défaut 8 h → 2 h), il applique quatre règles :

1. **Enchaîner** — chaque compte a toujours une fenêtre de 5 h ouverte : dès
   qu'une fenêtre se termine, une requête minimale (Haiku) démarre la suivante.
2. **Décaler** — les fenêtres des comptes sont espacées de 5 h ÷ nombre de
   comptes : un compte au repos attend que l'écart avec la dernière fenêtre
   démarrée soit atteint (il reste utilisable à tout moment entre-temps) :

   ```
   perso   08:00 ━━━━━━━━━ 13:00 ━━━━━━━━━ 18:00 ━━━━━━━━━ 23:00 ━━━
   boulot        10:30 ━━━━━━━━━ 15:30 ━━━━━━━━━ 20:30 ━━━━━━━━━ 01:30
   recharges           13:00     15:30     18:00     20:30     23:00
   ```

3. **Quota qui expire d'abord** — si un compte va perdre plus de 30 % de son
   quota dans moins d'une heure, CCS bascule dessus avant (au plus toutes les
   30 min).
4. **Répartir la semaine** — un compte en avance sur son rythme hebdomadaire
   passe en réserve : les bascules le choisissent en dernier. Un compte à 95 %
   de sa semaine n'est plus démarré.

Le service se réveille pile à chaque fin de fenêtre. Hors plage horaire, rien
n'est démarré et aucune bascule anticipée n'a lieu ; la bascule anticipée
respecte aussi l'interrupteur « bascule automatique ». Tout se règle dans l'onglet **Réglages**, et l'onglet
**Planning** montre la frise du jour et les recharges à venir.

## Mettre en pause

Besoin de rester sur un compte précis le temps d'une démo ou d'un gros
travail ? `ccs pause 1h` (ou `4h`, `demain` = jusqu'au début de la prochaine
plage horaire, `manuel` = jusqu'à ce que tu reprennes) suspend la bascule
automatique et l'orchestrateur. Pendant une pause, **CCS ne change plus de
compte tout seul**, même quand une session est bloquée par la limite ; les
bascules que tu fais toi-même, les alertes et les warm-up continuent. La pause
se lève seule à l'échéance (notification « Pause terminée ») ; `ccs pause off`
reprend tout de suite.

Aussi dans le menu de l'icône (« Mettre en pause ») et sur la carte **Meilleur
compte** de l'onglet Comptes ; l'en-tête de la fenêtre, l'onglet Planning,
`ccs status`, l'icône et la ligne d'état de Claude Code affichent ⏸.

## Dans Claude Code

`ccs integrate on` ajoute deux choses à Claude Code (dans `~/.claude/settings.json`,
avec une sauvegarde ; une ligne d'état que tu aurais déjà n'est jamais remplacée) :

- **une ligne d'état** en bas de chaque session :
  `◑ perso 53 % ↻17:20 · ⏱14:21 · sem. 51 % · 2 comptes` — compte actif,
  session, recharge, limite estimée, semaine, et le meilleur compte quand il
  faut changer ;
- **la bascule après blocage** : si une session atteint malgré tout la limite,
  CCS bascule aussitôt sur le meilleur autre compte et te prévient — tape
  « continue » et la session repart (dans le terminal intégré, CCS peut
  l'envoyer pour toi). En pause, la notification le dit et rien ne bascule.

`ccs integrate off` retire tout ce que CCS a ajouté, et seulement cela.

## Sessions Claude sur le PC

L'onglet **Sessions** (et `ccs sessions`, et le sous-menu de l'icône) liste les
sessions Claude Code ouvertes — terminal ou VS Code : projet, état (*travaille*,
*attend ta réponse*, *au repos*), depuis quand, modèle et consommation de la
conversation. Tu peux ouvrir un terminal ou le dossier du projet, terminer une
session oubliée, reprendre une conversation récente ou en démarrer une nouvelle
dans un projet. Une notification te prévient quand une session **a terminé** ou
**attend ta réponse** — pratique quand plusieurs tournent en parallèle ; un clic
dessus ouvre l'onglet de la session, et un rappel unique part si ta réponse se
fait attendre plus de 10 min. Le badge de l'onglet Sessions compte les sessions
qui t'attendent.

**Nouvelle session…** ouvre un dialogue : dossier, compte, modèle (`--model`)
et mode de permissions (`--permission-mode`). Si tu choisis un autre compte que
le compte actif, CCS bascule avant de lancer la session — et toutes les
sessions ouvertes suivent, le dialogue te le rappelle. Le mode « Aucune
vérification » (`bypassPermissions`) reste proposé, avec un avertissement en
rouge.

## Terminal intégré

Reprendre une conversation ou démarrer une session l'ouvre **dans la fenêtre de
l'application**, dans un onglet de terminal, plutôt que dans une fenêtre à part.
Plusieurs sessions tiennent en onglets (page **Terminaux**, visible dès qu'un
onglet est ouvert) ; chaque onglet porte le titre de la conversation
et montre si Claude **travaille**, **attend ta réponse** ou s'est arrêté.

- **Ctrl+Maj+C / Ctrl+Maj+V** pour copier et coller (ou clic droit),
  **Ctrl+clic** sur un lien (adresse de connexion de Claude, par exemple),
  Ctrl+plus / Ctrl+moins pour la taille du texte ; police à chasse fixe du
  bureau, couleurs qui suivent le thème clair ou sombre.
- Quand Claude s'arrête, un bandeau propose **Reprendre** (la même
  conversation) ou **Fermer**. Fermer un onglet ou la fenêtre pendant qu'une
  session tourne demande confirmation : la conversation est enregistrée, tu
  pourras la reprendre.
- Une session déjà ouverte dans l'application se retrouve par **Afficher**
  depuis les onglets Sessions et Conversations. Le terminal externe reste
  disponible dans les menus « ⋮ », et « Terminal ici » ouvre un shell dans un
  onglet.
- **Reprise automatique après une limite** (avec `ccs integrate on`) : quand
  une session d'un onglet est bloquée, CCS bascule sur un autre compte puis
  tape « continue » à ta place, une seule fois, dès que Claude attend une
  nouvelle demande — jamais si tu as écrit dans l'onglet entre-temps, ni
  pendant une pause. Interrupteur dans le menu « ⋮ » de la page Terminaux.
- **Côte à côte** (Ctrl+Maj+E) : deux sessions dans la même vue, séparation
  réglable.
- **Messages en attente** (Ctrl+Maj+M) : prépare la suite pendant que Claude
  travaille ; chaque message part quand il a fini son tour, un par tour.
- **Onglets rouverts** : au redémarrage de l'application, un bandeau propose de
  rouvrir les sessions de la dernière fois (conversations reprises avec leurs
  options et leurs messages en attente), ou c'est automatique si tu l'as
  choisi dans le menu « ⋮ ».

Le terminal intégré utilise VTE (`gir1.2-vte-3.91`, dépendance du paquet). S'il
manque, tout s'ouvre dans un terminal externe comme avant et l'onglet Sessions
indique la commande à lancer : `sudo apt install gir1.2-vte-3.91`.

## Renommer une conversation

« Renommer… » (onglets Sessions et Conversations, menu d'un onglet du terminal)
ou `ccs title <identifiant> <titre>` donne un titre à une conversation, comme
`/rename` dans Claude Code : le titre est enregistré dans la conversation et
s'affiche partout, VS Code compris.

## Historique des conversations

L'onglet **Conversations** (et `ccs conv`) liste **toutes** les conversations
Claude Code du PC, comme la liste des conversations passées de l'extension
VS Code, mais tous projets confondus : titre (celui que tu as donné, sinon le
titre automatique de Claude Code, sinon ta première demande), projet, origine
(VS Code ou terminal), branche, nombre de demandes, date. Recherche sans
accents ni majuscules, filtres par projet et par origine, groupes *Aujourd'hui*,
*Hier*, *7 derniers jours*…

Un clic reprend la conversation **dans VS Code** (la fenêtre du projet s'ouvre et
l'extension Claude Code y rouvre la conversation) ou **dans l'application**
(`claude --resume` dans un onglet du terminal intégré ; un terminal externe reste
au menu « … »). Une conversation déjà ouverte ailleurs n'est pas relancée
une seconde fois. Si le projet a été **déplacé**, CCS propose le dossier du même
nom qu'il retrouve et, après confirmation, y copie le journal de la conversation
pour qu'elle reprenne depuis là (l'original reste en place).

**Aperçu…** (menu d'une conversation, onglets Conversations et Sessions) relit
une conversation sans la reprendre : tes demandes, les réponses de Claude, les
outils utilisés en une ligne. Tu peux la copier ou l'**exporter en Markdown**.
Chaque conversation affiche aussi son **coût** : tokens consommés (sous-agents
compris) et ce qu'elle aurait coûté au tarif de l'API. Ton abonnement ne
facture pas au token : ce montant sert seulement à comparer les conversations.

```bash
ccs conv                 # les 30 dernières conversations, groupées par date
ccs conv export csv      # recherche
ccs conv -p Portail      # un projet
ccs resume 4f3a          # reprend ici (4 premiers caractères de l'identifiant)
ccs resume 4f3a --vscode # ou dans VS Code
ccs title 4f3a Export CSV des prêts   # renomme la conversation
ccs preview 4f3a | less  # relit la conversation (Markdown, coût en en-tête)
ccs export 4f3a prets.md # l'enregistre en Markdown
```

## Bilan de santé

Quelque chose ne marche pas ? `ccs doctor` (ou « Bilan de santé… » dans le menu
de l'application) vérifie le service et ses relevés, la version installée et
celle qui tourne, l'extension et l'icône de la barre du haut, l'intégration
dans Claude Code, la connexion de chaque compte, `claude`, `jq` et le terminal
intégré. Pour chaque problème, il donne **la commande à copier** ; il ne
l'exécute jamais à ta place. Code de sortie : 0 si tout va bien, 1 sinon.
L'application affiche un bandeau quand un problème est détecté au démarrage.

## Fonctionnalités

| | |
|---|---|
| **Profils** | Un profil par compte claude.ai. Bascule instantanée ; réglages, historique, plugins et serveurs MCP restent communs. |
| **Usage de tous les comptes** | Session de 5 h et limites hebdomadaires de chaque compte, sans basculer. |
| **Prévisions** | Fin de session estimée au rythme actuel, fin de semaine prévue au rythme moyen de la semaine, marge sur le rythme de la semaine, budget par jour, capacité restante tous comptes confondus. |
| **Meilleur compte** | Recommandation expliquée : d'abord le quota qui expire le plus tôt, les comptes en réserve en dernier. |
| **Bascule automatique** | À 98 % (réglable) ou si le prochain relevé dépasserait 100 %, vers un compte sous 80 % aux données fraîches. Pas de va-et-vient, bascule manuelle récente respectée. |
| **Orchestrateur** | Enchaînement et décalage des fenêtres, quota qui expire d'abord, réserve hebdomadaire (voir plus haut). |
| **Pause** | Bascule automatique et orchestrateur suspendus 1 h, 4 h, jusqu'à la prochaine plage horaire ou jusqu'à reprise ; levée automatique. |
| **Alertes** | 80 % et 95 % (avec un bouton « Basculer sur … »), fin de session imminente, semaine épuisée dans 2 jours ou moins, bascule effectuée, tous comptes épuisés, compte réinitialisé, connexion expirée, session terminée ou en attente (avec un rappel après 10 min), pause terminée, nouvelle version. Une fois par seuil et par fenêtre. |
| **Intégration Claude Code** | Ligne d'état dans chaque session, bascule automatique quand une session est bloquée. |
| **Sessions** | Sessions ouvertes, consommation, reprise de conversations, nouvelle session (dossier, compte, modèle, permissions), terminal / dossier du projet. |
| **Terminal intégré** | Sessions Claude Code dans des onglets de l'application : activité, reprise après arrêt ou après une limite, deux sessions côte à côte, messages en attente, onglets rouverts au redémarrage, copier/coller, liens, confirmation avant fermeture. |
| **Conversations** | Historique de toutes les conversations du PC, recherche, aperçu, export Markdown, coût, reprise dans l'application, VS Code ou un terminal externe, renommage, projets déplacés. |
| **Analyse** | Où part l'usage : par projet, modèle, heure et compte, avec des conseils concrets. |
| **Bilan de santé** | `ccs doctor` : service, versions, barre du haut, intégration, comptes, Claude Code, terminal ; une commande à copier par problème. |
| **Application** | « Comptes Claude » (GTK 4) : Comptes, Planning, Sessions, Conversations, Terminaux, Historique, Analyse, Réglages. |
| **Icône dans la barre du haut** | Jauge du compte actif (vert / orange / rouge, ⏸ en pause) ; au clic : comptes, recharges, prévisions, sessions, interrupteurs, pause, nouvelle version. |
| **Service** | Unité systemd utilisateur : relevé toutes les 5 min, toutes les minutes près des limites ; avec l'orchestrateur, réveil précis aux fins de fenêtre ; nouvelle version cherchée une fois par jour. |

## Installation

Ubuntu 24.04 (ou Debian/Ubuntu récent avec GTK 4, libadwaita ≥ 1.5 et, pour le
terminal intégré, VTE pour GTK 4 : `gir1.2-vte-3.91`).
Claude Code doit être installé
(`claude` dans le `PATH`).

```sh
gh release download -R mawena/CCS -p '*.deb'      # ou depuis la page Releases
sudo apt install ./ccs_*_all.deb
systemctl --user daemon-reload
systemctl --user enable --now ccs-daemon
```

Le service démarre ensuite seul à chaque session, l'icône de la barre du haut
aussi (première fois sans te reconnecter : `claude-accounts tray &`).
Optionnel : `ccs integrate on` pour la ligne d'état et la bascule après blocage
dans Claude Code.

**Indicateur invisible ?** Active l'extension GNOME « Ubuntu AppIndicators » :
`gnome-extensions enable ubuntu-appindicators@ubuntu.com` (ou bouton dans
Réglages).

**Mise à jour** : CCS te prévient quand une nouvelle version est publiée
(notification, icône, Réglages ; vérification sur GitHub au plus une fois par
jour). Installe le nouveau `.deb` : le service se relance seul avec la nouvelle
version (dans les 5 min), l'icône aussi (dans les 10 s). En venant de la 0.4.0
ou d'avant, l'icône ne sait pas encore le faire : relance-la une fois
(`pkill -f 'claude-accounts tray'; setsid -f claude-accounts tray`) ; en venant
d'une version antérieure à 0.2.1, lance aussi une fois
`systemctl --user restart ccs-daemon`. Tes profils sont conservés.

### Depuis les sources

```sh
git clone https://github.com/mawena/CCS.git && cd CCS
make test                 # tests unitaires + bout en bout
bin/ccs                   # utilisable directement depuis le dépôt
make deb                  # construit dist/ccs_<version>_all.deb
```

## Démarrage rapide

1. **Enregistre le compte déjà connecté** : `ccs save perso`
2. **Ajoute les autres** : `ccs add boulot` ouvre la connexion dans le
   navigateur ; choisis bien un *autre* compte (`--email` pré-remplit).
3. **Démarre le service** : `systemctl --user enable --now ccs-daemon`
4. **Active l'orchestrateur** : `ccs orch on`, puis règle ta plage horaire dans
   l'application (« Comptes Claude » dans le menu, ou `ccs gui`).

## Commandes

| Commande | Effet |
|---|---|
| `ccs` | Liste les profils (● = actif) |
| `ccs <nom>` | Bascule sur un profil |
| `ccs next` / `ccs best` | Profil suivant / meilleur compte du moment |
| `ccs status` | Compte actif, prévision, meilleur compte, capacité, orchestrateur, pause, service |
| `ccs plan` | Planning des fenêtres et recharges à venir |
| `ccs sessions` | Sessions Claude Code ouvertes : projet, état, consommation |
| `ccs conv [mots]` | Historique des conversations du PC, recherche, `-p <projet>`, `--vscode`/`--terminal` |
| `ccs resume <id>` | Reprend une conversation ici, `--vscode`, `--new-terminal`, `--dir <dossier>` |
| `ccs title <id> <titre>` | Renomme une conversation (comme `/rename`) |
| `ccs preview <id>` | Affiche la conversation en Markdown, coût en en-tête (alias `ccs apercu`) |
| `ccs export <id> [fichier.md]` | Enregistre la conversation en Markdown |
| `ccs integrate on\|off\|status` | Ligne d'état et bascule après blocage dans Claude Code |
| `ccs usage` | Usage détaillé de tous les comptes, prévisions, rythme hebdo |
| `ccs orch on\|off` | Orchestrateur |
| `ccs auto on\|off` | Bascule automatique à 98 % |
| `ccs pause [1h\|4h\|demain\|manuel\|off\|status]` | Met en pause la bascule automatique et l'orchestrateur (`status` par défaut) |
| `ccs doctor` | Bilan de santé, avec la commande qui corrige chaque problème |
| `ccs analyze [--days N]` | Consommation par projet, modèle, heure, compte + conseils |
| `ccs save <nom>` / `ccs add <nom>` | Enregistre le compte connecté / connecte un nouveau compte |
| `ccs rename <a> <b>` / `ccs rm <nom>` | Renomme / supprime un profil |
| `ccs gui` | Application graphique |

Détails : `man ccs`, `man claude-accounts`, [docs/utilisation.md](docs/utilisation.md).

## Configuration

Tout se règle dans l'onglet **Réglages** de l'application (ou les commandes
`ccs auto`, `ccs orch`, `ccs pause`, `ccs integrate`). Les réglages vivent dans
`~/.claude-accounts/settings.json`, fusionnés avec les valeurs par défaut :
bascule automatique (`auto_switch`), alertes (`alerts` : seuils, fin de semaine
prévue `weekly_forecast` / `weekly_forecast_days`, rappel d'attente
`waiting_reminder` / `waiting_reminder_min`…), orchestrateur et plage horaire
(`orchestrator`), warm-up (`warmup`), nouvelles versions (`updates.enabled`).
`CCS_HOME` change le dossier des profils (défaut `~/.claude-accounts`).

## Comment ça marche

**Bascule.** Chaque profil conserve le jeton OAuth et l'identité du compte dans
`~/.claude-accounts/<nom>/`. Basculer réécrit, de façon atomique et sous verrou,
la partie « compte » de `~/.claude/.credentials.json` et `~/.claude.json` ; le
reste (jetons MCP, réglages) est conservé.

**Sessions ouvertes.** Avant chaque requête, Claude Code vérifie si son fichier
de connexion a changé et le relit : une session en cours passe sur le nouveau
compte à son message suivant. La première requête après une bascule renvoie le
contexte au nouveau compte (cache non partagé) : un coût ponctuel.

**Usage sans se reconnecter.** Le service interroge l'API d'usage avec le jeton
de chaque profil et renouvelle lui-même les jetons des comptes inactifs ; celui
du compte actif est laissé à Claude Code tant qu'il tourne.

**Démarrer une fenêtre.** Une requête `claude -p` minimale sur Haiku, dans un
dossier de configuration temporaire qui ne contient que le compte visé : le
compte actif et tes sessions ne sont pas touchés.

Architecture : [docs/architecture.md](docs/architecture.md).

## Données et confidentialité

Tout reste sur la machine, dans `~/.claude-accounts/` (dossier 700, fichiers
600). CCS contacte les serveurs d'Anthropic et, au plus une fois par jour, l'API
publique de GitHub pour savoir si une nouvelle version de CCS est sortie (sans
authentification ; à couper dans **Réglages → Nouvelles versions**).
Il lit les conversations de
`~/.claude/projects` sans les modifier, à deux exceptions près : la reprise d'un
projet déplacé y ajoute une copie du journal, et renommer une conversation ajoute
une ligne de titre à la fin de son journal (comme `/rename`). L'aperçu, l'export
et le coût ne font que lire. Aucun jeton n'apparaît dans
les journaux, l'état partagé, les notifications ou le bilan de santé (qui n'en
retient que la présence et les dates d'expiration).

## Dépannage

Premier réflexe : `ccs doctor`, qui donne la commande à lancer pour chaque
problème trouvé.

| Symptôme | Solution |
|---|---|
| « le compte connecté n'est enregistré dans aucun profil » | `ccs save <nom>` avant de basculer. |
| « connexion expirée ou révoquée » | `ccs rm <nom>` puis `ccs add <nom>`. |
| Pas de bascule / pas de démarrage | `ccs status` : service en marche ? orchestrateur activé ? dans la plage horaire ? en pause (`ccs pause off`) ? |
| L'icône garde l'ancienne version après une mise à jour | Mise à jour en venant de la 0.4.0 ou d'avant : `pkill -f 'claude-accounts tray'; setsid -f claude-accounts tray`. |
| L'ancienne version s'ouvre | Supprime `~/.local/bin/ccs`, `~/.local/bin/claude-accounts` et `~/.local/share/applications/io.ccs.ClaudeAccounts.desktop`. |
| « Comptes Claude » introuvable dans le menu | Alt+F2 puis `r` (X11), ou reconnecte-toi. |
| Icône absente de la barre du haut | Extension « Ubuntu AppIndicators » (voir Installation), puis `claude-accounts tray &`. |
| Pas de ligne d'état dans Claude Code | `ccs integrate status`, puis relance la session. |
| Les sessions s'ouvrent dans un terminal externe | Terminal intégré indisponible : `sudo apt install gir1.2-vte-3.91`, puis rouvre l'application. |
| Une session bloquée n'est pas relancée dans l'onglet | `ccs integrate on` (le hook est nécessaire), interrupteur « Reprise automatique après une limite » du menu « ⋮ » de la page Terminaux, pas de pause en cours ; une touche tapée dans l'onglet après la limite annule la reprise. |

Journaux du service : `journalctl --user -u ccs-daemon -f`.

## Désinstallation

```sh
systemctl --user disable --now ccs-daemon
sudo apt remove ccs
rm -rf ~/.claude-accounts      # optionnel : profils et historique
```

## Développement

Projet en **git flow** (`main` / `develop`, tags `vX.Y.Z`), commits
conventionnels en français. Python 3 (bibliothèque standard + PyGObject) et
bash ; pas d'autre dépendance.

```
bin/ccs              commande ccs (bash) : profils et bascule
bin/claude-accounts  lanceur Python de ccs_app
ccs_app/             service, prévisions, alertes, pause, conversations, bilan…
ccs_app/gui/         application GTK 4 / libadwaita et ses dialogues
data/  debian/       unité systemd, entrées de menu, icône, paquet
scripts/             construction du .deb
docs/                guide, architecture, pages man
tests/               tests unitaires et scénario de bout en bout
```

```sh
make test     # tests unitaires + scénario de bout en bout de ccs
make deb      # tests, paquet, SHA256SUMS et lintian dans dist/
```

Essayer une copie de développement sans réveiller l'application installée :
`CCS_APP_ID=io.ccs.ClaudeAccounts.Dev bin/claude-accounts gui` ;
`CCS_NO_VTE=1` force le repli sur le terminal externe.

## Licence

[MIT](LICENSE) © 2026 mawena
