#!/usr/bin/env bash
# ============================================================
# Lightsail Ubuntu 22.04 초기 설정 스크립트
# 사용법: sudo bash setup-lightsail.sh your@email.com
# ============================================================
set -euo pipefail

EMAIL="${1:?사용법: sudo bash setup-lightsail.sh your@email.com}"
DOMAIN="translate.chakanag.me"
APP_DIR="/opt/document-translate-agent"

echo "▶ 패키지 업데이트..."
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 certbot git ufw

echo "▶ Docker 서비스 활성화..."
systemctl enable --now docker
usermod -aG docker ubuntu 2>/dev/null || true

echo "▶ 방화벽 설정 (80, 443, 22)..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "▶ certbot 인증서 준비 (HTTP-01 challenge)..."
mkdir -p /var/www/certbot
# 인증서 발급 전 임시 nginx로 80포트 개방
certbot certonly \
  --standalone \
  --non-interactive \
  --agree-tos \
  --email "$EMAIL" \
  -d "$DOMAIN" || {
    echo "⚠ certbot 실패 — DNS가 이 서버를 가리키고 있는지 확인하세요"
    echo "  dig +short $DOMAIN"
    exit 1
  }

echo "▶ 인증서 자동 갱신 크론 등록..."
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && cd $APP_DIR/deploy && docker compose restart nginx") | crontab -

echo "▶ 앱 디렉토리 생성..."
mkdir -p "$APP_DIR"

echo ""
echo "✅ 초기 설정 완료!"
echo ""
echo "다음 단계:"
echo "  1. 코드를 $APP_DIR 에 복사하세요"
echo "     git clone <repo> $APP_DIR"
echo ""
echo "  2. 환경변수 파일 생성:"
echo "     cp $APP_DIR/deploy/.env.example $APP_DIR/deploy/.env"
echo "     # .env 파일에서 RP_ID, RP_ORIGIN 확인 (이미 $DOMAIN 으로 설정됨)"
echo ""
echo "  3. 앱 실행:"
echo "     cd $APP_DIR/deploy && docker compose up -d"
echo ""
echo "  4. 로그 확인:"
echo "     cd $APP_DIR/deploy && docker compose logs -f app"
