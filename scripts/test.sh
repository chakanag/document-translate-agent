#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$("${ROOT_DIR}/scripts/bootstrap_venv.sh")"

cd "${ROOT_DIR}"
PYTHONPYCACHEPREFIX="${ROOT_DIR}/storage/pycache" "${PYTHON}" -B -m unittest discover -s tests
