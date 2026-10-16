# One command per quality gate. Hooks and CI run the same tools (see .pre-commit-config.yaml).
# Tools come from api/.venv when it exists, otherwise from the active virtualenv.
export PATH := $(CURDIR)/api/.venv/bin:$(PATH)
RUFF_CONFIG := --config api/pyproject.toml

.DEFAULT_GOAL := help
.PHONY: help setup lock format lint typecheck arch docs-check schemas schemas-check budgets openapi openapi-check ui-check test cov docker-test mutation changelog audit check hooks

help:  ## List the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

setup:  ## Create api/.venv, install dependencies and git hooks (run once)
	python3.14 -m venv api/.venv
	api/.venv/bin/pip install --quiet --require-hashes -r api/requirements-dev.txt
	api/.venv/bin/pip install --quiet --no-deps --no-build-isolation -e api
	api/.venv/bin/pre-commit install

lock:  ## Re-resolve the locked, hashed dependencies (after changing pyproject.toml)
	uv pip compile api/pyproject.toml --python-version 3.14 --generate-hashes -o api/requirements.txt
	uv pip compile api/pyproject.toml --extra dev --python-version 3.14 --generate-hashes -o api/requirements-dev.txt
	uv pip compile engines/common/requirements.in --python-version 3.14 --generate-hashes -o engines/common/requirements.txt
	uv pip compile engines/smpt/requirements.in --python-version 3.14 --generate-hashes -o engines/smpt/requirements.txt

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

openapi-check:  ## Committed OpenAPI document in sync with the API
	python3 scripts/export_openapi.py --check

budgets:  ## Size budgets of modules, functions and classes
	python3 scripts/check_budgets.py

schemas-check:  ## Committed JSON Schemas in sync with the models
	python3 scripts/export_schemas.py --check

openapi:  ## Export the OpenAPI document (the UI types come from it)
	python3 scripts/export_openapi.py

ui-check:  ## UI: biome, tsc strict, vitest (needs Node 22, see ui/.nvmrc)
	cd ui && npm ci && npm run check:api && npm run check

test:  ## Fast tests
	cd api && pytest -q

cov:  ## Tests with branch coverage and the minimum threshold
	cd api && pytest -q -m 'not docker' --cov=app --cov-branch --cov-report=term-missing

docker-test:  ## Tests against the engine images built here (slow; build them first, docs/engines.md)
	cd api && pytest -q -m docker

mutation:  ## Mutation testing of domain and application (slow; one module: scripts/mutation.sh 'app.domain.canonical*')
	scripts/mutation.sh

changelog:  ## Regenerate CHANGELOG.md from the conventional commits (needs git-cliff)
	git cliff --output CHANGELOG.md

audit:  ## Known vulnerabilities in dependencies
	cd api && pip-audit --require-hashes -r requirements-dev.txt

check: lint typecheck arch docs-check budgets schemas-check openapi-check cov  ## Everything the CI runs on the Python code

hooks:  ## Run every git hook on all files (commit and push stages)
	pre-commit run --all-files
	pre-commit run --all-files --hook-stage pre-push
