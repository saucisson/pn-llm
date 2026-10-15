# 7. Code style rules

Status: accepted

## Context
The code base is written largely with the help of an AI assistant and must stay uniform and
readable whoever writes the next change.

## Decision
The rules of `docs/conventions.md`: linear functions without artificial splitting, pydantic for all
data (frozen models), keyword-only parameters, no mutation of parameters, onion architecture,
docstrings explaining the public API, comments explaining why. Everything that can be checked by a
tool is (ruff, mypy, import-linter, pytest); the rest is reviewed.

## Consequences
Generous complexity limits instead of small ones; stricter signatures (every parameter is
keyword-only); a little more ceremony for data (a model instead of a tuple), in exchange for code
that reads the same everywhere.
