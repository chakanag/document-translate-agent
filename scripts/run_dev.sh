#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$("${ROOT_DIR}/scripts/bootstrap_venv.sh")"

cd "${ROOT_DIR}"
exec "${PYTHON}" -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8010}" --reload
