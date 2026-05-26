#!/usr/bin/env bash
# ============================================================
# Document Translate Agent — 서비스 제어 스크립트
# 사용법: ./scripts/app.sh [start|stop|restart|status|logs|open]
# ============================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="${ROOT_DIR}/.server.pid"
LOG_FILE="${ROOT_DIR}/.server.log"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8010}"
URL="http://${HOST}:${PORT}"

# ----- 색상 -----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ----- Python 경로 확인 -----
get_python() {
  local py
  py="$("${ROOT_DIR}/scripts/bootstrap_venv.sh")"
  echo "$py"
}

# ----- 실행 중 여부 -----
is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

# ============================================================
cmd="${1:-status}"

case "$cmd" in

  # ── start ────────────────────────────────────────────────
  start)
    if is_running; then
      PID=$(cat "$PID_FILE")
      warn "이미 실행 중입니다  (PID: $PID)  →  $URL"
      exit 0
    fi

    info "서버를 시작합니다..."
    PYTHON="$(get_python)"
    cd "$ROOT_DIR"

    nohup "${PYTHON}" -m uvicorn app.main:app \
      --host "$HOST" --port "$PORT" \
      >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    # 최대 5초 대기하며 기동 확인
    for i in 1 2 3 4 5; do
      sleep 1
      if is_running; then
        PID=$(cat "$PID_FILE")
        success "서버 시작 완료  (PID: $PID)  →  $URL"
        exit 0
      fi
    done

    error "서버 기동 실패. 로그를 확인하세요:"
    error "  tail -f $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
    ;;

  # ── stop ─────────────────────────────────────────────────
  stop)
    if ! is_running; then
      if [[ -f "$PID_FILE" ]]; then
        warn "프로세스가 이미 종료되어 있습니다. PID 파일을 삭제합니다."
        rm -f "$PID_FILE"
      else
        warn "실행 중인 서버가 없습니다."
      fi
      exit 0
    fi

    PID=$(cat "$PID_FILE")
    info "서버를 중지합니다  (PID: $PID)..."
    kill "$PID"

    # 최대 5초 대기
    for i in 1 2 3 4 5; do
      sleep 1
      if ! kill -0 "$PID" 2>/dev/null; then
        rm -f "$PID_FILE"
        success "서버가 중지되었습니다."
        exit 0
      fi
    done

    warn "정상 종료가 지연됩니다. 강제 종료합니다..."
    kill -9 "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    success "서버를 강제 종료했습니다."
    ;;

  # ── restart ──────────────────────────────────────────────
  restart)
    info "서버를 재기동합니다..."
    "${BASH_SOURCE[0]}" stop  || true
    sleep 1
    "${BASH_SOURCE[0]}" start
    ;;

  # ── status ───────────────────────────────────────────────
  status)
    if is_running; then
      PID=$(cat "$PID_FILE")
      success "실행 중  (PID: $PID)  →  $URL"
      # 헬스체크
      if command -v curl &>/dev/null; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "${URL}/api/health" 2>/dev/null || echo "000")
        if [[ "$HTTP_CODE" == "200" ]]; then
          success "헬스체크 통과  (HTTP $HTTP_CODE)"
        else
          warn "헬스체크 응답 없음  (HTTP $HTTP_CODE) — 아직 기동 중일 수 있습니다."
        fi
      fi
    else
      if [[ -f "$PID_FILE" ]]; then
        warn "중지됨  (PID 파일 잔존 → 삭제)"
        rm -f "$PID_FILE"
      else
        warn "중지됨"
      fi
    fi
    ;;

  # ── logs ─────────────────────────────────────────────────
  logs)
    if [[ -f "$LOG_FILE" ]]; then
      info "로그 스트리밍 중  (Ctrl+C 로 종료)..."
      tail -f "$LOG_FILE"
    else
      warn "로그 파일이 아직 없습니다: $LOG_FILE"
      warn "서버를 먼저 시작하세요:  ./scripts/app.sh start"
    fi
    ;;

  # ── open ─────────────────────────────────────────────────
  open)
    if ! is_running; then
      info "서버가 중지되어 있습니다. 먼저 시작합니다..."
      "${BASH_SOURCE[0]}" start
    fi
    if command -v open &>/dev/null; then
      open "$URL"
    elif command -v xdg-open &>/dev/null; then
      xdg-open "$URL"
    else
      info "브라우저에서 열어주세요: $URL"
    fi
    ;;

  # ── help ─────────────────────────────────────────────────
  help|--help|-h)
    echo ""
    echo "  Document Translate Agent — 서비스 제어 스크립트"
    echo ""
    echo "  사용법:  ./scripts/app.sh <명령>"
    echo ""
    echo "  명령:"
    echo "    start    서버 시작 (백그라운드)"
    echo "    stop     서버 중지"
    echo "    restart  서버 재기동"
    echo "    status   실행 상태 확인 + 헬스체크"
    echo "    logs     실시간 로그 보기"
    echo "    open     서버 시작 후 브라우저로 열기"
    echo ""
    echo "  환경변수:"
    echo "    HOST   바인딩 주소  (기본: 127.0.0.1)"
    echo "    PORT   포트 번호    (기본: 8010)"
    echo ""
    echo "  예시:"
    echo "    PORT=9000 ./scripts/app.sh start"
    echo "    ./scripts/app.sh open"
    echo "    HOST=0.0.0.0 ./scripts/app.sh start   # 모바일/LAN 접근용"
    echo "    AUTH_USER=admin AUTH_PASS=pw HOST=0.0.0.0 ./scripts/app.sh start"
    echo ""
    ;;

  *)
    error "알 수 없는 명령: $cmd"
    echo "사용법: $0 [start|stop|restart|status|logs|open|help]"
    exit 1
    ;;

esac
