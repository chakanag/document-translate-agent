#!/usr/bin/env bash
# ============================================================
# 앱 배포 스크립트 (코드 업데이트 + 재기동)
# 사용법: bash /home/ec2-user/document-translate/deploy/deploy.sh
# ============================================================
set -euo pipefail

APP_DIR="/home/ec2-user/document-translate"
DEPLOY_DIR="$APP_DIR/deploy"

cd "$DEPLOY_DIR"

echo "▶ .env 파일 확인..."
if [[ ! -f .env ]]; then
  echo "⚠  .env 파일이 없습니다."
  echo "   cp .env.example .env 후 내용을 확인하세요."
  exit 1
fi

echo "▶ Docker 이미지 빌드..."
DOCKER_BUILDKIT=0 docker compose build app

echo "▶ 서비스 재시작..."
docker compose up -d --remove-orphans

echo "▶ 헬스체크 (최대 30초)..."
for i in $(seq 1 10); do
  sleep 3
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8010/api/health 2>/dev/null || echo "000")
  if [[ "$HTTP" == "200" ]]; then
    echo "✅ 앱 정상 기동 (HTTP $HTTP)"
    break
  fi
  echo "   대기 중... ($i/10)"
done

echo ""
echo "✅ 배포 완료! https://doc-tr.chakanag.me 에서 확인하세요."
echo ""
echo "유용한 명령:"
echo "  로그 보기:       docker compose logs -f app"
echo "  상태 확인:       docker compose ps"
echo "  앱만 재시작:     docker compose restart app"
echo "  전체 중지:       docker compose down"
