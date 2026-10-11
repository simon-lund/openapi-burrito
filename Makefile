.PHONY: install format lint typecheck test check ci examples build clean

install:
	uv sync --extra preview --group dev --group test
	uv run pre-commit install

# --- local: fix what can be fixed ---------------------------------------------

format:
	uv run ruff format openapi_burrito tests

lint:
	uv run ruff check --fix openapi_burrito tests

typecheck:
	uv run mypy openapi_burrito tests

test:
	uv run pytest --cov

check: format lint typecheck test

# --- ci: same checks, nothing is modified ------------------------------------

ci:
	uv lock --check
	uv run ruff check openapi_burrito tests
	uv run ruff format --check openapi_burrito tests
	uv run mypy openapi_burrito tests
	uv run pytest --cov

# Generate the example clients (gitignored) and type-check them
examples:
	for example in examples/*/; do \
		uv run openapi-burrito generate "$$example/openapi.json" -o "$$example/client" -y -c async -c sync; \
		(cd "$$example/client" && ../../../.venv/bin/python -m mypy --strict .); \
	done

build:
	rm -rf dist
	uv build
	uv tool run twine check --strict dist/*

clean:
	rm -rf .ruff_cache .pytest_cache .mypy_cache .hypothesis coverage.xml .coverage dist
	find . -type d -name "__pycache__" -exec rm -rf {} +
