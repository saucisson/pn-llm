# Testing policy

## What we test, and where

| Kind | Folder | What it covers | Speed |
|---|---|---|---|
| Unit | `api/tests/unit/` | One module with its real collaborators (domain, services with the real SQLite store, adapters) | fast |
| API | `api/tests/api/` | Whole application through HTTP (`TestClient`): routes, error mapping, persistence across restarts | fast |
| Integration | `api/tests/integration/` | Real Docker engine images. Marked `docker`; **skipped** when Docker or the image is missing | slow |

## Rules

1. **Every behaviour change comes with a test**, in the same commit. A bug fix starts with a test
   that fails.
2. **Test names say the behaviour** (`test_cancelling_a_finished_job_keeps_its_results`). No
   docstrings needed in tests.
3. **No mocks of our own code.** Use the real objects (the SQLite store in a temporary directory
   is fast enough). Replace only a process boundary: Docker (a fake `DockerRunner` subclass),
   `subprocess`, the clock. Fakes are small classes in the test module, not patched internals.
4. **Safety rules have tests**: UNKNOWN is never FALSE, a failed engine never yields a verdict,
   a request is idempotent across restarts, hostile XML is rejected, containers are launched
   with isolation flags.
5. **Known-verdict tests for every engine**: at least one TRUE and one FALSE per supported syntax
   (added with each engine integration, see `docs/engine-contract.md`).
6. Architecture rules are tests too: domain models must be frozen (`test_models.py`); dependency
   rules are checked by import-linter.
7. Tests are deterministic: no network, no sleeping, no dependence on the clock or on test order.
8. Warnings are errors (`filterwarnings = error`). An unavoidable third-party warning is ignored
   explicitly, with a comment.

## Coverage

- Measured with branch coverage (`pytest --cov`), on `app/` only.
- **Minimum 90 %** (`fail_under` in `api/pyproject.toml`), enforced before push and in CI. The
  target is to stay near the current level; do not lower the threshold, add tests.
- `# pragma: no cover` needs a reason on the same line and is the exception.
- Coverage is a floor, not a goal: a covered line with no assertion proves nothing. Review the
  assertions, not the percentage.

## Running

```bash
make test          # fast tests
make cov           # tests with branch coverage and the threshold
make check         # everything the CI runs
```
