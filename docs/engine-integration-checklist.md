# Engine integration checklist

Every engine integration issue follows this list. Contract: `docs/engine-contract.md`. Policy:
`CLAUDE.md` (domain rules 1, 2, 5, 6). Time per tool should go to the adapter, not to plumbing:
the kit and the image template below do the rest.

## What exists
- **Adapter kit** `engines/common/pnverif_engine`: reads `request.json`, times the run, turns a
  tool's wording of an answer into a verdict (`normalize_verdict`: only clear words become TRUE or
  FALSE, everything else is UNKNOWN), writes `result.json` and the trace files, and turns a crash
  into a `failed` envelope. It uses the contract models of the platform, so the adapter cannot
  write an invalid output.
- **Image template** `engines/template/`: a multi-stage `Dockerfile` (build or fetch the tool at a
  pinned version, then a small runtime image), a non-root user, and an `adapter.py` skeleton.
  Build from the repository root: `docker build -f engines/<name>/Dockerfile -t pn-llm-verif/<name>:<version> .`
  `engines/dummy` is the smallest working example.

## Steps
1. **Licence.** Check that the tool can be redistributed in the image or must be fetched at build
   time; write the answer in the issue and in the image labels. If it cannot be used, document why
   and close the issue.
2. **Pinning.** The tool is built or downloaded at a release tag or a commit hash, with a checksum
   when it is a download; the base images are pinned by tag. The version is passed to the adapter
   (`TOOL_VERSION`) and appears in every result (`tool.version` of the envelope).
3. **Copy the template** to `engines/<name>/`, fill the placeholders, write `adapter.py`:
   - render each formula tree into the tool's syntax (`rendered`); never change the meaning of a
     formula (domain rule 2): a construct the tool cannot express gives `UNKNOWN` with a warning;
   - run the tool within `request.limits` (the container is killed at the timeout anyway);
   - map its output with `normalize_verdict`; give a counterexample as the ids of the transitions
     fired (`trace`), and `loop_start` for an infinite run;
   - never answer FALSE on a failure, a timeout, a crash or an unreadable output.
4. **Registry.** Add one `EngineSpec` entry in `app/infrastructure/engine_registry.py` with the
   real capabilities: logics, colored support, operations.
5. **Health check.** A trivial net and a trivial formula must run in the image; the engine is
   listed as available by `GET /v1/engines` only when the image is present.
6. **Known-verdict tests.** At least one TRUE and one FALSE per supported logic, on small nets with
   verdicts known by hand; one counterexample replayed with `POST /v1/nets/{id}/replay`. Tests that
   need the image carry the `docker` marker.
7. **Limits.** The container has no network, a read-only root, a private `/tmp`, bounded memory,
   CPU and processes (ADR 0016): the tool must work within these, writing only to `/work/output`
   and `/tmp`. Nothing is downloaded at run time.
8. **Conformance.** Verdicts agree with the tool's MCC results on the seeded models; a
   disagreement is documented and reported, never hidden (domain rule 8).
9. **CI.** Add the image to the `docker` job of `.github/workflows/ci.yml` and to the `engines`
   profile of `docker-compose.yml`.
