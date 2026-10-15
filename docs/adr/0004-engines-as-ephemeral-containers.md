# 4. Engines run as ephemeral Docker containers

Status: accepted

## Context
Model checkers are hard to install, have conflicting dependencies, and may consume all memory or
never terminate.

## Decision
One image per engine, one `docker run --rm` per job, with no network, a read-only filesystem and
memory, CPU and process limits. A single file contract (`docs/engine-contract.md`) is the only
interface between the API and an engine. Only `infrastructure/docker_runner.py` starts processes.

## Consequences
- Isolation and reproducibility (pinned versions per image).
- Container start-up cost, negligible next to model checking.
- The API needs Docker access: mounting the socket is acceptable locally only (security review issue).
