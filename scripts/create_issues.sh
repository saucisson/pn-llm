#!/usr/bin/env bash
# Create labels, milestones and issues of the backlog on the current GitHub repository.
#
# Prerequisite: gh (https://cli.github.com), authenticated (`gh auth login`), run from the clone
# of the repository (or with --repo OWNER/NAME).
#
# Usage:
#   scripts/create_issues.sh --dry-run          # print what would be created
#   scripts/create_issues.sh                    # create (idempotent: skips existing issues)
#   scripts/create_issues.sh --repo me/pn-llm   # another repository
#
# Idempotence: an issue is identified by its exact title (open and closed issues).
# To add an issue: add an `issue` call in the BACKLOG section (or a `tool_issue` call for an
# engine integration).

set -euo pipefail

DRY_RUN=0
REPO_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --repo) REPO_ARGS=(--repo "$2"); shift 2 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v gh >/dev/null || { echo "gh not found: https://cli.github.com" >&2; exit 1; }
if [[ $DRY_RUN -eq 0 ]]; then
  gh auth status >/dev/null 2>&1 || { echo "Not authenticated: gh auth login" >&2; exit 1; }
fi

# --- Repository (needed for the milestones API) --------------------------------------------------
if [[ ${#REPO_ARGS[@]} -gt 0 ]]; then
  REPO="${REPO_ARGS[1]}"
elif [[ $DRY_RUN -eq 1 ]]; then
  REPO="(current repository)"
else
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

# --- Labels --------------------------------------------------------------------------------------
declare -A LABELS=(
  ["api"]="1d76db|REST API / FastAPI"
  ["storage"]="0e8a16|Persistence and data model"
  ["engine"]="5319e7|Verification engine and adapter"
  ["mcc-tool"]="7057ff|Integration of a tool from the Model Checking Contest"
  ["mcc-data"]="006b75|MCC models, formulas, results and metadata"
  ["colored"]="e99695|Colored Petri nets"
  ["static-analysis"]="0e8a16|Structural static analysis"
  ["reduction"]="fbca04|Structural reductions"
  ["tool-selection"]="f9d0c4|Choosing among equivalent tools"
  ["llm"]="d93f0b|Agent / prompts / generated properties"
  ["bench"]="c5def5|Evaluation and benchmarks"
  ["infra"]="bfdadc|Docker, CI, WSL2, tooling"
  ["docs"]="0075ca|Documentation"
  ["paper"]="5319e7|Publication work (docs/publication.md)"
  ["quality"]="c2e0c6|Code quality, tests, tooling gates"
  ["ui"]="fef2c0|User interface (chat page)"
  ["security"]="b60205|Security and isolation"
  ["exploration"]="ededed|Research direction: hypothesis to test, not a committed feature"
)

echo "== Labels =="
for name in "${!LABELS[@]}"; do
  color="${LABELS[$name]%%|*}"
  desc="${LABELS[$name]#*|}"
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "[dry-run] label: $name"
  else
    gh label create "$name" --color "$color" --description "$desc" --force "${REPO_ARGS[@]}"
  fi
done

# --- Milestones ----------------------------------------------------------------------------------
MILESTONES=(
  "M1 - Core API and first engine"
  "M2 - MCC data and tool integrations"
  "M3 - Colored nets"
  "M4 - Static analysis and reductions"
  "M5 - LLM agent and tool selection"
  "M6 - Evaluation"
  "M7 - Exploration"
  "M8 - Text chat workflow"
  "M9 - Graph display (deferred)"
  "M10 - Publication"
)
M1="${MILESTONES[0]}"; M2="${MILESTONES[1]}"; M3="${MILESTONES[2]}"
M4="${MILESTONES[3]}"; M5="${MILESTONES[4]}"; M6="${MILESTONES[5]}"; M7="${MILESTONES[6]}"
M8="${MILESTONES[7]}"; M9="${MILESTONES[8]}"; M10="${MILESTONES[9]}"

echo "== Milestones =="
for m in "${MILESTONES[@]}"; do
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "[dry-run] milestone: $m"
  elif gh api "repos/$REPO/milestones?state=all&per_page=100" -q '.[].title' | grep -Fxq "$m"; then
    echo "milestone exists: $m"
  else
    gh api "repos/$REPO/milestones" -f title="$m" >/dev/null && echo "milestone created: $m"
  fi
done

# --- Issue helpers -------------------------------------------------------------------------------
EXISTING=""
if [[ $DRY_RUN -eq 0 ]]; then
  EXISTING="$(gh issue list --state all --limit 1000 --json title -q '.[].title' "${REPO_ARGS[@]}")"
fi

CREATED=0; SKIPPED=0
issue() { # issue "title" "comma,separated,labels" "milestone" "body"
  local title="$1" labels="$2" milestone="$3" body="$4"
  if [[ $DRY_RUN -eq 0 ]] && grep -Fxq -- "$title" <<<"$EXISTING"; then
    echo "already exists: $title"; SKIPPED=$((SKIPPED+1)); return
  fi
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "[dry-run] issue: $title  [labels: $labels | milestone: $milestone]"
  else
    gh issue create --title "$title" --label "$labels" --milestone "$milestone" \
        --body "$body" "${REPO_ARGS[@]}"
  fi
  CREATED=$((CREATED+1))
}

# Template shared by all engine-integration issues. Placeholders are replaced by tool_issue.
read -r -d '' TOOL_TEMPLATE <<'EOF' || true
Integrate **@@NAME@@** as a verification engine, following `docs/engine-contract.md`.

@@NOTES@@

**Scope**
- Examination categories to cover: @@CATEGORIES@@.
- Colored nets: @@COLORED@@.

**Acceptance criteria**
- Docker image in `engines/@@SLUG@@/` with a **pinned** version (tag or commit hash); the version
  is returned in every result (`tool.version` of the JSON envelope).
- Adapter: JSON formula tree -> native syntax (rendering recorded in the result), native output ->
  the structured JSON of `docs/json-contract.md` (envelope, `verdict`, `time_s`, structured trace). Never answer FALSE on failure: UNKNOWN / TIMEOUT / OOM / ERROR only.
- Registered in the engine registry with its real capabilities (syntaxes, colored support), and
  reported by `GET /v1/engines` (health check with a trivial net at startup).
- Known-verdict tests: at least one TRUE and one FALSE per supported category.
- Runs under the standard limits (no network, read-only filesystem, memory/CPU limits) and
  respects the timeout.
- Conformance: verdicts agree with the tool's MCC results on a small subset of seeded models
  (see the cross-engine conformance issue); disagreements are documented, not hidden.
- Licence checked: state whether the tool or its binaries can be redistributed in the image or must
  be fetched at build time.

**Depends on**: "Robust Docker runner", "Pivot formula format", "Engine integration checklist".
EOF

tool_issue() { # tool_issue "Name" "slug" "categories" "colored" "notes" [labels] [milestone]
  local name="$1" slug="$2" categories="$3" colored="$4" notes="$5"
  local labels="${6:-engine,mcc-tool}" milestone="${7:-$M2}"
  local body="$TOOL_TEMPLATE"
  body="${body//@@NAME@@/$name}"; body="${body//@@SLUG@@/$slug}"
  body="${body//@@CATEGORIES@@/$categories}"; body="${body//@@COLORED@@/$colored}"
  body="${body//@@NOTES@@/$notes}"
  issue "Integrate $name as an engine" "$labels" "$milestone" "$body"
}

echo "== Issues =="

# =================================================================================================
# BACKLOG
# =================================================================================================

# ---------------------------------------------------------------- M1 - Core API and first engine
NET_NOTE="Implements ADR 0015 and docs/net-document.md: canonical JSON net document, PNML by content negotiation, identity by canonical hash."

issue "Storage: schema migrations, retention and backups" "storage,infra" "$M1" \
"SQLite persistence exists (nets and jobs, WAL mode, idempotency key, interrupted-job recovery).
It needs to survive real use.

**Acceptance criteria**
- Versioned schema migrations (e.g. \`PRAGMA user_version\` + numbered SQL scripts), applied at startup.
- Retention policy for old jobs and results (configurable), never for nets referenced by a job.
- Documented backup/restore (SQLite online backup) and a test that restores a backup.
- Consider storing large net documents on disk (content-addressed) if the database grows too big."

issue "Job queue with workers (replace BackgroundTasks)" "api,infra" "$M1" \
"\`BackgroundTasks\` runs inside the API process: no real cancellation, no resume after a crash
(jobs are only marked \`interrupted\`).

**Acceptance criteria**
- Jobs executed by workers (RQ or Celery) with configurable concurrency, reading jobs from the
  persistent store.
- \`DELETE /v1/jobs/{id}\` kills the engine container for a running job.
- Interrupted jobs can be re-queued explicitly (\`POST /v1/jobs/{id}/retry\`)."

issue "Robust Docker runner (docker-py, limits, cleanup)" "engine,security,infra" "$M1" \
"The current runner uses \`subprocess\` + \`docker run\`. Move to the \`docker\` SDK and harden it.

**Acceptance criteria**
- Container named per job; killed and removed on timeout/cancellation (not only the docker client).
- \`--network none\`, read-only filesystem, memory/CPU/pids limits verified by tests.
- OOM detection (exit code 137 / \`OOMKilled\`) -> verdict \`OOM\`.
- Integration test with the \`engines/dummy\` image (requires Docker)."

issue "Pivot formula format (JSON AST) and per-engine translators" "api,engine" "$M1" \
"A formula is a JSON syntax tree (ADR 0013, \`docs/json-contract.md\`) whose atoms cite places and
transitions by id, with a plain-language gloss; adapters render each engine's native syntax. The
LLM never writes engine syntax.

**Acceptance criteria**
- \`Formula\` model with the tree, \`logic\`, \`gloss\`, \`origin\`; unknown ids rejected with the
  closest matches. Text parser (for users and MCC import) producing the tree for LTL, CTL,
  reachability, deadlock and bounds; clear syntax errors.
- Explicit handling of cardinality vs fireability atoms and of the neXt operator.
- \`POST /v1/formulas/validate\` returns errors and warnings.
- Round-trip tests on formulas from the MCC (depends on the MCC formula import issue)."

issue "NetDocument model: pages, graphics, tool-specific data, extensions, canonical form and hash" "api,storage" "$M1" \
"$NET_NOTE

**Acceptance criteria**
- Frozen pydantic models: \`NetDocument\`, pages as containers, places, transitions, arcs,
  reference nodes, \`Annotation\`, graphics variants, \`ToolSpecific\`, \`XmlNode\`, extensions.
- Canonical form (omit absent and default values, children sorted by id, RFC 8785 JSON) and
  \`net_id\` = first 32 hex characters of the SHA-256; names and ids never normalized.
- Validation shared by both formats (unique ids, arcs between nodes of opposite kinds, resolvable
  references) with bounded size, depth and counts; golden-hash tests."

issue "PNML importer: lossless conversion to NetDocument (P/T and colored)" "api,colored" "$M1" \
"$NET_NOTE

**Acceptance criteria**
- Hardened parsing (no DTD or entities); pages, reference nodes, graphics, tool-specific data,
  unknown elements and attributes, declarations and terms (as \`XmlNode\`) all kept.
- A file with several nets is refused with a clear error; non-integer P/T markings are refused.
- Error locations as line numbers; hostile-input tests (entity expansion, deep nesting, huge
  counts)."

issue "PNML exporter: deterministic canonical PNML from NetDocument" "api,engine" "$M1" \
"$NET_NOTE

**Acceptance criteria**
- Same document, same bytes; fixed namespace prefixes; used for \`Accept: application/pnml+xml\`
  and for the \`net.pnml\` engine input.
- Round-trip fixed point: PNML to document to PNML to document is identical."

issue "Round-trip and equivalence tests on the MCC corpus" "api,mcc-data,quality" "$M2" \
"$NET_NOTE

**Acceptance criteria**
- Fixed point and same-id tests for PNML and JSON uploads of each model; permutation and prefix
  changes keep the id; a changed name, graphic or tool-specific entry changes it.
- Engine verdicts equal on the original file and on the rendered PNML (known-verdict nets).
- Corpus report: models using pages, reference nodes, tool-specific data, colored constructs."

issue "Content negotiation on /v1/nets (Content-Type, Accept, 406, 415, ETag)" "api" "$M1" \
"$NET_NOTE

**Acceptance criteria**
- \`POST\` accepts JSON (default) or PNML; \`GET\` returns JSON by default or PNML with \`Accept\`;
  \`Location\`, \`ETag\` = net id, \`Cache-Control: immutable\`, \`Vary: Accept\`.
- 415, 406, 413 and 422 problem+json with error locations; matrix test of all combinations."

issue "Storage: store the canonical net document (compressed), drop original PNML bytes" "storage" "$M1" \
"$NET_NOTE

**Acceptance criteria**
- \`nets\` stores the compressed canonical document and its summary; identity by canonical hash
  (32 hex characters); no original file kept.
- Migration of any existing development database (re-import from stored PNML), documented."

issue "Behaviour hash (ignoring layout and tool-specific data) for deduplication" "mcc-data,bench" "$M2" \
"Optional secondary key: the same model with another layout is another net id, but evaluation
should not count it twice.

**Acceptance criteria**
- Hash over names, structure, markings and declarations only; reported next to \`net_id\`; used by
  the dataset selection and the benchmark to deduplicate."

issue "Shared JSON contract: result envelope, ElementRef, Bound, Marking, Page" "api,quality" "$M1" \
"Implements ADR 0013 and \`docs/json-contract.md\`.

**Acceptance criteria**
- Frozen pydantic models for the envelope (\`schema_version\`, \`tool\`, \`status\`, \`data\`,
  \`warnings\`, \`truncated\`, \`error\`, \`elapsed_s\`), \`ElementRef\`, \`Bound\`, \`Marking\`, pagination.
- Existing endpoints migrated; errors stay problem+json; deterministic ordering by id.
- Round-trip and ordering tests; the architecture document is updated."

issue "JSON Schema export and contract tests" "api,quality" "$M1" \
"**Acceptance criteria**
- JSON Schemas exported from the models into \`docs/schemas/\`; a hook and a test fail when stale.
- Contract test: every endpoint and tool result validates against its schema and carries the
  envelope."

issue "Net inspection endpoints: places, transitions, arcs, element, search, initial marking" "api" "$M1" \
"The LLM must learn about a net without reading it (ADR 0013).

**Acceptance criteria**
- \`GET /v1/nets/{id}/places\`, \`/transitions\`, \`/arcs\` (paginated, filters by name pattern, by
  initial marking, by source or target), \`/elements/{element_id}\` (name, input and output sets
  with weights, tokens), \`/search\`, \`/marking\`.
- Names and ids exactly as in the PNML; deterministic order; truncation explicit.
- \`NetSummary\` reduced to counts and structural flags (no full name lists)."

issue "Net inspection: neighbourhoods and families of indexed names" "api" "$M1" \
"**Acceptance criteria**
- \`/neighbourhood?ids=...&depth=k\` with a size cap and an explicit \"cut\" marker.
- \`/name-groups\`: families such as \`fork_1\` to \`fork_5\` compressed to pattern, range and count,
  so a net with 100,000 places stays readable.
- Test on a large generated net: response under the size budget."

issue "Guard: the net itself (PNML, XML, JSON document) never reaches the LLM" "llm,security,quality" "$M1" \
"**Acceptance criteria**
- Test fails if a tool in the LLM tool list can return a net document, PNML or XML, or if any
  tool result, prompt or log line sent to the LLM contains \`<pnml\`, an XML declaration or a
  \`NetDocument\` (validated against its schema).
- \`GET /v1/nets/{id}\` exists for humans and clients and is excluded from the LLM tool list."

issue "Engine contract v1: envelope, structured formulas and traces" "engine,api" "$M1" \
"Migrate \`docs/engine-contract.md\` from the implemented v0 to the target contract.

**Acceptance criteria**
- \`request.json\` and \`result.json\` follow the shared models; traces are structured; outputs
  citing unknown ids are rejected by the platform.
- Dummy engine and registry migrated; \`kind: analysis\` supported for static-analysis engines."

issue "Counterexamples: storage, trace endpoint and replay" "api" "$M1" \
"**Acceptance criteria**
- \`GET /v1/jobs/{id}/results/{k}/trace\` returns the structured trace (steps citing transition ids,
  optional loop start) in the shared envelope.
- \`POST /v1/nets/{id}/replay\` returns the successive markings as \`Marking\`; reports where a
  non-fireable trace fails.
- Test: replaying an engine's counterexample violates the formula."

issue "Engine integration checklist and common adapter library" "engine,docs" "$M1" \
"Factor out what every integration needs, so that each tool issue stays small.

**Acceptance criteria**
- Python helper library for adapters (read request, write result, timing, verdict normalization).
- Checklist in \`docs/\` (pinning, licence, health check, known-verdict tests, limits).
- Image template (multi-stage build, non-root user, no network at runtime)."

issue "CI: add Docker integration job and publish coverage" "infra,quality" "$M1" \
"The workflow \`.github/workflows/ci.yml\` already runs the quality gates (see \`CONTRIBUTING.md\`).

**Acceptance criteria**
- A job that builds \`engines/dummy\` and runs the \`docker\`-marked tests (currently skipped).
- Coverage report uploaded as an artifact; status badge in the README.
- Image builds for every engine Dockerfile as they are added."

issue "Dependency lockfile and reproducible installs" "infra,quality" "$M1" \
"**Acceptance criteria**
- Locked, hashed dependency set (uv or pip-tools) used by CI and the API Dockerfile.
- Dependabot keeps it updated; \`pip-audit\` runs against the lock."

issue "Lint Dockerfiles (hadolint) in hooks and CI" "infra,quality" "$M1" \
"**Acceptance criteria**
- hadolint hook for \`api/Dockerfile\` and \`engines/*/Dockerfile\` (pinned base images, no latest).
- Fails the commit and the CI job on violations."

issue "Structured logging and request correlation" "api,quality" "$M1" \
"**Acceptance criteria**
- JSON logs with request id, job id, net id, engine and duration; no PNML content in logs.
- Documented in \`docs/architecture.md\`; test that a job logs its lifecycle."

issue "Add a test for the retry path of job creation" "storage,quality" "$M1" \
"The only uncovered branch is the retry loop in \`SqliteStore.create_or_get_job\`.

**Acceptance criteria**
- Deterministic test of the concurrent-insert race (two threads, same live key).
- Branch coverage of \`sqlite_store.py\` reaches 100 %."

issue "Raise the coverage floor and add mutation testing" "quality" "$M1" \
"**Acceptance criteria**
- Floor raised from 90 % when stable; mutation testing (mutmut or cosmic-ray) on \`domain/\` and
  \`application/\`, results tracked over time."

issue "Architecture fitness: size and complexity budgets" "quality" "$M1" \
"**Acceptance criteria**
- Budget on module size and function complexity beyond what ruff checks, enforced by a script
  hook; budgets documented in \`docs/architecture.md\`."

issue "Devcontainer for WSL2 / VS Code and API versioning policy" "infra,docs" "$M1" \
"**Acceptance criteria**
- \`.devcontainer/\` reproducing \`make setup\`; documented Docker socket access.
- Changelog and release process (conventional commits to release notes); \`/v1\` compatibility
  policy written in \`docs/\`."

# ------------------------------------------------- M2 - MCC data: populate the database initially
issue "MCC model catalog and download script" "mcc-data,infra" "$M2" \
"Populate the project from the MCC model collection (https://mcc.lip6.fr/models.html).

**Acceptance criteria**
- Script that downloads the model archives from the MCC site into \`bench/models/\` (git-ignored),
  resumable and checksum-verified.
- Machine-readable catalog (model family, instance, year of submission, P/T or colored, source URL).
- Licence/redistribution status recorded per model; nothing is committed to git."

issue "Seed command: import MCC models into the database with provenance" "mcc-data,storage" "$M2" \
"**Acceptance criteria**
- CLI command (e.g. \`python -m app.seed mcc\`) that imports every catalog model through the same
  code path as \`POST /v1/nets\`; idempotent (re-running adds nothing).
- Metadata table: family, instance, parameters, year, \`net_type\`, source URL, MCC form reference.
- \`GET /v1/models\` to browse and search the catalog (by family, size, type, name).
- A small bundled subset (a few P/T and colored models) used by the test suite."

issue "MCC models: extract textual descriptions from the model forms" "mcc-data,llm" "$M2" \
"Each MCC model comes with a form describing it (origin, size, informal description).
This textual description is the semantic signal for the LLM.

**Acceptance criteria**
- Extract the description text and any stated properties from the forms (PDF or LaTeX source).
- Store it as a net description with origin \`mcc\` (ADR 0011, same mechanism as user
  descriptions); flag models without a usable description.
- Quality report: how many models have a description, how long, which fields."

issue "MCC models: import formulas per examination" "mcc-data,api" "$M2" \
"The MCC provides, for each model and examination, a set of formulas (XML).

**Acceptance criteria**
- Parser for the MCC formula XML into the pivot AST (all categories: reachability, CTL, LTL,
  upper bounds, global properties).
- Formulas stored per model and examination, tagged \`origin = mcc\`.
- Expected verdicts stored when the MCC publishes them (with their confidence level)."

issue "MCC historical results: import per tool, model and examination" "mcc-data,storage,tool-selection" "$M2" \
"Needed to know which tool is reliable and fast on which kind of model, and to train a selector.

**Acceptance criteria**
- Import published results: tool, year, model, examination, verdict, time, memory, status.
- Normalize tool names across years (renames, versions).
- Query API or SQL views: success rate and median time per tool x examination x model family.
- Provenance: URL and year of each result set."

issue "Model families and train/test splits for evaluation" "mcc-data,bench" "$M2" \
"**Acceptance criteria**
- Family identification (all instances of a scalable model belong to one family).
- Reproducible splits **by family** (cross-validation folds), stored in the database.
- A held-out set of families never used for tuning prompts or training selectors."

issue "Cross-engine conformance test suite" "engine,bench" "$M2" \
"**Acceptance criteria**
- Suite of small nets and formulas with verdicts established by the MCC or by hand (TRUE and
  FALSE cases for every category).
- Runs against every integrated engine; produces a matrix tool x case.
- Disagreements between engines are reported as failures needing triage."

# --------------------------------------------- M2 - one issue per MCC tool (MCC 2026 participants)
tool_issue "ITS-Tools" "itstools" \
  "StateSpace, GlobalProperties, UpperBounds, Reachability, CTL, LTL (entered in all categories)" \
  "native for P/T and colored" \
  "Entered in every MCC 2026 category (Y. Thierry-Mieg, LIP6). Uses structural reductions, including with stutter-sensitive LTL; closely related to the research this project builds on. Good candidate for the first real engine."

tool_issue "Tapaal (verifypn)" "tapaal" \
  "GlobalProperties, UpperBounds, Reachability, CTL, LTL" \
  "supported (check colored vs unfolded input options)" \
  "MCC 2026 participant (J. Srba, Aalborg University). Command-line engine \`verifypn\`; check the distribution and licence, and whether the colored engine is included."

tool_issue "TY" "ty" \
  "StateSpace, GlobalProperties, UpperBounds, Reachability, CTL, LTL" \
  "supported" \
  "MCC 2026 participant (A. Yates, Ferrite Technology). **Confirm first** whether the tool is publicly available and redistributable; if not, document why it cannot be integrated and close the issue."

tool_issue "smpt" "smpt" \
  "ReachabilityCardinality, ReachabilityFireability" \
  "supported" \
  "MCC 2026 participant (N. Amat, ONERA). Specialised in reachability; useful as a complementary engine to the others."

tool_issue "tedd" "tedd" \
  "StateSpace" \
  "supported" \
  "MCC 2026 participant (B. Berthomieu, LAAS-CNRS), part of the Tina family of tools. Entered in StateSpace; check whether other Tina tools (struct, selt, tina) should be integrated as separate engines or in the same image, for invariants and LTL/CTL model checking."

tool_issue "petrivet" "petrivet" \
  "StateSpace, GlobalProperties" \
  "**not supported** (P/T only); the engine must declare \`supports_colored = false\` so that colored nets are unfolded or routed elsewhere" \
  "MCC 2026 participant (M. Dyer, TU Munich). Sequential tool in the MCC, so useful as a single-core baseline."

# Historical participants: lower priority, availability must be confirmed first.
HIST_NOTE="Historical MCC participant, **not** in the MCC 2026 list. Before any work: confirm that the tool is still maintained, builds on a current Ubuntu, and can be redistributed or fetched at build time. If not, document it and close the issue."
tool_issue "LoLA" "lola" \
  "to be determined from past MCC results" "to be determined" "$HIST_NOTE" "engine,mcc-tool" "$M5"
tool_issue "LTSmin" "ltsmin" \
  "to be determined from past MCC results" "to be determined" "$HIST_NOTE" "engine,mcc-tool" "$M5"
tool_issue "Marcie" "marcie" \
  "to be determined from past MCC results" "to be determined" "$HIST_NOTE" "engine,mcc-tool" "$M5"
tool_issue "GreatSPN" "greatspn" \
  "to be determined from past MCC results" "to be determined" "$HIST_NOTE" "engine,mcc-tool" "$M5"
tool_issue "Smart" "smart" \
  "to be determined from past MCC results" "to be determined" "$HIST_NOTE" "engine,mcc-tool" "$M5"
tool_issue "Sift" "sift" \
  "to be determined from past MCC results" "to be determined" "$HIST_NOTE" "engine,mcc-tool" "$M5"

issue "Review the full list of past MCC participants and open missing integration issues" "mcc-tool,docs" "$M5" \
"The list of historical tools in this backlog is not exhaustive.

**Acceptance criteria**
- List every tool that took part in any past MCC edition (from the contest results pages).
- For each: still maintained? redistributable? categories covered? Record in \`docs/mcc-tools.md\`.
- Open an integration issue for each worthwhile missing tool."

# ------------------------------------------------------------------------------ M3 - Colored nets
issue "Colored nets: typed sorts and terms, summary" "colored,api" "$M3" \
"Today only P/T structure is summarized.

**Acceptance criteria**
- Typed vocabulary of sorts, declarations and terms on top of the generic \`XmlNode\` trees of the
  net document (ADR 0015); stored documents and ids do not change.
- Summary of colored nets: sorts (cyclic enumerations, finite ranges, products), place domains,
  color functions on arcs, guards; place/transition names preserved.
- Rejects unsupported constructs with a clear error rather than mis-summarizing them.
- Fixtures: at least three small colored MCC models."

issue "Data model: colored nets, unfolded nets and their relation" "colored,storage" "$M3" \
"**Acceptance criteria**
- A colored net and its P/T unfolding are two nets linked by \`parent_id\` with a stored mapping
  (unfolded place <-> colored place + color tuple; unfolded transition <-> colored transition +
  binding).
- The MCC provides unfolded versions of colored models: import them as such, with provenance.
- API exposes the relation (\`GET /v1/nets/{id}\` shows parent, unfolding mapping availability)."

issue "Unfolding service (colored -> P/T) with place/transition mapping" "colored,reduction,engine" "$M3" \
"**Acceptance criteria**
- \`POST /v1/nets/{id}/unfold\` returns a new P/T net and a mapping (using an engine's unfolder).
- Cross-check: the unfolding of a colored model equals the MCC-provided unfolded version, up to
  naming, on at least five models.
- Limits (time, size) with a clean error when the unfolding explodes."

issue "Engine capability flag: native colored support vs unfold fallback" "colored,engine,api" "$M3" \
"**Acceptance criteria**
- \`supports_colored\` is accurate per engine (already in the registry: verify it by tests).
- When the chosen engine does not support colored nets, the API unfolds first and reports it in
  the result (warning \`checked_on_unfolding\`).
- \`GET /v1/engines\` documents which examination categories work on colored nets."

issue "Formulas on colored nets: pivot AST extension" "colored,api" "$M3" \
"**Acceptance criteria**
- Atoms over colored places (token count of a place, optionally per color) and transitions
  (fireability, optionally per binding), in the pivot AST and its text syntax.
- Translators for each engine that supports colored nets; for the others, translation to the
  unfolded net using the mapping.
- Validation: unknown place, unknown color, wrong sort -> precise error."

issue "Counterexample translation for colored nets" "colored,api" "$M3" \
"**Acceptance criteria**
- A trace found on an unfolded net is reported on the colored net with bindings.
- Replay on the colored net is supported (or explicitly reported as unsupported)."

issue "Static analysis for colored nets (structure at the colored level)" "colored,static-analysis" "$M3" \
"**Acceptance criteria**
- Decide what is computed on the colored net itself vs on its unfolding (invariants, bounds,
  symmetries) and document it.
- Summary usable by the LLM: sorts, domain sizes, structure of color functions, unfolded size
  estimate before unfolding."

issue "LLM-facing summary of colored nets" "colored,llm" "$M3" \
"**Acceptance criteria**
- Compact summary (token budget) giving sorts and domains, symmetric components, and meaningful
  names, without enumerating the unfolded net.
- Evaluation item: does the colored-level summary lead to better properties than the unfolded
  net's summary? (feeds the evaluation milestone)"

issue "Colored test models and equivalence tests" "colored,bench" "$M3" \
"**Acceptance criteria**
- Small colored fixtures with verdicts known on both the colored net and its unfolding.
- Test that engines supporting both give the same verdict on the colored net and on its
  unfolding; any difference is a bug to triage."

# ------------------------------------------------------ M4 - Static analysis and reductions
OP_NOTE="One endpoint, one operation, independent of the tool (ADR 0014, docs/json-contract.md). Names and ids exactly as in the PNML; deterministic JSON; cached per net, operation, parameters and tool version."

issue "Generic operation runner and operations catalog (GET /v1/nets/{id}/operations)" "api,static-analysis" "$M4" \
"$OP_NOTE

Shared mechanics for every analysis and transformation, so that each operation stays small.

**Acceptance criteria**
- Runner handling engine dispatch (\`engine: auto\` or explicit, only engines declaring the
  operation), limits, caching, job and lease for slow operations (200 if quick, 202 with a job
  otherwise), the result envelope.
- Catalog endpoint listing operations, parameters, result type, available engines and, for a
  reduction, the preserved properties.
- Contract test: every registered operation has a route, a request and a result model and a
  known-answer test; a test net with a deliberately slow operation checks the 202 path."

issue "Analysis: p-invariants (POST /v1/nets/{id}/analyses/p-invariants)" "api,static-analysis" "$M4" \
"$OP_NOTE

Minimal-support P-invariants as weighted ElementRef lists.

**Acceptance criteria**
- One route, one request model, one result model; does only this analysis (ADR 0014).
- Served by any engine declaring the operation \`p-invariants\`; result envelope names the tool and version.
- Known-answer tests on: mutex (lock place invariant), producer/consumer, philosophers."

issue "Analysis: t-invariants (POST /v1/nets/{id}/analyses/t-invariants)" "api,static-analysis" "$M4" \
"$OP_NOTE

Minimal-support T-invariants (cycles that return to the same marking).

**Acceptance criteria**
- One route, one request model, one result model; does only this analysis (ADR 0014).
- Served by any engine declaring the operation \`t-invariants\`; result envelope names the tool and version.
- Known-answer tests on: producer/consumer, philosophers."

issue "Analysis: place-bounds (POST /v1/nets/{id}/analyses/place-bounds)" "api,static-analysis" "$M4" \
"$OP_NOTE

Structural and computed bound of each place, as Bound (finite, unbounded, unknown).

**Acceptance criteria**
- One route, one request model, one result model; does only this analysis (ADR 0014).
- Served by any engine declaring the operation \`place-bounds\`; result envelope names the tool and version.
- Known-answer tests on: a bounded and an unbounded net."

issue "Analysis: minimal-siphons (POST /v1/nets/{id}/analyses/minimal-siphons)" "api,static-analysis" "$M4" \
"$OP_NOTE

Minimal siphons as sets of places; documented size limits and timeouts.

**Acceptance criteria**
- One route, one request model, one result model; does only this analysis (ADR 0014).
- Served by any engine declaring the operation \`minimal-siphons\`; result envelope names the tool and version.
- Known-answer tests on: philosophers (known siphons)."

issue "Analysis: minimal-traps (POST /v1/nets/{id}/analyses/minimal-traps)" "api,static-analysis" "$M4" \
"$OP_NOTE

Minimal traps as sets of places.

**Acceptance criteria**
- One route, one request model, one result model; does only this analysis (ADR 0014).
- Served by any engine declaring the operation \`minimal-traps\`; result envelope names the tool and version.
- Known-answer tests on: philosophers (known traps)."

issue "Analysis: dead-transitions (POST /v1/nets/{id}/analyses/dead-transitions)" "api,static-analysis" "$M4" \
"$OP_NOTE

Transitions that can never fire, when decided structurally; undecided ones are not listed as dead.

**Acceptance criteria**
- One route, one request model, one result model; does only this analysis (ADR 0014).
- Served by any engine declaring the operation \`dead-transitions\`; result envelope names the tool and version.
- Known-answer tests on: a net with a dead transition."

issue "Analysis: net-class (POST /v1/nets/{id}/analyses/net-class)" "api,static-analysis" "$M4" \
"$OP_NOTE

Classification flags: state machine, marked graph, free choice, extended free choice, workflow-like.

**Acceptance criteria**
- One route, one request model, one result model; does only this analysis (ADR 0014).
- Served by any engine declaring the operation \`net-class\`; result envelope names the tool and version.
- Known-answer tests on: one net per class."

issue "Analysis: conflict-sets (POST /v1/nets/{id}/analyses/conflict-sets)" "api,static-analysis" "$M4" \
"$OP_NOTE

Groups of transitions in structural conflict.

**Acceptance criteria**
- One route, one request model, one result model; does only this analysis (ADR 0014).
- Served by any engine declaring the operation \`conflict-sets\`; result envelope names the tool and version.
- Known-answer tests on: philosophers."

issue "Analysis: connected-components (POST /v1/nets/{id}/analyses/connected-components)" "api,static-analysis" "$M4" \
"$OP_NOTE

Connected components of the net as ElementRef lists.

**Acceptance criteria**
- One route, one request model, one result model; does only this analysis (ADR 0014).
- Served by any engine declaring the operation \`connected-components\`; result envelope names the tool and version.
- Known-answer tests on: a net made of two disjoint parts."

issue "Analysis engine: native analysis tool for structural operations (container, envelope)" "engine,static-analysis" "$M4" \
"$OP_NOTE

**Acceptance criteria**
- Image implementing the analysis operations above under the engine contract (\`kind: analysis\`,
  \`operation\`), with a pinned tool version (for example Tina or an equivalent library).
- Registered with the list of operations it declares."

issue "Compact analysis summary for the LLM" "static-analysis,llm" "$M4" \
"The LLM must never receive the raw net of a large model, and never any PNML (ADR 0013).

**Acceptance criteria**
- Size-bounded summary (configurable token budget): named invariants, components, interfaces,
  cycles, categories (small/medium/large) rather than raw numbers.
- Test: a net with 100,000 places yields a summary under the budget."

issue "Reductions: common mechanism (new net, mapping, protected elements)" "reduction,api" "$M4" \
"$OP_NOTE

Every reduction rule has its own endpoint and applies one rule; this issue builds what they share.

**Acceptance criteria**
- Request: \`protected\` element ids and optional \`max_applications\`; rule applied to a fixpoint
  otherwise. A protected element is never removed or merged (domain rule 3), tested per rule.
- Result: \`changed\`, \`parent_id\`, \`new_net_id\`, \`applications\`, removed and merged elements,
  preserved properties. Nothing applicable gives \`changed: false\` and creates no net.
- Reduced net stored as a new immutable net with \`parent_id\` (ADR 0005); same request, same
  reduced net (idempotent); the reduced net never reaches the LLM.
- Reductions are never combined in one request: composition is the caller's job."

issue "Reduction: fuse-series-places (POST /v1/nets/{id}/reductions/fuse-series-places)" "reduction,api" "$M4" \
"$OP_NOTE

Fuse places in series (a chain through a single transition). Preserves: reachability of protected places, deadlock freedom.

**Acceptance criteria**
- One route, one request model, one result model; applies only this rule (ADR 0014).
- Applicability conditions and preserved properties documented with a reference, and listed in
  the operations catalog.
- Tests: a net where the rule applies (known reduced net), one where it does not
  (\`changed: false\`), protected elements untouched, counterexample replays on the original."

issue "Reduction: fuse-series-transitions (POST /v1/nets/{id}/reductions/fuse-series-transitions)" "reduction,api" "$M4" \
"$OP_NOTE

Fuse transitions in series. Preserves: reachability of protected places, deadlock freedom.

**Acceptance criteria**
- One route, one request model, one result model; applies only this rule (ADR 0014).
- Applicability conditions and preserved properties documented with a reference, and listed in
  the operations catalog.
- Tests: a net where the rule applies (known reduced net), one where it does not
  (\`changed: false\`), protected elements untouched, counterexample replays on the original."

issue "Reduction: fuse-parallel-places (POST /v1/nets/{id}/reductions/fuse-parallel-places)" "reduction,api" "$M4" \
"$OP_NOTE

Fuse places with identical pre- and post-sets. Preserves: reachability of protected places.

**Acceptance criteria**
- One route, one request model, one result model; applies only this rule (ADR 0014).
- Applicability conditions and preserved properties documented with a reference, and listed in
  the operations catalog.
- Tests: a net where the rule applies (known reduced net), one where it does not
  (\`changed: false\`), protected elements untouched, counterexample replays on the original."

issue "Reduction: fuse-parallel-transitions (POST /v1/nets/{id}/reductions/fuse-parallel-transitions)" "reduction,api" "$M4" \
"$OP_NOTE

Fuse transitions with identical pre- and post-sets. Preserves: reachability, deadlock freedom.

**Acceptance criteria**
- One route, one request model, one result model; applies only this rule (ADR 0014).
- Applicability conditions and preserved properties documented with a reference, and listed in
  the operations catalog.
- Tests: a net where the rule applies (known reduced net), one where it does not
  (\`changed: false\`), protected elements untouched, counterexample replays on the original."

issue "Reduction: remove-self-loop-transitions (POST /v1/nets/{id}/reductions/remove-self-loop-transitions)" "reduction,api" "$M4" \
"$OP_NOTE

Remove transitions that neither consume nor produce a net token change. Preserves: reachability (not liveness).

**Acceptance criteria**
- One route, one request model, one result model; applies only this rule (ADR 0014).
- Applicability conditions and preserved properties documented with a reference, and listed in
  the operations catalog.
- Tests: a net where the rule applies (known reduced net), one where it does not
  (\`changed: false\`), protected elements untouched, counterexample replays on the original."

issue "Reduction: remove-implicit-places (POST /v1/nets/{id}/reductions/remove-implicit-places)" "reduction,api" "$M4" \
"$OP_NOTE

Remove places whose marking is implied by others. Preserves: reachability of protected places, deadlock freedom.

**Acceptance criteria**
- One route, one request model, one result model; applies only this rule (ADR 0014).
- Applicability conditions and preserved properties documented with a reference, and listed in
  the operations catalog.
- Tests: a net where the rule applies (known reduced net), one where it does not
  (\`changed: false\`), protected elements untouched, counterexample replays on the original."

issue "Reduction: remove-dead-transitions (POST /v1/nets/{id}/reductions/remove-dead-transitions)" "reduction,api" "$M4" \
"$OP_NOTE

Remove transitions that can never fire. Preserves: all properties on the remaining net.

**Acceptance criteria**
- One route, one request model, one result model; applies only this rule (ADR 0014).
- Applicability conditions and preserved properties documented with a reference, and listed in
  the operations catalog.
- Tests: a net where the rule applies (known reduced net), one where it does not
  (\`changed: false\`), protected elements untouched, counterexample replays on the original."

issue "Reduction: pre-agglomeration (POST /v1/nets/{id}/reductions/pre-agglomeration)" "reduction,api" "$M4" \
"$OP_NOTE

Agglomerate a place with its output transitions (Berthelot). Preserves: reachability of protected places, deadlock freedom.

**Acceptance criteria**
- One route, one request model, one result model; applies only this rule (ADR 0014).
- Applicability conditions and preserved properties documented with a reference, and listed in
  the operations catalog.
- Tests: a net where the rule applies (known reduced net), one where it does not
  (\`changed: false\`), protected elements untouched, counterexample replays on the original."

issue "Reduction: post-agglomeration (POST /v1/nets/{id}/reductions/post-agglomeration)" "reduction,api" "$M4" \
"$OP_NOTE

Agglomerate a place with its input transitions (Berthelot). Preserves: reachability of protected places, deadlock freedom.

**Acceptance criteria**
- One route, one request model, one result model; applies only this rule (ADR 0014).
- Applicability conditions and preserved properties documented with a reference, and listed in
  the operations catalog.
- Tests: a net where the rule applies (known reduced net), one where it does not
  (\`changed: false\`), protected elements untouched, counterexample replays on the original."

issue "Lift counterexamples from the reduced net back to the original" "reduction,api" "$M4" \
"Uses the element mapping returned by each reduction.

**Acceptance criteria**
- Trace reported on the original net by default; \`?net=reduced\` gives the other view.
- Test: a counterexample found on a reduced net replays successfully on the original."

issue "Option reduce:true in /checks (engine-internal reduction)" "reduction,engine" "$M4" \
"Simple alternative: let ITS-Tools or another engine reduce internally, taking the formula into
account.

**Acceptance criteria**
- Option documented; identical verdicts with and without \`reduce\` on the test cases.
- LTL with neXt covered (stutter sensitivity)."

# ---------------------------------------------------------- M5 - Tool selection (equivalent tools)
issue "Capability registry: which tool answers which property class" "tool-selection,engine,api" "$M5" \
"Foundation for choosing among tools.

**Acceptance criteria**
- For each engine: examination categories, formula classes (LTL with/without neXt, CTL,
  reachability by cardinality/fireability, bounds, deadlock, state space), P/T and colored
  support, resource model (sequential/parallel), known limitations.
- \`GET /v1/engines/capabilities\` and a query \`GET /v1/engines?can_check=<class>&colored=<bool>\`.
- Capabilities cross-checked against the MCC categories each tool entered."

issue "Define equivalence classes of tools per property" "tool-selection,docs" "$M5" \
"Two tools are interchangeable for a property only if they implement the same semantics.

**Acceptance criteria**
- Written definition of \"equivalent for a formula class\" (same semantics, same verdict domain,
  same net type), with known semantic differences documented (e.g. handling of neXt, deadlock
  conventions, bound definitions).
- Machine-readable equivalence table used by the selector.
- Review by someone from the MCC community if possible."

issue "Cross-tool disagreement detection" "tool-selection,engine" "$M5" \
"When equivalent tools return TRUE and FALSE for the same property, something is wrong
(tool bug, adapter bug or semantic mismatch).

**Acceptance criteria**
- Portfolio runs compare definitive verdicts; contradictions are reported as a distinct status and
  never silently resolved.
- Contradictions are stored with all evidence (versions, traces) for triage.
- A counterexample, when available, is replayed to arbitrate FALSE verdicts."

issue "Feature extraction for tool selection" "tool-selection,static-analysis" "$M5" \
"**Acceptance criteria**
- Feature vector per (net, formula): size, net class, invariant coverage, reduction ratio,
  colored or not, domain sizes, formula class and depth, resource limits.
- Computed from the static-analysis endpoints and stored, versioned (feature set version)."

issue "Performance predictor trained on historical MCC results" "tool-selection,bench" "$M5" \
"A classical model (decision tree / random forest) predicts, per equivalent tool, the probability
of a definitive answer within the limits and the expected time.

**Acceptance criteria**
- Trained on the imported MCC results and the features above.
- Cross-validation **by model family**; baselines: single best tool and always-same-tool.
- Reports the gap to the virtual best tool (oracle choosing the best tool per instance)."

issue "POST /v1/select-tools: ranked equivalent tools with rationale" "tool-selection,api" "$M5" \
"**Acceptance criteria**
- Input: net, formula(s), limits. Output: ranked list of **equivalent** tools with predicted
  success probability and time, plus a short rationale.
- Only tools that are available and support the net type are returned.
- Falls back to a static preference order when the predictor is not available."

issue "Portfolio executor: run top-k tools in parallel" "tool-selection,engine,infra" "$M5" \
"**Acceptance criteria**
- Run the top-k tools in parallel under a shared resource budget; first definitive verdict wins;
  the others are cancelled (containers killed).
- All verdicts collected for disagreement detection when budget allows (configurable).
- \`engine: \"auto\"\` in \`/checks\` uses selector + portfolio."

issue "LLM layer for tool selection: explanation and fallback strategy" "tool-selection,llm" "$M5" \
"**Acceptance criteria**
- The LLM explains the choice in plain language and decides the next move after TIMEOUT,
  OOM or UNKNOWN (other tool, reduce first, simpler property, weaker property).
- Ranking itself comes from the predictor; the LLM cannot override capability constraints.
- Decisions logged with their inputs for later analysis."

issue "Evaluation of tool selection (single best, selector, virtual best)" "tool-selection,bench" "$M5" \
"**Acceptance criteria**
- Compare: single best tool, trained selector, portfolio of top-k, virtual best tool.
- Metrics: solved instances, PAR-2 score or equivalent, wall-clock time, resource usage.
- Splits by model family; results reproducible from stored data and pinned versions."

# ------------------------------------------------------------------------------- M5 - LLM agent
issue "Tool contract for the LLM (OpenAPI / MCP server)" "llm,api" "$M5" \
"**Acceptance criteria**
- Tool specification generated from the OpenAPI (or an MCP facade) for the catalog of
  \`docs/json-contract.md\`: inspect, one tool per analysis and per reduction rule (ADR 0014),
  validate, check, replay, select-tools.
- No tool returns the net itself in any format (guard test, ADR 0013, ADR 0015).
- Descriptions written for an LLM (when to use each tool, what UNKNOWN means)."

issue "Agent loop: propose, filter, verify, interpret" "llm" "$M5" \
"**Acceptance criteria**
- Configurable call and time budgets; clean stop.
- On a counterexample: classify as model bug / property too strong / expected behaviour.
- Complete log (property, origin, verdict, engine, version) exportable as JSON."

issue "Automatic filters: vacuity and properties implied by invariants" "llm,static-analysis" "$M5" \
"LLMs readily propose trivial properties that pass.

**Acceptance criteria**
- Detection of vacuously false antecedents and of properties implied by P-invariants.
- Filtered properties are reported (warning), not silently dropped."

issue "Specification patterns (absence, response, precedence, bounds, exclusion)" "llm" "$M5" \
"**Acceptance criteria**
- Library of patterns instantiable with place/transition names.
- The LLM picks a pattern and its parameters; the formula is generated deterministically."

# ------------------------------------------------------------------------------- M6 - Evaluation
EVAL_NOTE="Part of the evaluation protocol (docs/objective.md, docs/evaluation.md, ADR 0012). Deterministic judge, family-level analysis, budget parity."

issue "Review and accept the objective, evaluation protocol and ADR 0012" "bench,docs" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Claims C1-C6, conditions, measures and provisional thresholds discussed and amended.
- Decide the primary outcome, the target number of test families and who rates (experts, users)."

issue "Baseline B0: rule-based property generator (no LLM)" "bench,static-analysis" "$M6" \
"$EVAL_NOTE The baseline the LLM must beat; a weak baseline makes the study meaningless.

**Acceptance criteria**
- Deadlock freedom, per-place boundedness, per-transition quasi-liveness, invariant-based
  exclusions, home-state candidates; same output format and budget as the LLM conditions.
- Reviewed by a second person; documented in \`bench/\`."

issue "Soundness audit of session logs (M1) and known-verdict suite" "bench,quality,engine" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Script that fails when a verdict has no engine result behind it, or when UNKNOWN, TIMEOUT,
  OOM or ERROR is presented as a verdict.
- Disagreements between equivalent tools are listed in the report, never resolved silently."

issue "Fidelity audit (M2): formula versus plain-language gloss" "bench,llm" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Random sample, two blind raters, rating guide, agreement (Cohen's kappa) reported.
- Disagreements adjudicated and listed; fidelity errors classified (scope, next-state, bounds)."

issue "Mutation pipeline (M5, M6): operators, decided versus undecided mutants" "bench" "$M6" \
"Objective measure of relevance: how many injected faults do the properties detect?

$EVAL_NOTE

**Acceptance criteria**
- Operators: arc removed or added, weight changed, initial marking changed, transition removed.
- A property kills a mutant when its verdict differs from the original's; counterexamples are
  replayed on the mutant (M6). Undecided mutants are counted separately.
- Mutation score per property set and per family; runs under the same budget as all conditions."

issue "Non-triviality filters as measures (M4)" "bench,static-analysis" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Share of vacuous properties and of properties implied by invariants, per condition.
- Same filters as the product ones (M5 backlog), reused and not duplicated."

issue "Experiment runner: conditions B0, L1, L2, L3 and N with budget parity" "bench,llm" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Run a condition on a family set with k repetitions; non-interactive mode with questions
  answered by a fixed \"no answer available\".
- Records model id, prompt hash, tool versions, seeds, budgets, git commit; sessions stored as
  event logs and replayable."

issue "Name obfuscation control (condition N)" "bench" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Deterministic renaming of places and transitions with a mapping, applied before the LLM sees the
  net; results mapped back for judging."

issue "Dataset selection and freeze: dev and test families, public and unpublished models" "bench,mcc-data" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Dev and test family lists with the selection rule; unpublished and synthetic models included
  and reported separately (contamination).
- Git tag \`eval-freeze-N\` with protocol, thresholds, families and code versions."

issue "Analysis script: family-level bootstrap, Holm correction, per-family tables" "bench" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Paired differences by family, 95 % bootstrap intervals over families, Holm correction for
  secondary tests, per-family tables; identical script on dev and test."

issue "Blind expert rating protocol and tool (M8)" "bench" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Randomized, condition-hidden rating sheets (1 to 5 and keep or drop); at least two raters;
  agreement reported."

issue "User study protocol for the chat workflow (M10)" "bench,ui" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Tasks, consent and data handling (ADR 0011 retention), measures: time to first useful verified
  property, questions asked, correct reading of UNKNOWN and TIMEOUT.
- Descriptive reporting only; no generalization claimed."

issue "Report template with deviations and negative results" "bench,docs" "$M6" \
"$EVAL_NOTE

**Acceptance criteria**
- Template listing each claim, its measure, threshold, outcome, deviations from the frozen
  protocol, and \`bench/results/NEGATIVE.md\` entries."

issue "Documentation: add-an-engine guide" "docs" "$M2" \
"**Acceptance criteria**
- Step-by-step guide: Dockerfile, adapter, known-verdict tests, registry entry.
- Review of \`docs/engine-contract.md\` based on the experience of the first integrations."

issue "Security review of container launching" "security,infra" "$M1" \
"Mounting the Docker socket gives near-root access to the host.

**Acceptance criteria**
- Documented risk analysis; alternative evaluated (rootless Podman, dedicated worker host).
- PNML size limit and job duration limits verified by tests."

# ------------------------------------------------------------------------------- M7 - Exploration
# Hypotheses described in docs/exploration.md. Each one states what judges the LLM output and the
# metric to beat; none is merged into the default path without a measured gain over the baseline.
EXPL_NOTE="Research direction from \`docs/exploration.md\`: a hypothesis to test, not a committed feature. The LLM may be wrong but must never be the last word: a deterministic judge decides."

issue "Exploration charter: rules, baselines and negative-results log" "exploration,docs,bench" "$M7" \
"$EXPL_NOTE

**Acceptance criteria**
- Template for an experiment: hypothesis, judge, baseline (including structural analysis alone and
  random/greedy search), metric chosen **before** running, budget, model families used.
- \`bench/experiments/\` with one record per run: tool versions, LLM version, data, result,
  including negative results.
- Rule documented: nothing merges into the default path without a measured gain over baseline."

issue "Explore: LLM-guided counterexample hunting with replay as judge" "exploration,llm" "$M7" \
"$EXPL_NOTE

**Hypothesis**: LLM-proposed firing sequences find counterexamples that random walks miss, at
equal budget.

**Acceptance criteria**
- Prompt + harness: LLM proposes a firing sequence; \`/replay\` checks it against the property.
- Compared with random walk and a greedy heuristic on MCC instances where a tool finds a
  counterexample; report hit rate and cost.
- Write-up of where it helps (net size, structure) and where it does not.

**Depends on**: counterexample replay, MCC import."

issue "Explore: conjecture-refutation loop and surprising false beliefs" "exploration,llm" "$M7" \
"$EXPL_NOTE

**Hypothesis**: plausible-but-false conjectures localize modeling errors better than the list of
verified properties.

**Acceptance criteria**
- Loop: conjecture -> refutation attempt by an engine -> refined conjecture; budgeted.
- Each refuted conjecture is stored with a plausibility score assigned **before** it is checked.
- Evaluated on mutated models: do high-plausibility refutations point at the injected fault?"

issue "Explore: LLM-proposed invariants as certificates for hard reachability" "exploration,llm,static-analysis" "$M7" \
"$EXPL_NOTE

**Hypothesis**: LLM-suggested helper invariants make some instances solvable that the engine
alone (and the structural analysis alone) leave unsolved.

**Acceptance criteria**
- Candidate invariants checked for inductiveness by a deterministic checker; only valid ones are
  passed to the engine.
- Measured on MCC reachability instances unsolved by smpt or ITS-Tools: count the **extra**
  instances solved compared with invariants from structural analysis.
- Failure modes catalogued (invalid, valid but useless, valid and helpful)."

issue "Explore: lemma decomposition for UNKNOWN / TIMEOUT results" "exploration,llm" "$M7" \
"$EXPL_NOTE

**Hypothesis**: splitting a hard property into checkable lemmas solves some instances that time
out as a whole.

**Acceptance criteria**
- LLM proposes lemmas and assumptions; each lemma is checked by an engine.
- A deterministic procedure checks that the lemmas imply the goal, and **rejects circular
  assumptions**. The LLM never argues the composition.
- Evaluated on nets with a known component structure."

issue "Explore: adversarial and metamorphic testing of the engines" "exploration,engine,bench" "$M7" \
"$EXPL_NOTE

**Hypothesis**: LLM-designed corner cases and metamorphic relations expose real discrepancies
between tools, or between a tool and an adapter.

**Acceptance criteria**
- Generator of tricky nets/formulas (neXt, weights, self-loops, zero markings, deadlock
  conventions) and a library of metamorphic relations (rename, add an unobserved place, split a
  transition, apply a property-preserving reduction).
- Discrepancies triaged into: adapter bug, tool bug, documented semantic difference.
- Confirmed tool bugs reported to the authors.

**Depends on**: at least two integrated engines, equivalence table, disagreement detection."

issue "Explore: detecting discrepancies between a model and its textual description" "exploration,llm,mcc-data" "$M7" \
"$EXPL_NOTE

**Hypothesis**: stating expectations from the description and checking them detects injected
modeling faults better than description-free property generation.

**Acceptance criteria**
- Fault injection (mutation operators) on models that have a description.
- Detection rate with and without the description, same budgets.
- Ambiguous descriptions flagged rather than guessed at."

issue "Explore: catalog of concurrency pathologies as property generators" "exploration,llm" "$M7" \
"$EXPL_NOTE

**Hypothesis**: instantiating a catalog of classic pathologies (lost wakeup, circular wait,
priority inversion, starvation, missing release, double acquire) finds more injected faults than
unguided generation.

**Acceptance criteria**
- Catalog with property templates; the LLM maps net fragments to patterns.
- Compared with unguided generation on mutants that inject exactly those pathologies.
- Report where recognition from names fails (unnamed or generated nets)."

issue "Explore: counterexample-driven model repair with a regression guard" "exploration,llm" "$M7" \
"$EXPL_NOTE

**Hypothesis**: an LLM can propose minimal edits that make a failing property hold without
breaking the rest.

**Acceptance criteria**
- Repair accepted only if the target property holds, **all previously proven properties still
  hold** and liveness is preserved (no trivial repair that disables behavior).
- Edit distance recorded; evaluated on mutants of known-good models (does it recover the
  original behavior?)."

issue "Explore: synthesizing benchmark families that separate tools" "exploration,bench,tool-selection" "$M7" \
"$EXPL_NOTE

**Hypothesis**: LLM-generated scalable families can be made hard for one tool and easy for
another, giving useful training data for the selector and candidate MCC submissions.

**Acceptance criteria**
- Generator of parameterized families; measured time ratio between best and worst tool.
- Families clearly labelled synthetic; compared with existing MCC families for representativeness.
- Check whether adding them improves the selector on held-out **real** families."

issue "Explore: natural-language what-if with machine-readable property diff" "exploration,llm,api" "$M7" \
"$EXPL_NOTE

**Hypothesis**: what-if questions are best answered by a mutation plus a diff of verified
properties between original and variant.

**Acceptance criteria**
- A what-if request becomes a net mutation (new net, linked to its parent); the same property set
  is checked on both.
- The response always includes the machine-readable diff next to the explanation.
- Natural-language summaries checked against the diff on a sample."


# --------------------------------------------------------------------------- M8 - Text chat workflow
CHAT_NOTE="Part of the text-only chat workflow (docs/adr/0008-0010). No graphical display of the net: place and transition names are quoted as text."

issue "Review and accept ADRs 0008-0010 (events, LLM port, text UI)" "docs,llm,api" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- The three proposed ADRs are discussed, amended and accepted (or replaced) before code starts.
- The event vocabulary and its provenance rule are frozen for the first version."

issue "Net descriptions: model, storage and endpoints" "storage,api" "$M8" \
"$CHAT_NOTE Implements ADR 0011.

**Acceptance criteria**
- Immutable, content-addressed \`Description\` model; link to a net with an origin
  (\`user\`, \`mcc\`, \`llm\`); port and SQLite adapter.
- \`POST /v1/nets/{net_id}/descriptions\` (idempotent), \`GET\` list and by id; size limit in
  Settings; text stored exactly as sent (UTF-8).
- Unknown net gives 404; oversized text gives 413; tests for idempotence and for several
  descriptions on one net."

issue "Session and event domain models" "llm,api" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- Frozen pydantic models for sessions and every event kind, discriminated by \`kind\`.
- A verdict event cannot be built without a reference to an engine result (ADR 0006).
- Serialization round-trip tests for each kind."

issue "Persist sessions and events in SQLite (ordered, resumable)" "storage,api" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- \`SessionRepository\` port and SQLite adapter; strictly increasing event numbers per session,
  safe with several processes.
- Reading events after a given number (for resumption).
- Tests with two store instances on one file."

issue "LlmGateway port and scripted fake" "llm" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- Port in \`application/ports.py\`; scripted fake used by all agent tests.
- Import-linter contract: only the provider adapter imports the provider SDK."

issue "Tool facade for the agent (net summary, analysis, check, job)" "llm,api" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- Tool specifications generated from the use cases of \`docs/json-contract.md\`, with descriptions
  written for an LLM (what UNKNOWN, TIMEOUT and OOM mean).
- Guard test: no tool offered to the LLM can return a net in any format, and no result contains one.
- Arguments validated like API requests; unknown tools and bad arguments become events, not crashes."

issue "Agent run as a leased job with budgets and cancellation" "llm,api" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- The run is claimed atomically, renews its lease, resumes or ends cleanly after a crash.
- Budgets (steps, tool calls, tokens, wall time) in Settings; \`budget_exhausted\` event on stop.
- Cancelling a session stops the run and its engine jobs."

issue "Agent can ask the user a question and resume on the answer" "llm,api" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- \`question\` event puts the session in \`waiting_for_user\`; \`answer\` resumes it, from any process.
- Unanswered questions do not consume budget; configurable idle expiry."

issue "Provenance rule: verdicts shown only from engine results" "llm,api,quality" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- Assistant text is labelled as LLM-written; verdicts come only from verdict events.
- Test: a scripted LLM claiming a result that no engine produced never yields a verdict event.
- UNKNOWN, TIMEOUT, OOM and ERROR are never presented as FALSE."

issue "Session inputs: net, system description and goal" "llm,api" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- \`session_started\` event records net id, description (free text) and goal; description is
  optional, size-limited, stored with the session and never attached to the (immutable) net.
- Multipart creation: net file (PNML or JSON) plus description (text or \`.txt\`/\`.md\` file) plus goal.
- The agent receives the description as delimited untrusted text next to the static-analysis facts.
- Evaluation hook: a session can be replayed without the description to compare conditions."

issue "Sessions REST endpoints (create, message, answer, cancel)" "api" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- \`POST /v1/sessions\`, \`POST /v1/sessions/{id}/messages\`, \`POST /v1/sessions/{id}/answer\`,
  \`DELETE /v1/sessions/{id}\`; problem+json errors; idempotent where it makes sense.
- Upload of the net (PNML or JSON) with the first message registers it through \`POST /v1/nets\`."

issue "Event stream endpoint (SSE, resumable)" "api" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- \`GET /v1/sessions/{id}/events\` reads from the database, honours \`Last-Event-ID\`, survives
  process changes between reconnections.
- Heartbeat comments; no per-session state in memory."

issue "Anthropic adapter for LlmGateway" "llm,infra" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- Adapter in \`infrastructure/\`; key and model from Settings, never logged or put in events.
- Timeouts, retries with backoff, provider errors mapped to \`session_error\` events.
- One integration test, skipped without a key."

issue "Prompt-injection hardening for net content" "llm,security" "$M8" \
"Place and transition names are attacker-controlled and enter the prompt.

**Acceptance criteria**
- Net content is quoted in delimited blocks and described as data in the system prompt.
- Test corpus of hostile names (instructions, fake tool results, very long names); the agent
  fixtures show no tool misuse, and no secret leaks into events."

issue "Agent context includes the user description, with provenance" "llm" "$M8" \
"$CHAT_NOTE Implements ADR 0011.

**Acceptance criteria**
- The description is given to the agent as quoted untrusted data, labelled with its origin; the
  session log records which description was used.
- The agent may propose a clarified or corrected description (origin \`llm\`), stored only after
  the user accepts it.
- Test: a description containing instructions does not change tool use."

issue "Retention and deletion of user nets, descriptions and sessions" "storage,security" "$M8" \
"User data may be confidential.

**Acceptance criteria**
- Documented retention policy; delete endpoints for sessions and descriptions, and for nets not
  referenced by other users' jobs.
- Deletion removes data from the database file (vacuum) and from logs and reports."

issue "Context management: summaries instead of the whole PNML" "llm" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- The agent receives the net summary and static-analysis facts, and fetches details by tool
  (e.g. neighbours of a named place) on demand.
- Large nets stay within the token budget; truncation is explicit in the event log."

issue "UI project setup: TypeScript, React, Vite, Biome, Vitest, generated API types" "ui,infra" "$M8" \
"$CHAT_NOTE Implements ADR 0010.

**Acceptance criteria**
- \`ui/\` project (Node LTS pinned in \`.nvmrc\`), \`tsc --strict\`, Biome, Vitest; no \`any\`.
- Types generated from the API OpenAPI schema; a script and a CI check fail when they are stale.
- Built files served by the API under \`/ui\`; dev server proxying the API.
- Rules of ADR 0010 written into \`docs/conventions.md\` and \`CLAUDE.md\` before feature code."

issue "UI quality gates: pre-commit hooks and CI job" "ui,quality" "$M8" \
"**Acceptance criteria**
- Biome, \`tsc --noEmit\` and Vitest run in pre-commit (changed UI files) and in CI.
- Coverage measured for the UI with a floor; architecture note added to \`docs/architecture.md\`."

issue "UI: resumable event stream client (fetch-based SSE)" "ui" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- Client that reconnects with \`Last-Event-ID\`, never shows an event twice, shows connection state.
- Events are an exhaustive discriminated union; an unknown kind is displayed as such, not dropped."

issue "UI: start form (net, description, goal) and live event feed" "ui" "$M8" \
"$CHAT_NOTE Implements ADR 0010.

**Acceptance criteria**
- Start form: net upload (PNML or JSON) or drag and drop, system description (typed or text file), goal.
- Before confirming, shows what was understood from the net (name, places, transitions, arcs) and
  server-side validation errors (invalid or oversized net) in plain language.
- Live feed of events; text rendering only (no raw HTML).
- Follow-up messages can add information or files.
- Tool calls and intermediate results collapsed by default, expandable."

issue "UI: questions, answers, cancel and verdict badges" "ui" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- Pending question shown with an input; cancel button.
- Verdicts displayed with engine, version and limits; assistant text visibly distinct from verdicts."

issue "Export a session as a report (Markdown and JSON)" "api,docs" "$M8" \
"$CHAT_NOTE

**Acceptance criteria**
- Properties checked, verdicts with engine and version, open questions, unresolved UNKNOWNs.
- Same content available as JSON for \`bench/\`."

issue "Architecture and conventions update for sessions and the agent" "docs,quality" "$M8" \
"**Acceptance criteria**
- \`docs/architecture.md\` module table, request flow and extension guide updated in the same
  commits as the code (the sync hook enforces the table).
- Import-linter contracts for the new modules."

# --------------------------------------------------------------------------- M9 - Graph display (deferred)
GRAPH_NOTE="Deferred: not started until the text-only chat (M8) has been used on real nets."

issue "Graph display: render a net and highlight elements cited by the assistant" "ui" "$M9" \
"$GRAPH_NOTE

**Acceptance criteria**
- Highlight events carry ids and a note; the server checks that every id exists in the net.
- Neighbourhood view for large nets, with grouping of indexed names."

issue "Graph display: replay a counterexample trace on the original net" "ui" "$M9" \
"$GRAPH_NOTE

**Acceptance criteria**
- Token-game replay of an engine trace; the replay is checked by the API, not by the browser."


# ------------------------------------------------------------------------------ M10 - Publication
PAPER_NOTE="See docs/publication.md for the venue categories and the paper definitions."

issue "Resolve the open points of docs/publication.md (reviewer rules, ACSD, review mode)" "paper,docs" "$M10" \
"$PAPER_NOTE Petri Nets 2027 (Rennes, 21-25 June 2027): abstract 15 January, paper 22 January.

**Acceptance criteria**
- Review mode, LLM-use and artifact policies, notification dates read from EasyChair or the
  organizers; every item marked *to check* resolved.
- ACSD 2027: existence, dates, paper types and overlap rules found; decide Petri Nets or ACSD for
  each paper.
- Decide which papers (A to F) to target before the abstract deadline."

issue "Paper A (tool): reviewer access plan and replay mode" "paper,api" "$M10" \
"$PAPER_NOTE Reviewers must access the tool free of charge, without a paid LLM key.

**Acceptance criteria**
- Replay mode serving recorded sessions from event logs; scripted fake LLM for a keyless demo.
- One-command installation, stable demonstration scenario, open-source licence chosen."

issue "Paper A (tool): 10-page tool paper and demonstration" "paper,docs" "$M10" \
"$PAPER_NOTE

**Acceptance criteria**
- Paper in LNCS tool format; architecture, soundness guarantees (C1), demonstration scenario.
- Tool Exhibition script (what to show in a few minutes to a small group)."

issue "Paper C (formalization fidelity): benchmark and error taxonomy" "paper,bench,llm" "$M10" \
"$PAPER_NOTE

**Acceptance criteria**
- Translation benchmark (plain language to MCC formula syntax), engines as judge, blind raters,
  taxonomy of fidelity errors; dataset released with the paper."

issue "Paper B (main study): write-up from the frozen protocol" "paper,bench" "$M10" \
"$PAPER_NOTE

**Acceptance criteria**
- Written only after the \`eval-freeze-N\` test run; deviations and negative results included."

issue "Paper D (experience report): real-model case studies" "paper,bench" "$M10" \
"$PAPER_NOTE

**Acceptance criteria**
- Real nets with owners' consent (ADR 0011 retention); faults found; honest lessons."

issue "Paper E (tool integration): disagreement catalogue and root causes" "paper,engine" "$M10" \
"$PAPER_NOTE

**Acceptance criteria**
- Every disagreement between equivalent tools logged with net, formula, tool versions and cause."

issue "Paper F (tool selection): benchmark write-up" "paper,tool-selection" "$M10" \
"$PAPER_NOTE

**Acceptance criteria**
- Regret against the single best and the virtual best tool, cross-validated by family."

# =================================================================================================

echo
if [[ $DRY_RUN -eq 1 ]]; then
  echo "Dry run finished: $CREATED issue(s) would be created."
else
  echo "Done: $CREATED created, $SKIPPED already existing."
fi
