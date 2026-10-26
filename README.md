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

## Dans Claude Code

`ccs integrate on` ajoute deux choses à Claude Code (dans `~/.claude/settings.json`,
avec une sauvegarde ; une ligne d'état que tu aurais déjà n'est jamais remplacée) :

- **une ligne d'état** en bas de chaque session :
  `◑ perso 53 % ↻17:20 · ⏱14:21 · sem. 51 % · 2 comptes` — compte actif,
  session, recharge, limite estimée, semaine, et le meilleur compte quand il
  faut changer ;
- **la bascule après blocage** : si une session atteint malgré tout la limite,
  CCS bascule aussitôt sur le meilleur autre compte et te prévient — tape
  « continue » et la session repart.

`ccs integrate off` retire tout ce que CCS a ajouté, et seulement cela.

## Sessions Claude sur le PC

L'onglet **Sessions** (et `ccs sessions`, et le sous-menu de l'icône) liste les
sessions Claude Code ouvertes — terminal ou VS Code : projet, état (*travaille*,
*attend ta réponse*, *au repos*), depuis quand, modèle et consommation de la
conversation. Tu peux ouvrir un terminal ou le dossier du projet, terminer une
session oubliée, reprendre une conversation récente ou en démarrer une nouvelle
dans un projet. Une notification te prévient quand une session **a terminé** ou
**attend ta réponse** — pratique quand plusieurs tournent en parallèle.

## Fonctionnalités

| | |
|---|---|
| **Profils** | Un profil par compte claude.ai. Bascule instantanée ; réglages, historique, plugins et serveurs MCP restent communs. |
| **Usage de tous les comptes** | Session de 5 h et limites hebdomadaires de chaque compte, sans basculer. |
| **Prévisions** | Fin de session estimée au rythme actuel, marge sur le rythme de la semaine, budget par jour, capacité restante tous comptes confondus. |
| **Meilleur compte** | Recommandation expliquée : d'abord le quota qui expire le plus tôt, les comptes en réserve en dernier. |
| **Bascule automatique** | À 98 % (réglable) ou si le prochain relevé dépasserait 100 %, vers un compte sous 80 % aux données fraîches. Pas de va-et-vient, bascule manuelle récente respectée. |
| **Orchestrateur** | Enchaînement et décalage des fenêtres, quota qui expire d'abord, réserve hebdomadaire (voir plus haut). |
| **Alertes** | 80 % et 95 % (avec un bouton « Basculer sur … »), fin de session imminente, bascule effectuée, tous comptes épuisés, compte réinitialisé, semaine en avance, connexion expirée, session terminée ou en attente. Une fois par seuil et par fenêtre. |
| **Intégration Claude Code** | Ligne d'état dans chaque session, bascule automatique quand une session est bloquée. |
| **Sessions** | Sessions ouvertes, consommation, reprise de conversations, terminal / dossier du projet. |
| **Analyse** | Où part l'usage : par projet, modèle, heure et compte, avec des conseils concrets. |
| **Application** | « Comptes Claude » (GTK 4) : Comptes, Planning, Sessions, Historique, Analyse, Réglages. |
| **Icône dans la barre du haut** | Jauge du compte actif (vert / orange / rouge) ; au clic : comptes, recharges, prévision, sessions, interrupteurs. |
| **Service** | Unité systemd utilisateur : relevé toutes les 5 min, toutes les minutes près des limites ; avec l'orchestrateur, réveil précis aux fins de fenêtre. |

## Installation

Ubuntu 24.04 (ou Debian/Ubuntu récent avec GTK 4 et libadwaita ≥ 1.4).
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

**Mise à jour** : installe le nouveau `.deb`. À partir de 0.2.1, le service
se relance seul avec la nouvelle version (dans les 5 min) ; depuis une version
plus ancienne, lance une fois `systemctl --user restart ccs-daemon`. Tes
profils sont conservés.

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
| `ccs status` | Compte actif, prévision, meilleur compte, capacité, orchestrateur, service |
| `ccs plan` | Planning des fenêtres et recharges à venir |
| `ccs sessions` | Sessions Claude Code ouvertes : projet, état, consommation |
| `ccs integrate on\|off\|status` | Ligne d'état et bascule après blocage dans Claude Code |
| `ccs usage` | Usage détaillé de tous les comptes, prévisions, rythme hebdo |
| `ccs orch on\|off` | Orchestrateur |
| `ccs auto on\|off` | Bascule automatique à 98 % |
| `ccs analyze [--days N]` | Consommation par projet, modèle, heure, compte + conseils |
| `ccs save <nom>` / `ccs add <nom>` | Enregistre le compte connecté / connecte un nouveau compte |
| `ccs rename <a> <b>` / `ccs rm <nom>` | Renomme / supprime un profil |
| `ccs gui` | Application graphique |

Détails : `man ccs`, `man claude-accounts`, [docs/utilisation.md](docs/utilisation.md).

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
600). CCS ne contacte que les serveurs d'Anthropic. Aucun jeton n'apparaît dans
les journaux, l'état partagé ou les notifications.

## Dépannage

| Symptôme | Solution |
|---|---|
| « le compte connecté n'est enregistré dans aucun profil » | `ccs save <nom>` avant de basculer. |
| « connexion expirée ou révoquée » | `ccs rm <nom>` puis `ccs add <nom>`. |
| Pas de bascule / pas de démarrage | `ccs status` : service en marche ? orchestrateur activé ? dans la plage horaire ? |
| L'ancienne version s'ouvre | Supprime `~/.local/bin/ccs`, `~/.local/bin/claude-accounts` et `~/.local/share/applications/io.ccs.ClaudeAccounts.desktop`. |
| « Comptes Claude » introuvable dans le menu | Alt+F2 puis `r` (X11), ou reconnecte-toi. |
| Icône absente de la barre du haut | Extension « Ubuntu AppIndicators » (voir Installation), puis `claude-accounts tray &`. |
| Pas de ligne d'état dans Claude Code | `ccs integrate status`, puis relance la session. |

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

```sh
make test     # tests unitaires + scénario de bout en bout de ccs
make deb      # tests, paquet, SHA256SUMS et lintian dans dist/
```

## Licence

[MIT](LICENSE) © 2026 mawena
