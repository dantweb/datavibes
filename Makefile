# datavibes — dataset generator
#
# The generator runs inside the vbwd backend container because DATAVIBES_OUTPUT_DIR
# (.env) points at /app/var/... which lives in that container (bind-mounted to the
# host var/ dir). `make run` stages this tree into the container and executes the
# pipeline; the snapshot lands under $DATAVIBES_OUTPUT_DIR.

CONTAINER ?= vbwd-backend-api-1
DATASET   ?= us-regional-weather
STAGE_DIR ?= /tmp/dv
EXCLUDES  := --exclude='./.venv' --exclude='./.git' --exclude='./output' \
             --exclude='./store' --exclude='./data_out' --exclude='./__pycache__'

.PHONY: run generate process stage config list test geometry help

## run: stage into the container and run the full generator (generate → process → export)
run: stage
	docker exec -w $(STAGE_DIR) $(CONTAINER) python3 -c \
	  "import sys; sys.path.insert(0,'.'); from datavibes.cli import main; \
	   sys.argv=['datavibes','run','$(DATASET)']; main()"

## generate: collect a raw snapshot only (no processing/export)
generate: stage
	docker exec -w $(STAGE_DIR) $(CONTAINER) python3 -c \
	  "import sys; sys.path.insert(0,'.'); from datavibes.cli import main; \
	   sys.argv=['datavibes','generate','$(DATASET)']; main()"

## process: process the latest raw snapshot into the dataset
process: stage
	docker exec -w $(STAGE_DIR) $(CONTAINER) python3 -c \
	  "import sys; sys.path.insert(0,'.'); from datavibes.cli import main; \
	   sys.argv=['datavibes','process','$(DATASET)']; main()"

## stage: copy this project into the container at $(STAGE_DIR)
stage:
	docker exec $(CONTAINER) rm -rf $(STAGE_DIR)
	docker exec $(CONTAINER) mkdir -p $(STAGE_DIR)
	tar -C . $(EXCLUDES) -cf - . | docker exec -i $(CONTAINER) tar -C $(STAGE_DIR) -xf -

## config: print the effective configuration (secrets masked)
config: stage
	docker exec -w $(STAGE_DIR) $(CONTAINER) python3 -c \
	  "import sys; sys.path.insert(0,'.'); from datavibes.cli import main; \
	   sys.argv=['datavibes','config']; main()"

## list: list known datasets
list: stage
	docker exec -w $(STAGE_DIR) $(CONTAINER) python3 -c \
	  "import sys; sys.path.insert(0,'.'); from datavibes.cli import main; \
	   sys.argv=['datavibes','list']; main()"

## test: run the unit suite locally in the project venv (no network)
test:
	.venv/bin/pytest -q

## geometry: re-vendor the pinned Natural Earth 110m countries (then update the sha256 in the manifest)
NE_VERSION ?= v5.1.2
NE_URL     := https://raw.githubusercontent.com/nvkelso/natural-earth-vector/$(NE_VERSION)/geojson/ne_110m_admin_0_countries.geojson
geometry:
	mkdir -p .cache
	curl -sSfL -o .cache/ne_110m_admin_0_countries.geojson $(NE_URL)
	.venv/bin/python -I scripts/vendor_natural_earth.py .cache/ne_110m_admin_0_countries.geojson \
	  datavibes/maps/geometry/ne_110m_admin_0_countries.geojson

## help: list targets
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## //'
