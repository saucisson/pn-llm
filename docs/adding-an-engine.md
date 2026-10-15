# Adding an engine

A walk through the whole path, from "this tool looks useful" to "its answers are in the
conformance matrix". The rules are in `docs/engine-integration-checklist.md`, the contract in
`docs/engine-contract.md`, what exists in `docs/engines.md`. This page is the order to do things in,
and what the first two integrations (Tapaal, ITS-Tools) taught.

## 1. Before writing anything

1. **Is the tool usable?** Licence (can the image be built here? redistributed?), maintenance,
   and how it is distributed: a release tag, a commit, or only "the latest build". Write the
   answer in the issue.
2. **Which questions does it answer?** Map its categories to our logics: `state` (a condition
   reached by some marking), `ctl`, `ltl`. Analyses and reductions arrive with milestone M4 and
   use the same image and request; a tool that only does those (tedd, petrivet) waits for it.
3. **Does it read the contest's formats?** Most contest tools do. If it reads the contest's
   property XML, use the writer `app/domain/mcc_xml.py` (it is tested by reading back every
   contest formula unchanged) instead of writing another renderer. If not, the renderer goes in the
   adapter, and needs the same round-trip discipline: write it, parse it back or run a
   known-verdict set, and never change the meaning of a formula (CLAUDE.md, domain rule 2).

## 2. Run the tool by hand first

Build a throw-away image or use the tool's own distribution, and run it on `tests/corpus/hand/mutex.pnml`
with one formula of each logic. Find out, before coding the adapter:

- the exact sentences or lines that mean TRUE, FALSE and "could not decide";
- how it reports a counterexample, and whether the names in it are the net's (a tool that unfolds
  a colored net, or renames after a reduction, gives names that are not in the net: give no trace);
- what it needs to write and where (home directory, temporary files, configuration), because the
  container has a read-only root and a private `/tmp` that cannot run programs;
- the options the tool's authors use in the contest: look at their wrapper script
  (`BenchKit_head.sh` and what it calls). Without them a tool may run, answer little, and look
  weak. ITS-Tools solved almost no CTL formula without `-its -order META -manyOrder -smt`;
- what happens when it cannot parse a formula: a tool that dies on one atom loses every formula
  of the run. Either run formulas one by one (Tapaal) or rewrite the atom in a form the tool
  reads, with the same meaning (ITS-Tools and `deadlock`), and say so in `docs/engines.md`.

## 3. The image

Copy `engines/template/`. The Dockerfile has two stages: build or fetch the tool at a pinned
version, then a small runtime image on `python:3.14-slim` with the shared kit and your adapter.

- **Pin.** A tag or commit for source; for a download, the SHA-256, checked in the build. If the
  authors publish only a moving "latest", pin the checksum: the build then breaks on purpose when
  they publish a new one, and a maintainer updates checksum and version together.
- **Base system.** The tool may need an older or newer Debian than the default (Tapaal builds
  on Debian 12 because of a dependency's generated files; ITS-Tools needs a Java 21 that only
  Debian 13 ships). Pin the tag; the runtime image uses the same release as the build stage.
- **Version label.** `org.opencontainers.image.version` is the version the registry names and the
  adapter reports; CI tags each image by it.
- **Read-only root.** Everything the tool wants to write goes under `/tmp` or `/work/output`.
  A tool that changes the mode of its own files at start needs them executable from the build;
  if it insists on the call anyway, see the shim in `engines/itstools/keepmode.c`.
- **Lint.** `hadolint` runs on every commit. Package versions are not pinned (`DL3008`): ignore
  that rule with the line above the `RUN` and a comment saying why.

## 4. The adapter

`engines/<name>/adapter.py` implements one function, `check(given) -> tuple[AdapterAnswer, ...]`,
and calls `run_adapter`. Conventions that held up:

- **One answer per formula**, in order. Whatever goes wrong, the kit makes the envelope; you
  decide only the verdict.
- **Verdicts.** TRUE and FALSE only from the tool's own clear sentence. A sentence that is not
  clear is UNKNOWN. The kill at the timeout is TIMEOUT, SIGKILL is OOM, a crash is ERROR.
  Never FALSE by default.
- **Time.** The container is killed at `limits.timeout_s`. Leave a few seconds for starting and
  stopping, give each run an equal share of what remains, and when the share is over keep what
  the tool printed before the kill: those are real answers.
- **`rendered`** is the exact text given to the tool (the rewritten one, if you rewrote).
- **Traces.** Only transitions of the net as given, in order, with `loop_start` for a loop.
  If the tool cannot promise that, return none and add a warning that says why. A trace for a
  TRUE answer is a witness, not a counterexample: add a warning that says so.
- **Ids.** If the tool's output has to be matched with formulas, write plain ids (`q0`, `q1`) for
  the tool and map them back; our ids are free text.
- **Warnings** are short machine words (`trace_not_given_for_colored_net`), not sentences.

## 5. Register, test, document

1. One `EngineSpec` in `app/infrastructure/engine_registry.py`: image `pn-llm-verif/<name>:<version>`,
   the version, the logics, colored or not.
2. `engines/common/requirements.in` and `.txt` hold what the shared kit needs; add a library only
   if the kit or an adapter needs it, and regenerate with `uv pip compile ... --generate-hashes`.
3. **Known verdicts.** `api/tests/integration/test_docker_<name>.py`, marked `docker`: at least
   one TRUE and one FALSE for each logic the engine supports, on small nets whose verdict is known
   by hand, the version in the report, and a counterexample if the engine gives one. The module
   fixture skips the whole module when the image is absent (an autouse function fixture does not
   run before a module fixture).
4. **Conformance.** `python -m app.conformance --cases api/tests/corpus/conformance.json
   --engines <name> --markdown`. Wrong answers and contradictions between engines are failures to
   triage and document, never to hide (domain rule 8). Non-answers within the limits are not
   contradictions; say how many there were and why.
5. `docs/engines.md`: the pinned version, the licence, build notes, what the adapter rewrites,
   what it does with traces, the conformance result. `docker-compose.yml` (profile `engines`);
   CI builds every `engines/*/Dockerfile` by itself.

## 6. When it does not go well

| Symptom | Likely cause |
|---|---|
| Every formula UNKNOWN, tool output looks fine | Missing contest options, or the verdict sentence is not the one you match |
| The whole run answers nothing, one formula looks odd | The tool crashed on one construct; run formulas separately or rewrite it |
| Works in a plain container, fails in the platform's | Read-only root, `HOME` not writable, a program started from `/tmp`, memory limit below the tool's own default (a JVM wants `-Xmx`) |
| Verdicts differ from the contest's | Compare the formula the tool received (`rendered`) with the contest's file; then check how the atoms are counted |
| Traces rejected | Names that are not the net's: unfolded colored transitions, renamed after a reduction |
