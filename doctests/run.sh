#!/usr/bin/env bash
#
# Run doctest's own self-documenting tutorials and regenerate their Markdown.
#
# These specs are "inception": doctest specs that drive doctest. Each `run`
# executes a tutorial end-to-end (writing inner specs, running them, asserting on
# the output); each `generate` renders the same spec to Markdown under outputs/.
#
# By default the inner steps build doctest from the published flake. To exercise
# THIS checkout instead, point DOCTEST at it, e.g.:
#   DOCTEST="python3 ../doctest.py" ./run.sh        # direct (needs PyYAML)
#   DOCTEST="nix run ..# --" ./run.sh               # this checkout's flake
#
set -euo pipefail

# Run from this doctests/ directory regardless of where the script is invoked from.
cd "$(dirname "$0")"

# The doctest CLI used to RUN these specs. Override by exporting DOCTEST.
read -r -a DOCTEST <<< "${DOCTEST:-nix run github:logos-co/logos-doctest --}"
OUTPUT_DIR="./outputs"

echo "==> Clearing previous ${OUTPUT_DIR}/"
# A prior run may have copied read-only artifacts here; restore write perms first.
if [ -e "${OUTPUT_DIR}" ]; then
  chmod -R u+w "${OUTPUT_DIR}" 2>/dev/null || true
fi
rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

for spec in *.test.yaml; do
  name="$(basename "${spec%.test.yaml}")"
  echo "==> Running ${spec}"
  "${DOCTEST[@]}" run "${spec}" --verbose --continue-on-fail

  echo "==> Generating ${OUTPUT_DIR}/${name}.md"
  "${DOCTEST[@]}" generate "${spec}" -o "${OUTPUT_DIR}/${name}.md"
done

echo "==> Done. Rendered tutorials are in doctests/${OUTPUT_DIR#./}/"
