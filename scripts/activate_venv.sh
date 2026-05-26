#!/usr/bin/env bash

if [ -n "${BASH_SOURCE:-}" ]; then
  SCRIPT_PATH="${BASH_SOURCE[0]}"
else
  SCRIPT_PATH="${(%):-%x}"
fi

ROOT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")/.." && pwd)"
"${ROOT_DIR}/scripts/bootstrap_venv.sh" >/dev/null

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "Run this with source so it can activate your current shell:"
  echo "source ${ROOT_DIR}/scripts/activate_venv.sh"
  exit 0
fi

source "${ROOT_DIR}/.venv/bin/activate"
