#!/usr/bin/env bash
# Build data/boston.sqlite from scratch: download all five Analyze Boston datasets, optionally
# fetch Data Commons area housing data (only when DATACOMMONS_API_KEY is set), then preprocess.
#
# Usage:
#   scripts/build_data.sh                  # uses .venv/bin/python
#   scripts/build_data.sh --python python  # e.g. inside the Docker build
#
# Raw downloads in data/raw/ contain owner names and contact addresses. They are gitignored,
# never copied into the final Docker image, and only whitelisted columns reach boston.sqlite.
set -euo pipefail

PYTHON=".venv/bin/python"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      [[ $# -ge 2 ]] || { echo "--python needs a path" >&2; exit 2; }
      PYTHON="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

# Run from the project root so `-m scripts.*` resolves regardless of the caller's cwd.
cd "$(dirname "$0")/.."

echo "Fetching Analyze Boston datasets with $PYTHON"
"$PYTHON" -m scripts.fetch_boston
# Optional: area housing figures (U.S. Census via Data Commons) for a fixed ZIP list. Runs only
# when the key is set; a failed request skips area housing instead of failing the build.
# The key can come from DATACOMMONS_API_KEY_FILE (the Docker build's secret mount); it is then
# set only for this one command, so no other step sees it.
if [[ -n "${DATACOMMONS_API_KEY_FILE:-}" && -s "${DATACOMMONS_API_KEY_FILE}" ]]; then
  echo "Fetching Data Commons area housing data"
  DATACOMMONS_API_KEY="$(cat "$DATACOMMONS_API_KEY_FILE")" "$PYTHON" -m scripts.fetch_datacommons \
    || echo "Data Commons fetch failed; continuing without area housing data" >&2
elif [[ -n "${DATACOMMONS_API_KEY:-}" || -n "${DATA_COMMONS_API_KEY:-}" ]]; then
  echo "Fetching Data Commons area housing data"
  "$PYTHON" -m scripts.fetch_datacommons || echo "Data Commons fetch failed; continuing without area housing data" >&2
else
  echo "DATACOMMONS_API_KEY not set; skipping Data Commons area housing data"
fi
echo "Preprocessing into data/boston.sqlite"
"$PYTHON" -m scripts.preprocess_boston
