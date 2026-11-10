#!/bin/zsh
# Run the full check suite.
#   scripts/test.sh           in Docker via docker-compose (as CI does)
#   scripts/test.sh --local   in the project .venv (created with uv from uv.lock)
set -euo pipefail
cd "${0:A:h}/.."

case "${1:-}" in
  --local)
    command -v uv >/dev/null || { print -u2 "uv is required: brew install uv"; exit 1; }
    uv sync --frozen --quiet
    PYTHON=.venv/bin/python sh tests/run_checks.sh
    ;;
  "")
    docker-compose build tests
    docker-compose run --rm tests
    ;;
  -h|--help) sed -n '2,4p' "$0" ;;
  *) print -u2 "unknown option: $1"; exit 2 ;;
esac
