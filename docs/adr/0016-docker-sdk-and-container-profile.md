# 16. The Docker SDK and a fixed container security profile

Status: accepted. Refines ADR 0004.

## Context
The first runner shelled out to `docker run --rm`. On a timeout only the docker client was killed:
the container could keep running. Cancellation could not stop an engine, and a memory kill was
indistinguishable from a crash.

## Decision
1. `infrastructure/docker_runner.py` uses the Docker SDK for Python (`docker`), and is the only
   module that imports it. No code starts a subprocess any more.
2. Each run creates a container named `pnverif-<job id>` and labelled `pnverif.job=<job id>`. It
   is always removed afterwards: when it finishes, times out or is killed by a cancellation.
3. The security profile is one model, `ContainerSpec`, built by `build_spec` and unit-tested: no
   network, read-only root filesystem, a private `tmpfs` on `/tmp`, all capabilities dropped,
   `no-new-privileges`, memory without swap, one CPU, 256 processes, inputs mounted read-only,
   only `/work/output` writable. The image comes from the engine registry, never from a request.
4. Outcomes are explicit: a timeout raises `DockerTimeoutError` (verdict TIMEOUT), an unreachable
   daemon raises `DockerUnavailableError` (ERROR), a memory kill gives OOM. Exit code 137 counts
   as a memory kill because Docker does not always set `OOMKilled`; an OOM result is never
   trusted even if a result file exists.
5. Cancellation stops the container at once (`EngineGateway.stop`), and the lease keeper stops it
   if the job was lost.

## Consequences
- A job cannot leave an engine running after its timeout or cancellation.
- Behaviour is verified against a real daemon (`tests/integration/test_docker_runner.py`, marker
  `docker`), not with mocks.
- The API still needs access to the Docker daemon: see `docs/security-container-launching.md`.
