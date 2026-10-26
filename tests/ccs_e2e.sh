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

echo "OK ccs_e2e"
