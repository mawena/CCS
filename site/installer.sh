#!/bin/sh
# Installe CCS depuis son dépôt APT signé : https://mawena.github.io/CCS/
#   curl -fsSL https://mawena.github.io/CCS/installer.sh | sudo sh
# Il fait exactement les trois étapes de la page : clé du dépôt, dépôt, installation. Ensuite, `sudo apt upgrade`
# apporte les nouvelles versions.
set -eu

DEPOT=https://mawena.github.io/CCS/apt
CLE=/usr/share/keyrings/ccs.gpg
SOURCE=/etc/apt/sources.list.d/ccs.sources

if [ "$(id -u)" -ne 0 ]; then
  echo "CCS : à lancer en administrateur, par exemple : curl -fsSL https://mawena.github.io/CCS/installer.sh | sudo sh" >&2
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo "CCS : apt-get introuvable ; CCS s'installe sur Ubuntu ou une distribution Debian." >&2
  exit 1
fi

telecharger() {   # adresse fichier
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
  else echo "CCS : il faut curl ou wget." >&2; exit 1
  fi
}

echo "1/3 Clé du dépôt -> $CLE"
telecharger "$DEPOT/ccs.gpg" "$CLE.tmp" && chmod 644 "$CLE.tmp" && mv "$CLE.tmp" "$CLE"
echo "2/3 Dépôt -> $SOURCE"
telecharger "$DEPOT/ccs.sources" "$SOURCE.tmp" && chmod 644 "$SOURCE.tmp" && mv "$SOURCE.tmp" "$SOURCE"
echo "3/3 Installation"
apt-get update
apt-get install -y ccs
echo
echo "CCS est installé. Pour vérifier : ccs doctor"
