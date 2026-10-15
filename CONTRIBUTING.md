# Contributing

Humans and Claude Code follow the same rules. Start with `CLAUDE.md` (summary), then
`docs/conventions.md` (rules with examples), `docs/architecture.md` and `docs/testing.md`.

## Set up (WSL2 / Ubuntu, in your Linux home, not under /mnt/c)

```bash
make setup      # virtualenv in api/.venv, dependencies, git hooks (commit, commit-msg, pre-push)
source api/.venv/bin/activate
make check      # must pass before you open a pull request
```

## What runs when

- **On commit**: file hygiene, ruff lint and format, mypy, import-linter (architecture),
  architecture-doc sync, shellcheck, and the commit message format.
- **On push**: the full test suite with branch coverage (minimum 90 %).
- **In CI**: all of that on a clean machine, plus `pip-audit` and the Docker image builds.

Hooks use the tools of the active virtualenv, so activate it first. Never use `--no-verify`.

## Making a change

1. Pick (or open) a GitHub issue.
2. Write a failing test first for a bug fix; add tests with every behaviour change.
3. Follow the onion architecture: put code in the right ring.
4. `make check`.
5. Update the docs in the same commit; add an ADR (`docs/adr/`) for a significant decision.
6. Commit with a conventional message in English, one concern per commit:
   `feat: ...`, `fix: ...`, `refactor: ...`, `docs: ...`, `test: ...`, `chore: ...`.
7. Open a pull request that references the issue.

## Comment policy (checked at each commit)

Docstring on every public module, class, function and method. Comments explain why, not what.
No commented-out code. No TODO/FIXME: open an issue. A `noqa` or `type: ignore` always says why.
Details in `docs/conventions.md`.
