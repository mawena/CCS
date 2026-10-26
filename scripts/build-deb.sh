#!/usr/bin/env bash
# Construit dist/ccs_<version>_all.deb : tests, paquet, sommes SHA-256, lintian.
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
mv -f "../ccs_${deb_version}_all.deb" dist/
rm -f "../ccs_${deb_version}_"*.buildinfo "../ccs_${deb_version}_"*.changes
(cd dist && sha256sum ./*.deb | sed 's| \./| |' > SHA256SUMS)

lintian --fail-on error "dist/ccs_${deb_version}_all.deb"
echo "Paquet : dist/ccs_${deb_version}_all.deb"
