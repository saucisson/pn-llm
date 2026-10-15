# Security of container launching

Engines are third-party model checkers fed with nets that anyone can upload. This page analyses
what can go wrong when the API starts them, what is done, and what a deployment must add.

## The risk
The API starts engine containers through the Docker daemon. Anything that can talk to the daemon
socket can ask for a privileged container that mounts the host root: **access to the socket is root
on the host**. Locally, `docker-compose.yml` mounts `/var/run/docker.sock` in the API container.
If the API process were taken over (a bug in parsing an uploaded net, in the formula parser, in
the agent that later calls the API), the attacker would own the machine.

Threats, by entry point:

| Entry | Threat | Present defences |
|---|---|---|
| Uploaded net (JSON or PNML) | XML bombs, huge nets, deep nesting, parser bugs | `defusedxml` with DTDs and entities refused; upload size, element, page-depth, XML-depth and string bounds (`Settings`), tested; pydantic parsing |
| Formula text | Pathological input | Recursive descent over a bounded token list; the tree depth is bounded by pydantic |
| Request fields reaching Docker | Image, command or mount chosen by a caller | None reach Docker: the image comes from the engine registry, mounts are temporary directories created by the API, the container name is an internal job id |
| Engine process | Escape, network access, resource exhaustion, fork bomb | Fixed profile (ADR 0016): no network, read-only root, capabilities dropped, no-new-privileges, memory, CPU and process limits, timeout then kill, always removed |
| Engine output | Oversized or hostile `result.json` | Parsed by pydantic; ids checked against the net (engine contract) |

## Limits that bound a job (tested)
- Upload size: `PNVERIF_MAX_UPLOAD_BYTES` (default 20 MB), answered with 413
  (`tests/api/test_api.py::test_oversized_upload_is_a_413`); element, depth and string bounds
  answered with 422 (`tests/unit/test_net_document.py`, `tests/unit/test_pnml_import.py`).
- Duration: `timeout_s` is at most 3600 (`tests/unit/test_models.py::test_limits_are_bounded`) and
  the container is killed at the timeout
  (`tests/integration/test_docker_runner.py::test_a_timeout_kills_and_removes_the_container`).
- Memory, processes, network, file system, capabilities: `tests/unit/test_container_spec.py` and
  the integration tests of the same file as above, against a real daemon.

## Alternatives for the daemon access
1. **Docker socket mounted in the API (today).** Simple, root-equivalent. Acceptable on a
   developer machine only.
2. **Socket proxy** (filtering `POST /containers/create`, and so on). Does not help much: the
   dangerous part is the body of the create request (privileged, host mounts), which proxies
   cannot constrain well. Rejected.
3. **Rootless Docker or rootless Podman** for the engine runtime. A compromise of the runtime or
   of an escaped container yields an unprivileged user, not root. Podman exposes a Docker-compatible
   socket (`podman system service`), so the Docker SDK works unchanged. **Recommended runtime.**
4. **A dedicated worker host (or VM) that holds the runtime**, with the API holding no socket at
   all: the API enqueues jobs and workers (issue #6) run them. A compromise of the API then gives
   no code execution on the engine host, and a compromise of an engine only reaches a disposable
   machine. **Recommended deployment**, combined with 3.
5. **A stronger sandbox runtime** (gVisor `runsc`, Kata Containers) for the engine containers,
   against kernel exploits from a hostile engine. Worth adding once real third-party engines
   run; it is a runtime flag, no code change.

## Decision
- Development: keep the socket mount, documented as local only.
- Deployment: workers on a dedicated host with rootless Podman, API without socket (depends on the
  job queue, issue #6); gVisor as a hardening option.
- Never run an engine on the host (`CLAUDE.md`, domain rule 5).

## Operational notes
- Containers are labelled `pnverif.job=<job id>`. After a crash of the whole host, remove strays
  with `docker rm -f $(docker ps -aq --filter label=pnverif.job)`.
- Keep `mem_limit` of the engine containers below the memory given to WSL2 (`.wslconfig`).
