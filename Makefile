.PHONY: install init universe ingest ingest-fast score serve scheduler status test clean

install:
	uv venv --python 3.13
	uv pip install -e ".[dev]"

init:
	uv run bioterm init-db
	uv run bioterm universe

ingest:            ## full pipeline over the whole universe
	uv run bioterm ingest

ingest-fast:       ## quick pass over a 40-ticker slice
	uv run bioterm ingest --limit 40

score:
	uv run bioterm score

serve:
	uv run bioterm serve

scheduler:
	uv run bioterm scheduler

status:
	uv run bioterm status

test:
	uv run pytest -q

clean:
	rm -rf data/bioterm.db data/cache
