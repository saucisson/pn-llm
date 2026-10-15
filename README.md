# pn-llm-verif

REST API that lets an LLM propose, then have verified, properties of Petri nets, using static
analysis and model-checking tools run in containers. Nets come from the Model Checking Contest
(MCC) or from the user; P/T nets first, colored nets later.

Status: skeleton. The API stores nets and jobs in SQLite (persistent), runs asynchronous checks
and returns verdicts; only a dummy engine is provided. Start with `CLAUDE.md` (project rules),
`docs/objective.md` and `docs/evaluation.md` (what we want to show and how we will judge it),
`docs/architecture.md` (onion architecture), `docs/conventions.md` (code rules),
`docs/testing.md`, `docs/engine-contract.md` (add an engine) and `docs/mcc-tools.md` (tools to
integrate).

## Quick start (WSL2 / Ubuntu, in your Linux home)

```bash
make setup                        # virtualenv api/.venv, dependencies, git hooks
source api/.venv/bin/activate
make check                        # lint, format, types, architecture, docs sync, tests + coverage
cd api && uvicorn app.main:create_app --factory --reload   # interactive docs: http://localhost:8000/docs
```

The database file defaults to `data/pnverif.sqlite`; override with
`PNVERIF_DATABASE_PATH=/path/to/file`. Several API processes can share the file (job leases,
`PNVERIF_JOB_LEASE_SECONDS`).

Current implementation (v0): PNML only. The target API (JSON by default, PNML through `Content-Type`
and `Accept`) is described in `docs/net-document.md`.

```bash
curl -X POST localhost:8000/v1/nets -H 'Content-Type: application/xml' --data-binary @my_net.pnml
curl -X POST localhost:8000/v1/nets/<net_id>/checks -H 'Content-Type: application/json' \
  -d '{"formulas":[{"id":"f1","syntax":"ltl","text":"G(p -> F q)"}],"engine":"dummy"}'
curl localhost:8000/v1/jobs/<job_id>
```

## Backlog

`scripts/create_issues.sh` creates the labels, milestones and issues on the GitHub repository
(see the script header). Prerequisite: `gh auth login`. Start with `--dry-run`.
