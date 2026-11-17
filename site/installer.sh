#!/bin/sh
# Installe CCS depuis le dépôt APT unique de mawena : https://apt.mawena.cloud/
#   curl -fsSL https://mawena.github.io/CCS/installer.sh | sudo sh
# Depuis CCS 0.20.1, CCS est publié dans le dépôt unique : ce script lance son installateur avec le paquet ccs.
# Équivaut à : curl -fsSL https://apt.mawena.cloud/installer.sh | sudo sh -s -- ccs
set -eu

INSTALLATEUR=https://apt.mawena.cloud/installer.sh

if [ "$(id -u)" -ne 0 ]; then
  echo "CCS : à lancer en administrateur, par exemple : curl -fsSL $INSTALLATEUR | sudo sh -s -- ccs" >&2
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo "CCS : apt-get introuvable ; CCS s'installe sur Ubuntu ou une distribution Debian." >&2
  exit 1
fi

if command -v curl >/dev/null 2>&1; then curl -fsSL "$INSTALLATEUR" | sh -s -- ccs
elif command -v wget >/dev/null 2>&1; then wget -qO- "$INSTALLATEUR" | sh -s -- ccs
else echo "CCS : il faut curl ou wget." >&2; exit 1
fi
echo
echo "CCS est installé. Pour vérifier : ccs doctor"
