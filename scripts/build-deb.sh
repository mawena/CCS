#!/usr/bin/env bash
# Construit dist/ccs_<version>_all.deb, ccs-bureau, ccs-serveur et le métapaquet ccs-all : tests (une fois), paquets,
# sommes SHA-256, lintian.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

deb_version="$(dpkg-parsechangelog -S Version)"
py_version="$(python3 -c 'import ccs_app; print(ccs_app.__version__)')"
if [[ "$deb_version" != "$py_version" ]]; then
  echo "Versions différentes : debian/changelog=$deb_version, ccs_app=$py_version" >&2
  exit 1
fi

make clean >/dev/null
make test
dpkg-buildpackage -us -uc -b
make clean >/dev/null

mkdir -p dist
rm -f dist/*.deb
for pkg in ccs ccs-bureau ccs-serveur ccs-all; do
  mv -f "../${pkg}_${deb_version}_all.deb" dist/
done
rm -f "../ccs_${deb_version}_"*.buildinfo "../ccs_${deb_version}_"*.changes
(cd dist && sha256sum ./*.deb | sed 's| \./| |' > SHA256SUMS)

for pkg in ccs ccs-bureau ccs-serveur ccs-all; do
  lintian --fail-on error "dist/${pkg}_${deb_version}_all.deb"
  echo "Paquet : dist/${pkg}_${deb_version}_all.deb"
done
