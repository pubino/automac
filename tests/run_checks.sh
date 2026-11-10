#!/bin/sh
# Lint, format, type, syntax, and test checks. Used by Docker, CI, and scripts/test.sh --local.
set -eu
PY="${PYTHON:-python3}"
"$PY" -m ruff check .
"$PY" -m ruff format --check .
"$PY" -m mypy
for f in examples/zsh/tartvm examples/guest/provision.sh scripts/*.sh; do zsh -n "$f"; done
"$PY" -m pytest
