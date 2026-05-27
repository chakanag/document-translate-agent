#!/usr/bin/env bash
# ============================================================
# Document Translate Agent — 통합 제어 스크립트
# 사용법: ./ctl.sh <명령> [옵션]
# ============================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="docker compose -f ${ROOT_DIR}/deploy/docker-compose.yml"
APP_CONTAINER="deploy-app-1"
DOMAIN="doc-tr.chakanag.me"

# ── 색상 ─────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
header()  { echo -e "\n${BOLD}$*${NC}"; }

# ── .env 확인 ────────────────────────────────────────────────
check_env() {
  if [[ ! -f "${ROOT_DIR}/deploy/.env" ]]; then
    error ".env 파일이 없습니다."
    echo "  cp ${ROOT_DIR}/deploy/.env.example ${ROOT_DIR}/deploy/.env"
    exit 1
  fi
}

# ── 명령 ─────────────────────────────────────────────────────

cmd_start() {
  check_env
  info "서비스를 시작합니다..."
  $COMPOSE up -d
  sleep 2
  cmd_status
}

cmd_stop() {
  info "서비스를 중지합니다..."
  $COMPOSE down
  ok "중지 완료"
}

cmd_restart() {
  info "서비스를 재시작합니다..."
  $COMPOSE restart
  sleep 2
  cmd_status
}

cmd_build() {
  check_env
  info "Docker 이미지를 빌드합니다..."
  DOCKER_BUILDKIT=0 $COMPOSE build app
  ok "빌드 완료"
}

cmd_pull() {
  header "▶ GitHub에서 최신 코드 가져오기"
  if [[ ! -d "${ROOT_DIR}/.git" ]]; then
    error ".git 디렉토리가 없습니다. git 저장소가 아닙니다."
    exit 1
  fi
  info "git pull origin main..."
  git -C "${ROOT_DIR}" pull origin main
  ok "코드 업데이트 완료"
  echo ""
  # 코드 변경 후 자동으로 재배포
  cmd_deploy
}

cmd_deploy() {
  header "▶ 배포 시작"
  check_env
  info "이미지 빌드 중..."
  DOCKER_BUILDKIT=0 $COMPOSE build app
  info "컨테이너 재시작 중..."
  $COMPOSE up -d --remove-orphans
  # nginx 설정 변경 반영: 항상 재로드
  info "nginx 설정 재로드 중..."
  $COMPOSE exec -T nginx nginx -s reload 2>/dev/null || $COMPOSE restart nginx
  info "헬스체크 대기 중..."
  local ok_flag=0
  for i in $(seq 1 10); do
    sleep 3
    # Docker 내부 헬스체크 상태 확인 (포트 노출 불필요)
    local health
    health=$(docker inspect --format='{{.State.Health.Status}}' "${APP_CONTAINER}" 2>/dev/null || echo "unknown")
    if [[ "$health" == "healthy" ]]; then
      ok "앱 정상 기동 (docker health: ${health})"
      ok_flag=1
      break
    fi
    info "대기 중... ($i/10) [${health}]"
  done
  [[ $ok_flag -eq 0 ]] && warn "헬스체크 응답 없음 — 로그를 확인하세요: ./ctl.sh logs"
  echo ""
  ok "배포 완료 → https://${DOMAIN}"
}

cmd_status() {
  header "▶ 서비스 상태"
  $COMPOSE ps
  echo ""
  info "헬스체크..."
  local health
  health=$(docker inspect --format='{{.State.Health.Status}}' "${APP_CONTAINER}" 2>/dev/null || echo "unknown")
  if [[ "$health" == "healthy" ]]; then
    ok "앱 정상 (docker health: ${health})"
  else
    warn "앱 상태: ${health} — 로그를 확인하세요: ./ctl.sh logs"
  fi
  echo ""
  info "SSL 인증서 만료일..."
  sudo certbot certificates 2>/dev/null | grep -E "(Domains|Expiry)" || echo "  인증서 정보 없음"
}

cmd_logs() {
  local service="${1:-app}"
  local lines="${2:-50}"
  info "${service} 로그 (마지막 ${lines}줄, Ctrl+C로 종료)"
  $COMPOSE logs -f --tail="${lines}" "${service}"
}

cmd_shell() {
  info "앱 컨테이너 내부 접속..."
  docker exec -it "${APP_CONTAINER}" bash
}

cmd_cert_renew() {
  info "SSL 인증서 갱신 중..."
  $COMPOSE stop nginx
  sudo certbot renew --standalone --quiet
  $COMPOSE start nginx
  ok "인증서 갱신 완료"
}

cmd_backup() {
  local backup_dir="${ROOT_DIR}/backup"
  local timestamp
  timestamp=$(date +%Y%m%d_%H%M%S)
  local backup_file="${backup_dir}/storage_${timestamp}.tar.gz"
  mkdir -p "${backup_dir}"
  info "스토리지 백업 중 → ${backup_file}"
  tar -czf "${backup_file}" -C "${ROOT_DIR}" storage/
  ok "백업 완료: $(du -sh "${backup_file}" | cut -f1)"
  # 7일 이상 된 백업 자동 삭제
  find "${backup_dir}" -name "storage_*.tar.gz" -mtime +7 -delete
  info "7일 이상 된 백업 정리 완료"
}

cmd_db() {
  info "SQLite DB 접속..."
  docker exec -it "${APP_CONTAINER}" python3 -c "
import sqlite3, os
db = '/app/storage/jobs.sqlite3'
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
print('테이블 목록:', [r[0] for r in con.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])
print()
users = con.execute('SELECT id, username, role, is_active, created_at FROM users').fetchall()
print(f'유저 수: {len(users)}')
for u in users:
    print(f'  [{u[\"role\"]}] {u[\"username\"]} (active={u[\"is_active\"]})')
jobs = con.execute('SELECT COUNT(*) FROM translation_jobs').fetchone()[0]
print(f'번역 작업 수: {jobs}')
"
}

cmd_help() {
  echo ""
  echo -e "${BOLD}Document Translate Agent — 통합 제어 스크립트${NC}"
  echo ""
  echo -e "  ${BOLD}사용법:${NC} ./ctl.sh <명령> [옵션]"
  echo ""
  echo -e "  ${BOLD}서비스 관리${NC}"
  echo "    start          서비스 시작"
  echo "    stop           서비스 중지"
  echo "    restart        서비스 재시작"
  echo "    pull           GitHub에서 최신 코드 pull + 자동 재배포"
  echo "    deploy         이미지 빌드 + 재시작 (로컬 코드 기준)"
  echo "    build          이미지 빌드만"
  echo "    status         실행 상태 + 헬스체크 + 인증서 만료일"
  echo ""
  echo -e "  ${BOLD}모니터링${NC}"
  echo "    logs [app|nginx] [줄수]   실시간 로그 (기본: app, 50줄)"
  echo "    shell                     앱 컨테이너 bash 접속"
  echo "    db                        DB 유저/작업 현황 확인"
  echo ""
  echo -e "  ${BOLD}유지보수${NC}"
  echo "    cert-renew     SSL 인증서 수동 갱신"
  echo "    backup         storage 디렉토리 백업 (7일 자동 삭제)"
  echo ""
  echo -e "  ${BOLD}예시${NC}"
  echo "    ./ctl.sh pull               # GitHub에서 최신 코드 받아서 재배포"
  echo "    ./ctl.sh deploy             # 로컬 코드 기준으로 재배포"
  echo "    ./ctl.sh logs app 100       # 앱 로그 100줄"
  echo "    ./ctl.sh logs nginx         # nginx 로그"
  echo "    ./ctl.sh backup             # 수동 백업"
  echo ""
}

# ── 메인 ─────────────────────────────────────────────────────
CMD="${1:-help}"
shift || true

case "$CMD" in
  start)       cmd_start ;;
  stop)        cmd_stop ;;
  restart)     cmd_restart ;;
  pull)        cmd_pull ;;
  deploy)      cmd_deploy ;;
  build)       cmd_build ;;
  status)      cmd_status ;;
  logs)        cmd_logs "$@" ;;
  shell)       cmd_shell ;;
  cert-renew)  cmd_cert_renew ;;
  backup)      cmd_backup ;;
  db)          cmd_db ;;
  help|--help|-h) cmd_help ;;
  *)
    error "알 수 없는 명령: $CMD"
    cmd_help
    exit 1
    ;;
esac
