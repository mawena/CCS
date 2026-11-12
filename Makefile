PYTHON ?= python3

.PHONY: test unit e2e deb apt clean

test: unit e2e

# Les tests graphiques tournent sous Xvfb, jamais sur le bureau réel ; sans xvfb-run,
# ils sont sautés (tests/__init__.py retire alors l'affichage).
unit:
	if command -v xvfb-run >/dev/null 2>&1; then \
		CCS_GUI_TESTS=1 xvfb-run -a $(PYTHON) -m unittest discover -s tests -t . -v; \
	else \
		$(PYTHON) -m unittest discover -s tests -t . -v; \
	fi

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
