PYTHON ?= python3

.PHONY: test unit e2e deb apt clean

test: unit e2e

unit:
	$(PYTHON) -m unittest discover -s tests -t . -v

e2e:
	bash tests/ccs_e2e.sh

deb:
	bash scripts/build-deb.sh

# Publie dist/*.deb dans le dépôt APT signé (branche gh-pages)
apt:
	scripts/publier-apt.sh dist/*.deb

clean:
	rm -rf dist build debian/ccs debian/.debhelper debian/files debian/*.substvars debian/*.debhelper debian/debhelper-build-stamp
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
