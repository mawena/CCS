#!/usr/bin/env bash
# Test de bout en bout de `ccs` dans un HOME isolé avec de faux comptes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CCS="$ROOT/bin/ccs"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export HOME="$T/home" NO_COLOR=1
unset CLAUDE_CONFIG_DIR CCS_HOME CCS_VIA
# Jamais le vrai bureau : pas de bus D-Bus (notifications), réglages GNOME en mémoire.
mkdir -p "$T/run"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$T/aucun-bus" XDG_RUNTIME_DIR="$T/run" GSETTINGS_BACKEND=memory
mkdir -p "$HOME/.claude" "$T/bin"

cat >"$HOME/.claude/.credentials.json" <<'E'
{"claudeAiOauth":{"accessToken":"A1","refreshToken":"R1","subscriptionType":"pro"},"organizationUuid":"orgA","mcpOAuth":{"x":1}}
E
cat >"$HOME/.claude.json" <<'E'
{"numStartups":5,"oauthAccount":{"accountUuid":"uA","organizationUuid":"orgA","emailAddress":"a@x.com","organizationName":"OrgA"}}
E
# Faux `claude auth login` : connecte le compte B.
cat >"$T/bin/claude" <<'E'
#!/bin/bash
c="$HOME/.claude/.credentials.json"; g="$HOME/.claude.json"
jq '.claudeAiOauth={"accessToken":"B1","refreshToken":"RB","subscriptionType":"max"}|.organizationUuid="orgB"' "$c" >"$c.t" && mv "$c.t" "$c"
jq '.oauthAccount={"accountUuid":"uB","organizationUuid":"orgB","emailAddress":"b@y.com","organizationName":"OrgB"}' "$g" >"$g.t" && mv "$g.t" "$g"
E
chmod +x "$T/bin/claude"
# Faux `dpkg` : ce n'est jamais une installation par paquet, donc `ccs mise-a-jour` s'arrête
# avant tout accès au réseau (jamais de vrai téléchargement ni d'installation dans ce test).
printf '#!/bin/bash\nexit 1\n' >"$T/bin/dpkg"; chmod +x "$T/bin/dpkg"
export PATH="$T/bin:$PATH"

fail() { echo "ÉCHEC : $*" >&2; exit 1; }
expect() { grep -q -- "$2" <<<"$1" || fail "attendu « $2 » dans : $1"; }

out="$("$CCS" 2>&1)"; expect "$out" "Aucun profil"
out="$("$CCS" save perso)"; expect "$out" "profil 'perso' enregistré"
out="$("$CCS" add pro)"; expect "$out" "profil 'pro' ajouté"
out="$("$CCS" add pro2 2>&1 || true)"; expect "$out" "même compte"
out="$("$CCS")"; expect "$out" "● pro"

# Claude renouvelle le jeton du compte actif : la bascule doit le sauvegarder.
c="$HOME/.claude/.credentials.json"
jq '.claudeAiOauth.refreshToken="RB2"' "$c" >"$c.t" && mv "$c.t" "$c"
out="$("$CCS" perso)"; expect "$out" "basculé sur 'perso'"
[[ "$(jq -r .claudeAiOauth.refreshToken "$HOME/.claude-accounts/pro/oauth.json")" == RB2 ]] || fail "jeton renouvelé non sauvegardé"
[[ "$(jq -c .mcpOAuth "$c")" == '{"x":1}' ]] || fail "mcpOAuth perdu"
[[ "$(jq -r .numStartups "$HOME/.claude.json")" == 5 ]] || fail "~/.claude.json abîmé"
[[ "$(jq -r .oauthAccount.emailAddress "$HOME/.claude.json")" == a@x.com ]] || fail "oauthAccount non basculé"

out="$("$CCS" next)"; expect "$out" "basculé sur 'pro'"
[[ "$("$CCS" current)" == pro ]] || fail "current"
out="$("$CCS" rm pro 2>&1 || true)"; expect "$out" "compte actif"
"$CCS" perso >/dev/null
out="$("$CCS" rename pro travail)"; expect "$out" "'pro' → 'travail'"
out="$("$CCS" rm travail)"; expect "$out" "supprimé"

# Compte connecté non enregistré : on refuse de basculer (il serait perdu).
"$CCS" save autre >/dev/null 2>&1 || true
g="$HOME/.claude.json"
jq '.oauthAccount.accountUuid="uZ"' "$g" >"$g.t" && mv "$g.t" "$g"
out="$("$CCS" perso 2>&1 || true)"; expect "$out" "n'est enregistré dans aucun profil"
[[ "$(stat -c %a "$HOME/.claude-accounts/perso/oauth.json")" == 600 ]] || fail "droits du profil"

# Réglages et statut via claude-accounts (pas de réseau : lecture de state.json).
out="$("$CCS" auto off)"; expect "$out" "désactivée"
out="$("$CCS" status)"; expect "$out" "Bascule automatique : désactivée"
out="$("$CCS" auto on)"; expect "$out" "activée"
out="$("$CCS" help)"; expect "$out" "ccs best"
out="$("$CCS" orch on)"; expect "$out" "activé"
out="$("$CCS" status)"; expect "$out" "Orchestrateur : activé"
out="$("$CCS" help)"; expect "$out" "ccs plan"
out="$("$CCS" help)"; expect "$out" "ccs title <id> <titre>"

# Revue finale C1 : `ccs use` attend le verrou tenu par le service.
g="$HOME/.claude.json"
jq --slurpfile a "$HOME/.claude-accounts/perso/account.json" '.oauthAccount=$a[0]' "$g" >"$g.t" && mv "$g.t" "$g"
"$CCS" add lockb >/dev/null            # faux login : compte B, devient actif
flock "$HOME/.claude-accounts/.lock" sleep 2 &
locker=$!
sleep 0.3
start=$(date +%s%N)
"$CCS" perso >/dev/null
elapsed=$(( ($(date +%s%N) - start) / 1000000 ))
wait $locker
(( elapsed >= 1200 )) || fail "ccs n'a pas attendu le verrou (${elapsed} ms)"
[[ "$("$CCS" current)" == perso ]] || fail "bascule après verrou"

# Correctif 0.3.1 : connexion perdue, Claude Code a vidé les jetons du fichier
# vivant. Quitter ce compte ne doit pas recopier ces jetons vides dans son profil.
c="$HOME/.claude/.credentials.json"
p="$HOME/.claude-accounts/perso/oauth.json"
rt="$(jq -r .claudeAiOauth.refreshToken "$p")"
[[ -n "$rt" && "$rt" != null ]] || fail "préparation : perso sans jeton"
jq '.claudeAiOauth += {"accessToken":"","refreshToken":"","expiresAt":0}' "$c" >"$c.t" && mv "$c.t" "$c"
out="$("$CCS" lockb)"; expect "$out" "basculé sur 'lockb'"
[[ "$(jq -r .claudeAiOauth.refreshToken "$p")" == "$rt" ]] || fail "jetons vides recopiés dans le profil quitté"

# Un profil sans jeton (vide ou absent) n'est jamais installé : message clair,
# fichiers vivants intacts.
for variant in '.claudeAiOauth.refreshToken=""' 'del(.claudeAiOauth.refreshToken)'; do
  jq "$variant" "$p" >"$p.t" && mv "$p.t" "$p"
  before="$(cat "$c" "$HOME/.claude.json" | sha256sum)"
  out="$("$CCS" perso 2>&1)" && fail "bascule acceptée sur un profil sans jeton ($variant)"
  expect "$out" "connexion perdue"
  expect "$out" "ccs rm perso"
  expect "$out" "ccs add perso"
  [[ "$(cat "$c" "$HOME/.claude.json" | sha256sum)" == "$before" ]] || fail "fichiers vivants modifiés ($variant)"
  [[ "$("$CCS" current)" == lockb ]] || fail "compte actif changé ($variant)"
done

# `ccs next` saute les profils dont la connexion est perdue (perso est sans
# jeton depuis le test précédent).
mkprof() { # nom uuid jeton (vide = connexion perdue)
  local d="$HOME/.claude-accounts/$1"
  mkdir -p "$d"
  jq -n --arg r "$3" '{claudeAiOauth:{accessToken:"A",refreshToken:$r,subscriptionType:"pro"},organizationUuid:"org"}' >"$d/oauth.json"
  jq -n --arg u "$2" '{accountUuid:$u,organizationUuid:"org",emailAddress:"\($u)@x.com",organizationName:"Org"}' >"$d/account.json"
  chmod 600 "$d"/*.json
}
mkprof aaa uAAA ""
mkprof zeta uZETA RZ
[[ "$("$CCS" current)" == lockb ]] || fail "préparation : lockb actif"
# lockb → perso (sans jeton) sauté → zeta.
out="$("$CCS" next 2>&1)" || fail "next a échoué : $out"
expect "$out" "basculé sur 'zeta'"
# Fin de liste : retour au début, aaa (sans jeton) sauté → lockb.
out="$("$CCS" next 2>&1)" || fail "next (retour au début) a échoué : $out"
expect "$out" "basculé sur 'lockb'"
# Plus aucun autre profil utilisable : message clair, fichiers vivants intacts.
"$CCS" rm zeta >/dev/null
before="$(cat "$c" "$HOME/.claude.json" | sha256sum)"
out="$("$CCS" next 2>&1)" && fail "next accepté sans autre profil utilisable"
expect "$out" "connexion perdue"
expect "$out" "ccs rm aaa"; expect "$out" "ccs add aaa"
expect "$out" "ccs rm perso"; expect "$out" "ccs add perso"
[[ "$(cat "$c" "$HOME/.claude.json" | sha256sum)" == "$before" ]] || fail "fichiers vivants modifiés par next"
[[ "$("$CCS" current)" == lockb ]] || fail "compte actif changé par next"

# Raccourcis clavier (--notifier) : résultat en notification (claude-accounts n'atteint
# aucun bus ici : repli sur un faux notify-send qui note ses arguments) ; origine de
# la bascule notée pour le journal (switch-origin.json).
origin="$HOME/.claude-accounts/switch-origin.json"
notes="$T/notifications"
: >"$notes"
cat >"$T/bin/notify-send" <<E
#!/bin/bash
printf '%s\n' "\$*" >>"$notes"
E
chmod +x "$T/bin/notify-send"
rm -f "$origin"
out="$("$CCS" next --notifier 2>&1)" && fail "next --notifier accepté sans autre profil utilisable"
expect "$(cat "$notes")" "Bascule impossible"; expect "$(cat "$notes")" "connexion perdue"
[[ ! -e "$origin" ]] || fail "origine notée pour une bascule impossible"
mkprof zeta2 uZETA2 RZ2
out="$("$CCS" next --notifier)"; expect "$out" "basculé sur 'zeta2'"
expect "$(tail -1 "$notes")" "Bascule sur zeta2"; expect "$(tail -1 "$notes")" "uZETA2@x.com"
[[ "$(jq -r '.profile + " " + .via + " " + (.ts | type)' "$origin")" == "zeta2 raccourci number" ]] \
  || fail "origine d'un raccourci : $(cat "$origin")"
[[ "$(stat -c %a "$origin")" == 600 ]] || fail "droits de switch-origin.json"
out="$("$CCS" next --oups 2>&1)" && fail "option inconnue acceptée par next"
expect "$out" "usage : ccs next"
# À la main : « ccs » ; lancé par l'application ou le service (CCS_VIA vide) : rien ;
# origine notée juste avant par l'application pour ce compte : gardée ; sans --notifier,
# aucune notification.
rm -f "$origin"
"$CCS" lockb >/dev/null
[[ "$(jq -r '.profile + " " + .via' "$origin")" == "lockb ccs" ]] || fail "origine à la main : $(cat "$origin")"
rm -f "$origin"
CCS_VIA= "$CCS" use zeta2 >/dev/null
[[ ! -e "$origin" ]] || fail "origine notée alors que l'appelant s'en charge"
printf '{"profile":"lockb","via":"application","ts":%s}\n' "$(date +%s)" >"$origin"
"$CCS" lockb >/dev/null
[[ "$(jq -r .via "$origin")" == application ]] || fail "origine notée par l'application écrasée"
[[ "$(grep -c . "$notes")" == 2 ]] || fail "notification sans --notifier : $(cat "$notes")"
out="$("$CCS" lockb --notifier)"; expect "$out" "Déjà sur 'lockb'"
expect "$(tail -1 "$notes")" "Déjà sur lockb"

# Pause : bascule automatique et orchestrateur suspendus, visible dans le statut.
out="$("$CCS" pause)"; expect "$out" "Pas de pause"
out="$("$CCS" pause 4h)"; expect "$out" "en pause jusqu"
out="$("$CCS" status)"; expect "$out" "En pause jusqu"
out="$("$CCS" pause off)"; expect "$out" "Pause levée"
out="$("$CCS" status)"; grep -q "En pause" <<<"$out" && fail "pause encore affichée : $out"
out="$("$CCS" pause 2h 2>&1)" && fail "durée inconnue acceptée"
expect "$out" "usage : ccs pause"
out="$("$CCS" help)"; expect "$out" "ccs pause"; expect "$out" "ccs doctor"
expect "$out" "ccs preview <id>"; expect "$out" "ccs export <id>"

# Aperçu et export d'une conversation de l'historique (journal synthétique).
proj="$HOME/Work/App"
mkdir -p "$proj" "$HOME/.claude/projects/${proj//[^A-Za-z0-9]/-}"
sid=5e1d0c2b-1111-4222-8333-444455556666
cat >"$HOME/.claude/projects/${proj//[^A-Za-z0-9]/-}/$sid.jsonl" <<E
{"type":"user","cwd":"$proj","sessionId":"$sid","entrypoint":"cli","timestamp":"2026-11-04T10:00:00.000Z","message":{"role":"user","content":"Explique le module de paie"}}
{"type":"assistant","cwd":"$proj","timestamp":"2026-11-04T10:01:00.000Z","message":{"id":"m1","role":"assistant","model":"claude-opus-5-5","content":[{"type":"text","text":"Le module calcule les salaires."}],"usage":{"input_tokens":2000,"output_tokens":300}}}
{"type":"custom-title","customTitle":"Module de paie","sessionId":"$sid"}
E
out="$("$CCS" preview 5e1d)"; expect "$out" "# Module de paie"
expect "$out" "Le module calcule les salaires."; expect "$out" "- Coût : "
out="$("$CCS" apercu "$sid" | head -1)"; [[ "$out" == "# Module de paie" ]] || fail "alias apercu : $out"
out="$("$CCS" preview zzzz 2>&1)" && fail "identifiant inconnu accepté"
expect "$out" "aucune conversation"
out="$(cd "$T" && "$CCS" export 5e1d)"; [[ "$out" == "$T/module-de-paie.md" ]] || fail "export : $out"
grep -q "Le module calcule les salaires." "$T/module-de-paie.md" || fail "contenu exporté"
out="$("$CCS" export 5e1d "$T/notes/paie.md")"; [[ -s "$T/notes/paie.md" ]] || fail "export vers un fichier : $out"
out="$("$CCS" title 5e1d Paie mensuelle)"; expect "$out" "« Paie mensuelle »"
out="$("$CCS" preview 5e1d | head -1)"; [[ "$out" == "# Paie mensuelle" ]] || fail "titre après ccs title : $out"

# Commandes de la 0.6 (sans service : historique vide, journaux du HOME de test).
status_of() { local rc=0; "$@" >"$T/out" 2>"$T/err" || rc=$?; echo "$rc"; }
out="$("$CCS" journal)"; expect "$out" "Aucune bascule sur cette période"
out="$("$CCS" journal --tout)"; expect "$out" "Aucune bascule"
[[ "$(status_of "$CCS" journal --jours 0)" == 2 ]] || fail "journal --jours 0 : code de sortie"
expect "$(cat "$T/err")" "usage : ccs journal"
[[ "$(status_of "$CCS" journal --jours 2 --tout)" == 2 ]] || fail "journal --jours et --tout ensemble"
out="$(cd "$proj" && "$CCS" projet lockb)"; expect "$out" "~/Work/App → lockb"
out="$("$CCS" projet)"; expect "$out" "~/Work/App  → lockb"
out="$("$CCS" projet "$proj/sous" 2>&1)" && fail "dossier absent accepté"
mkdir -p "$proj/sous"
out="$("$CCS" projet "$proj/sous")"; expect "$out" "hérité de ~/Work/App"
out="$("$CCS" projet "$proj" aucun)"; expect "$out" "n'est plus associé"
[[ "$(status_of "$CCS" projet "$proj" inconnu)" == 1 ]] || fail "projet : compte inconnu"
[[ "$(status_of "$CCS" projet a b c)" == 2 ]] || fail "projet : usage"
out="$("$CCS" semaine)"; expect "$out" "Bilan de la semaine du"
out="$("$CCS" semaine --precedente 3)"; expect "$out" "Bilan de la semaine du"
[[ "$(status_of "$CCS" semaine --precedente -1)" == 2 ]] || fail "semaine : N négatif"
[[ "$(status_of "$CCS" semaine --precedente deux)" == 2 ]] || fail "semaine : N illisible"
out="$("$CCS" mois)"; expect "$out" "Rapport"
[[ "$(status_of "$CCS" mois --precedent -1)" == 2 ]] || fail "mois : N négatif"
[[ "$(status_of "$CCS" mois --precedent deux)" == 2 ]] || fail "mois : N illisible"
[[ "$(status_of "$CCS" moment)" == 1 ]] || fail "moment sans état"
[[ "$(status_of "$CCS" moment --duree zéro)" == 2 ]] || fail "moment : durée illisible"
out="$("$CCS" silence)"; expect "$out" "Pas de silence"
out="$("$CCS" silence 1h)"; expect "$out" "Silence jusqu"
out="$("$CCS" status)"; expect "$out" "Ne pas déranger jusqu"
out="$("$CCS" quiet reprendre)"; expect "$out" "Silence levé"
out="$("$CCS" status)"; grep -q "Ne pas déranger" <<<"$out" && fail "silence encore affiché : $out"
[[ "$(status_of "$CCS" silence 2h)" == 2 ]] || fail "silence : durée inconnue acceptée"
[[ "$(status_of "$CCS" mise-a-jour --verifier)" == 1 ]] || fail "mise à jour : copie de développement"
expect "$(cat "$T/err")" "Copie de développement"
[[ "$(status_of "$CCS" maj --force)" == 2 ]] || fail "mise à jour : option inconnue"
out="$("$CCS" formule)"; expect "$out" "Conseiller de formule"
out="$("$CCS" conseil)"; expect "$out" "Conseiller de formule"
[[ "$(XDG_CURRENT_DESKTOP=KDE status_of "$CCS" raccourcis)" == 1 ]] || fail "raccourcis hors GNOME"
expect "$(cat "$T/out")" "seulement sous GNOME"; expect "$(cat "$T/out")" "ccs next --notifier"
[[ "$(status_of "$CCS" raccourcis set suivant K)" == 1 ]] || fail "raccourci sans modificateur accepté"
expect "$(cat "$T/err")" "Ajoute Super, Ctrl ou Alt"
[[ "$(status_of "$CCS" shortcuts on zzz)" == 2 ]] || fail "raccourcis : action inconnue"
out="$("$CCS" help)"; expect "$out" "ccs formule"; expect "$out" "ccs semaine"
expect "$out" "ccs journal"; expect "$out" "ccs projet"; expect "$out" "ccs raccourcis"
expect "$out" "ccs mois"; expect "$out" "ccs moment"; expect "$out" "ccs silence"
expect "$out" "ccs mise-a-jour"
expect "$out" "--notifier"
# Ligne d'état : contexte de la session sur l'entrée standard, jamais d'attente.
out="$(timeout 5 "$ROOT/bin/claude-accounts" statusline </dev/null)" || fail "ligne d'état sans entrée"
[[ -n "$out" ]] || fail "ligne d'état vide"
out="$(echo '{"model":{"id":"claude-opus-5-5"}}' | timeout 5 "$ROOT/bin/claude-accounts" statusline)" \
  || fail "ligne d'état avec contexte"

# Commandes de la 0.8 : file de tâches, budget, fiche, sauvegarde, téléphone (dossier de test,
# aucun service, aucun envoi : le téléphone est désactivé et sans canal).
out="$("$CCS" help)"
for w in "ccs tache" "ccs budget" "ccs fiche" "ccs sauvegarde" "ccs restaurer" "ccs telephone"; do
  expect "$out" "$w"
done
for alias in tache taches tasks; do
  out="$("$CCS" "$alias")"; expect "$out" "Aucune tâche"
done
out="$("$CCS" tache ajouter "relire le journal" -C "$proj" --droits lecture --quand nuit)"
expect "$out" "ajoutée"
out="$("$CCS" tache)"; expect "$out" "relire le journal"
[[ "$(stat -c %a "$HOME/.claude-accounts/tasks.json")" == 600 ]] || fail "droits de tasks.json"
tid="$(jq -r '(.tasks // .)[0].id' "$HOME/.claude-accounts/tasks.json" 2>/dev/null || true)"
[[ -n "$tid" && "$tid" != null ]] || fail "identifiant de tâche illisible"
out="$("$CCS" tache annuler "$tid")"; expect "$out" "annulée"
out="$("$CCS" tache supprimer "$tid")"; expect "$out" "supprimée"
[[ "$(status_of "$CCS" tache annuler)" == 2 ]] || fail "tache annuler sans identifiant"
[[ "$(status_of "$CCS" tache ajouter)" == 2 ]] || fail "tache ajouter sans message"
[[ "$(status_of "$CCS" tache voir inconnue)" == 1 ]] || fail "tache voir : identifiant inconnu"
out="$("$CCS" budget "$proj" 25)"; expect "$out" "25"
out="$("$CCS" budget)"; expect "$out" "App"
out="$("$CCS" budget "$proj" aucun)"; expect "$out" "supprimé"
[[ "$(status_of "$CCS" budget a b c)" == 2 ]] || fail "budget : usage"
[[ "$(status_of "$CCS" budget "$proj" beaucoup)" == 1 ]] || fail "budget : montant illisible"
[[ "$(status_of "$CCS" fiche)" == 2 ]] || fail "fiche sans identifiant"
expect "$(cat "$T/err")" "usage : ccs fiche"
[[ "$(status_of "$CCS" fiche zzzz)" == 1 ]] || fail "fiche : conversation inconnue"
[[ "$(status_of "$CCS" restaurer)" == 2 ]] || fail "restaurer sans fichier"
[[ "$(status_of "$CCS" restore "$T/inexistant.gpg" --oui)" == 1 ]] || fail "restaurer : fichier absent"
[[ "$(status_of "$CCS" backup un deux)" == 2 ]] || fail "sauvegarde : trop d'arguments"
out="$("$CCS" telephone)"; expect "$out" "désactivées"; expect "$out" "Canal   : aucun"
out="$("$CCS" phone)"; expect "$out" "Serveur"
[[ "$(status_of "$CCS" telephone essai)" == 1 ]] || fail "téléphone : essai sans canal"
expect "$(cat "$T/err")" "crée un canal"
[[ "$(status_of "$CCS" telephone zzz)" == 2 ]] || fail "téléphone : argument inconnu"
out="$("$CCS" sessions)"; expect "$out" "Aucune session"

echo "OK ccs_e2e"
