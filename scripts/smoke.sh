#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
exec uv run --offline --no-project --no-python-downloads python tools/smoke.py
