# Topographic Pleasures — see PUBLISHING.md in the glf repository for the site contract.
#
#   make dist     check prerequisites, fetch and verify the data, build site/data, render, assemble dist/
#   make check    verify prerequisites (nothing is ever installed by the build)
#   make data     fetch + build the state grids only (writes site/data/)
#   make build    convert sources/ into site/data/ without downloading
#   make render   draw site/downloads/ (each state's default SVG and PDF) with Node
#   make fetch    download and verify the source data (sources/, existing files are kept)
#   make serve    build dist/ and serve it on http://localhost:8000/
#   make clean    remove dist/ and everything generated (downloads in sources/ are kept)

PYTHON ?= python3
NODE ?= node
PORT ?= 8000

.PHONY: dist check data build render fetch clean serve

dist: data render
	rm -rf dist
	cp -r site dist

check:
	@ok=1; \
	command -v $(PYTHON) >/dev/null || { echo "python3 is required (3.8 or newer): https://www.python.org/" >&2; ok=0; }; \
	if command -v $(PYTHON) >/dev/null; then \
	  $(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || { echo "python3 is too old: 3.8 or newer is required" >&2; ok=0; }; \
	  $(PYTHON) -c 'import numpy' 2>/dev/null || { echo "missing Python package numpy: pip install -r tools/requirements.txt" >&2; ok=0; }; \
	  $(PYTHON) -c 'import shapefile, sys; sys.exit(0 if int(shapefile.__version__.split(".")[0]) >= 2 else 1)' 2>/dev/null || { echo "missing or too old Python package pyshp (2.0 or newer): pip install -r tools/requirements.txt" >&2; ok=0; }; \
	fi; \
	command -v $(NODE) >/dev/null || { echo "node is required (18 or newer, to render the previews): https://nodejs.org/" >&2; ok=0; }; \
	if command -v $(NODE) >/dev/null; then \
	  $(NODE) -e 'process.exit(parseInt(process.versions.node) >= 18 ? 0 : 1)' || { echo "node is too old: 18 or newer is required" >&2; ok=0; }; \
	fi; \
	command -v curl >/dev/null || { echo "curl is required to download the source data" >&2; ok=0; }; \
	command -v unzip >/dev/null || { echo "unzip is required to unpack the state boundaries" >&2; ok=0; }; \
	command -v sha256sum >/dev/null || { echo "sha256sum (coreutils) is required to verify downloads" >&2; ok=0; }; \
	[ $$ok = 1 ] || { echo "make check: prerequisites missing, see above" >&2; exit 1; }; \
	echo "prerequisites ok"

data: check fetch build

build: check
	$(PYTHON) tools/build_data.py        # writes site/data/; exits non-zero on any problem

render: check
	$(NODE) tools/render.mjs             # writes site/downloads/ from site/data/

fetch: check
	tools/fetch_data.sh                  # downloads into sources/, keeps existing files, verifies checksums

clean:
	rm -rf dist site/data site/downloads

serve: dist
	$(PYTHON) -m http.server $(PORT) --directory dist
