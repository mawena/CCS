PYTHON ?= python3

.PHONY: test unit e2e deb clean

test: unit e2e

unit:
	$(PYTHON) -m unittest discover -s tests -t . -v

e2e:
	bash tests/ccs_e2e.sh

deb:
	bash scripts/build-deb.sh

clean:
	rm -rf dist build debian/ccs debian/.debhelper debian/files debian/*.substvars debian/*.debhelper debian/debhelper-build-stamp
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
