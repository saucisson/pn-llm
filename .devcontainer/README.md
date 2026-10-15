# Development container

Reproduces `make setup`: Python 3.14, Node 22, the Docker client and the GitHub CLI, then the
locked dependencies and the git hooks (`postCreateCommand`).

**Docker socket.** Engines run in containers started by the API (ADR 0004, ADR 0016). The
`docker-outside-of-docker` feature gives the container the *host's* Docker daemon through its
socket, so engine containers run next to the dev container, not inside it. This gives the
container near-root access to the host: acceptable on a developer machine, never in a shared or
deployed environment (`docs/security-container-launching.md`).

Ports: 8000 (API, chat UI under `/ui`), 5173 (Vite dev server). Use WSL2 or Linux file systems for
the checkout, never `/mnt/c`.
