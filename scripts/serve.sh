#!/usr/bin/env bash
# LAN 접근 가능한 서버 실행 (모바일/외부 접속용)
#
# 사용법:
#   AUTH_USER=admin AUTH_PASS=yourpw ./scripts/serve.sh
#
# Basic Auth를 활성화하려면 AUTH_USER와 AUTH_PASS를 환경변수로 지정하세요.
# 미설정 시 인증 없이 실행됩니다 (개발/테스트용).
set -euo pipefail

HOST="${HOST:-0.0.0.0}" PORT="${PORT:-8010}" exec "$(dirname "${BASH_SOURCE[0]}")/run_dev.sh"
