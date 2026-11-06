#!/usr/bin/env bash
# Test de bout en bout de `ccs` dans un HOME isolé avec de faux comptes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CCS="$ROOT/bin/ccs"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export HOME="$T/home" NO_COLOR=1
unset CLAUDE_CONFIG_DIR CCS_HOME
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

echo "OK ccs_e2e"
