#!/usr/bin/env bash
# Mutation testing of the domain and application layers: does the test suite notice a change in
# the code? Usage: scripts/mutation.sh [mutmut pattern]   (default: everything under app/domain
# and app/application; for example "app.domain.canonical*" for one module).
#
# mutmut copies the package to api/mutants; the tests also read docs/ and engines/, so they are
# linked next to it for the run. Prints the counts as JSON (killed, survived, ...).
set -euo pipefail
cd "$(dirname "$0")/../api"
trap 'rm -f docs engines' EXIT
ln -sfn ../docs docs
ln -sfn ../engines engines
mutmut run "${1:-app.*}" || true
mutmut export-cicd-stats >/dev/null
cat mutants/mutmut-cicd-stats.json
