.PHONY: install format lint test check clean

install:
	uv sync --extra preview --group dev --group test
	uv run pre-commit install

format:
	uv run ruff format openapi_burrito tests

lint:
	uv run ruff check --fix openapi_burrito tests
	uv run mypy openapi_burrito tests

test:
	uv run pytest --cov=openapi_burrito

# Run all checks (lint, typecheck, test)
check: format lint test

clean:
	rm -rf .ruff_cache .pytest_cache .mypy_cache coverage.xml .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
