# One command per quality gate. Hooks and CI run the same tools (see .pre-commit-config.yaml).
# Tools come from api/.venv when it exists, otherwise from the active virtualenv.
export PATH := $(CURDIR)/api/.venv/bin:$(PATH)
RUFF_CONFIG := --config api/pyproject.toml

.DEFAULT_GOAL := help
.PHONY: help setup format lint typecheck arch docs-check schemas schemas-check test cov audit check hooks

help:  ## List the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

setup:  ## Create api/.venv, install dependencies and git hooks (run once)
	python3.14 -m venv api/.venv
	api/.venv/bin/pip install --quiet -e "api[dev]"
	api/.venv/bin/pre-commit install

format:  ## Format and autofix (ruff)
	ruff format $(RUFF_CONFIG) api scripts engines
	ruff check $(RUFF_CONFIG) --fix api scripts engines

lint:  ## Lint (ruff)
	ruff check $(RUFF_CONFIG) api scripts engines
	ruff format $(RUFF_CONFIG) --check api scripts engines

typecheck:  ## Types (mypy --strict)
	cd api && mypy

arch:  ## Architecture rules (import-linter)
	cd api && lint-imports

docs-check:  ## Architecture document in sync with the modules
	python3 scripts/check_architecture_doc.py

schemas:  ## Export the JSON Schemas to docs/schemas/
	python3 scripts/export_schemas.py

schemas-check:  ## Committed JSON Schemas in sync with the models
	python3 scripts/export_schemas.py --check

test:  ## Fast tests
	cd api && pytest -q

cov:  ## Tests with branch coverage and the minimum threshold
	cd api && pytest -q --cov=app --cov-branch --cov-report=term-missing

audit:  ## Known vulnerabilities in dependencies
	cd api && pip-audit --skip-editable

check: lint typecheck arch docs-check schemas-check cov  ## Everything the CI runs on the Python code

hooks:  ## Run every git hook on all files (commit and push stages)
	pre-commit run --all-files
	pre-commit run --all-files --hook-stage pre-push
