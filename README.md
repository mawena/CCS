# CCS — plusieurs comptes Claude Code, zéro coupure

CCS garde plusieurs comptes **Claude Code** connectés sur le même PC Linux et
bascule de l'un à l'autre avec une seule commande, sans se déconnecter ni se
reconnecter. Il surveille l'usage de chaque compte, prévoit quand une session va
s'épuiser et **bascule tout seul avant la coupure** : les sessions Claude Code
déjà ouvertes passent sur le nouveau compte dès leur prochaine requête.

```sh
ccs save perso        # enregistre le compte connecté
ccs add pro           # connecte et enregistre un deuxième compte
ccs pro               # bascule
ccs status            # où j'en suis, quel compte utiliser
```

> CCS n'est pas un produit Anthropic. Il s'appuie sur les fichiers de connexion
> de Claude Code et sur l'API d'usage qu'utilise Claude Code lui-même ; une
> évolution de Claude Code peut demander une mise à jour de CCS.

## Fonctionnalités

| | |
|---|---|
| **Profils** | Un profil par compte claude.ai (Pro, Max, Team…). Bascule instantanée ; réglages, historique, plugins et serveurs MCP restent communs. |
| **Usage de tous les comptes** | Session de 5 h et limites hebdomadaires de chaque compte, sans basculer. |
| **Prévisions** | Heure estimée de fin de session au rythme actuel, marge sur le rythme de la semaine, budget par jour, capacité restante tous comptes confondus. |
| **Meilleur compte** | Recommandation expliquée : d'abord un compte dont la fenêtre est déjà ouverte (sa marge sera perdue au reset), sinon le compte au repos le moins entamé sur la semaine. |
| **Bascule automatique** | À 98 % (réglable) ou si le prochain relevé dépasserait 100 %, vers un compte sous 80 %. Garde-fous : pas de va-et-vient, respect d'une bascule manuelle récente, jamais vers un compte épuisé. |
| **Alertes** | Notifications à 80 % et 95 %, fin de session imminente, bascule effectuée, tous comptes épuisés, compte réinitialisé, semaine en avance sur le rythme, connexion expirée. Une seule fois par seuil et par fenêtre. |
| **Warm-up** | Une requête minimale (Haiku) à l'heure choisie pour démarrer la fenêtre de 5 h plus tôt et qu'elle se réinitialise en pleine journée. |
| **Analyse** | Où part l'usage : par projet, modèle, heure et compte, d'après les journaux locaux de Claude Code, avec des conseils concrets. |
| **Application** | « Comptes Claude » (GTK 4) : onglets Comptes, Historique (courbes 24 h / 7 j), Analyse, Réglages. |
| **Indicateur** | Pourcentage du compte actif dans la barre du haut, bascule en un clic. |
| **Service** | Unité systemd utilisateur : relevé toutes les 5 min, toutes les minutes près des limites. |

## Installation

Ubuntu 24.04 (ou Debian/Ubuntu récent avec GTK 4 et libadwaita ≥ 1.4).
Claude Code doit être installé (`claude` dans le `PATH`).

```sh
sudo apt install ./ccs_0.1.0_all.deb
systemctl --user daemon-reload
systemctl --user enable --now ccs-daemon      # service de collecte
```

Le service est activé pour toutes les sessions et démarre seul aux connexions
suivantes. L'indicateur démarre avec la session graphique.

**Indicateur invisible ?** Sur Ubuntu, il faut l'extension GNOME
« Ubuntu AppIndicators » :

```sh
gnome-extensions enable ubuntu-appindicators@ubuntu.com
```

(également activable depuis l'onglet Réglages de l'application).

### Depuis les sources

```sh
git clone <dépôt> ccs && cd ccs
make test                 # tests unitaires + bout en bout
bin/ccs                   # utilisable directement depuis le dépôt
make deb                  # construit dist/ccs_<version>_all.deb
```

## Démarrage rapide

1. **Enregistrer le compte déjà connecté** : `ccs save perso`
2. **Ajouter les autres** : `ccs add pro` ouvre la connexion dans le navigateur ;
   choisis bien un *autre* compte. (`--email adresse` pré-remplit le formulaire.)
3. **Lancer le service** : `systemctl --user enable --now ccs-daemon`
4. **Ouvrir l'application** : « Comptes Claude » dans le menu, ou `ccs gui`.

À partir de là, CCS bascule tout seul avant la limite et te prévient.

## Commandes

| Commande | Effet |
|---|---|
| `ccs` | Liste les profils (● = actif) |
| `ccs <nom>` | Bascule sur un profil |
| `ccs next` | Profil suivant |
| `ccs best` | Bascule sur le meilleur compte du moment |
| `ccs status` | Compte actif, prévision, meilleur compte, capacité, état du service |
| `ccs usage` | Usage détaillé de tous les comptes, prévisions et rythme hebdo |
| `ccs auto on\|off` | Bascule automatique |
| `ccs analyze [--days N]` | Consommation par projet, modèle, heure, compte + conseils |
| `ccs save <nom>` | Enregistre le compte connecté |
| `ccs add <nom> [--email e] [--console] [--sso]` | Connecte et enregistre un nouveau compte |
| `ccs rename <a> <b>` / `ccs rm <nom>` | Renomme / supprime un profil |
| `ccs current` | Nom du profil actif |
| `ccs gui` | Application graphique |

`claude-accounts` expose les mêmes fonctions (`print`, `status`, `best`,
`auto`, `collect`, `analyze`, `daemon`, `tray`, `gui`). Voir `man ccs` et
`man claude-accounts`.

## Comment ça marche

**Bascule.** Chaque profil conserve le jeton OAuth et l'identité du compte dans
`~/.claude-accounts/<nom>/`. Basculer réécrit, de façon atomique, la partie
« compte » de `~/.claude/.credentials.json` et `~/.claude.json` ; le reste
(jetons MCP, réglages) est conservé. Avant chaque bascule, le jeton du compte
quitté — que Claude Code renouvelle régulièrement — est resauvegardé dans son
profil.

**Sessions ouvertes.** Avant chaque requête, Claude Code vérifie si son fichier
de connexion a changé et le relit. Une session en cours passe donc sur le nouveau
compte à son message suivant, sans redémarrage. La première requête après une
bascule renvoie le contexte de la conversation au nouveau compte (le cache n'est
pas partagé entre comptes) : c'est un coût ponctuel.

**Usage sans se reconnecter.** Le service interroge l'API d'usage avec le jeton
de chaque profil. Il renouvelle lui-même les jetons des comptes inactifs ; celui
du compte actif est laissé à Claude Code tant qu'il tourne, pour ne jamais
invalider une session.

Détails : [docs/architecture.md](docs/architecture.md) ·
guide complet : [docs/utilisation.md](docs/utilisation.md).

## Données et confidentialité

Tout reste sur la machine, dans `~/.claude-accounts/` (dossier 700, fichiers
600) : profils, `history.db` (relevés et événements, 60 jours), `settings.json`,
`state.json`. CCS ne contacte que les serveurs d'Anthropic (usage et
renouvellement des jetons). Aucun jeton n'apparaît dans les journaux, l'état
partagé ou les notifications.

## Dépannage

| Symptôme | Solution |
|---|---|
| « le compte connecté n'est enregistré dans aucun profil » | `ccs save <nom>` avant de basculer (protège ce compte). |
| « connexion expirée ou révoquée » | `ccs rm <nom>` puis `ccs add <nom>`. |
| Pas de bascule automatique | `ccs status` : service en marche ? bascule activée ? Un autre compte sous 80 % ? |
| Indicateur absent | Extension « Ubuntu AppIndicators » (voir Installation). |
| Les commandes lancent une ancienne version | Supprime les anciennes copies : `rm ~/.local/bin/ccs ~/.local/bin/claude-accounts`. |

Journaux du service : `journalctl --user -u ccs-daemon`.

## Désinstallation

```sh
systemctl --user disable --now ccs-daemon
sudo apt remove ccs
rm -rf ~/.claude-accounts      # optionnel : profils et historique
```

Les comptes restent connectés chez Anthropic ; seul le compte actif reste
utilisable par Claude Code.

## Développement

Projet géré en **git flow** (`main` / `develop`, tags `vX.Y.Z`), commits
conventionnels en français. Python 3 (bibliothèque standard + PyGObject) et
bash.

```sh
make test     # 100+ tests unitaires + scénario de bout en bout de ccs
make deb      # tests, paquet, SHA256SUMS et lintian dans dist/
```

Structure : `bin/` (commandes), `ccs_app/` (cœur, prévisions, bascule, alertes,
service, analyse, interface), `data/` (lanceurs, icône, unité systemd),
`debian/`, `docs/`, `tests/`.

## Licence

[MIT](LICENSE) © 2026 mawena
