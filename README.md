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

Python 3.14 and Node 22 are needed (`uv python install 3.14`; `nvm use` reads `ui/.nvmrc`).

```bash
make setup                        # virtualenv api/.venv, dependencies, git hooks
source api/.venv/bin/activate
make check                        # lint, format, types, architecture, docs sync, tests + coverage
make ui-check                     # the UI: biome, strict TypeScript, tests
```

Try the chat without any key (an offline demonstration of the agent) with the built UI:

```bash
(cd ui && npm ci && npm run build)
cd api && PNVERIF_LLM_PROVIDER=scripted PNVERIF_UI_DIR=../ui/dist \
  uvicorn app.main:create_app --factory --reload
# the chat: http://localhost:8000/ui/   interactive API docs: http://localhost:8000/docs
```

The database file defaults to `data/pnverif.sqlite`; override with
`PNVERIF_DATABASE_PATH=/path/to/file`. Several API processes and worker processes can share the
file (`python -m app.main` runs workers only). Without `PNVERIF_LLM_PROVIDER` a session ends with
an error that says so.

```bash
curl -X POST localhost:8000/v1/nets -H 'Content-Type: application/pnml+xml' --data-binary @my_net.pnml
curl localhost:8000/v1/nets/<net_id>/places                     # inspect, never the net itself
curl -X POST localhost:8000/v1/formulas/validate -H 'Content-Type: application/json' \
  -d '{"net_id":"<net_id>","text":"G !(p1 >= 1 && p2 >= 1)"}'
curl -X POST localhost:8000/v1/nets/<net_id>/checks -H 'Content-Type: application/json' \
  -d '{"formulas":[{"id":"f1","logic":"state","ast":{"op":"deadlock"}}],"engine":"dummy"}'
curl localhost:8000/v1/jobs/<job_id>
```

## Backlog

`scripts/create_issues.sh` creates the labels, milestones and issues on the GitHub repository
(see the script header). Prerequisite: `gh auth login`. Start with `--dry-run`.
