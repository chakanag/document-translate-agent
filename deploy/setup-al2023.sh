#!/usr/bin/env bash
# ============================================================
# Amazon Linux 2023 + Lightsail 초기 설정 스크립트
# 사용법: sudo bash setup-al2023.sh your@email.com
# ============================================================
set -euo pipefail

EMAIL="${1:?사용법: sudo bash setup-al2023.sh your@email.com}"
DOMAIN="doc-tr.chakanag.me"

echo "▶ [1/6] 패키지 업데이트 및 기본 도구 설치..."
dnf update -y -q
dnf install -y -q git docker certbot

echo "▶ [2/6] Docker 서비스 활성화..."
systemctl enable --now docker
usermod -aG docker ec2-user

echo "▶ [3/6] Docker Compose V2 설치..."
ARCH=$(uname -m)  # x86_64 또는 aarch64
COMPOSE_URL="https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}"
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "$COMPOSE_URL" -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version  # 확인

echo "▶ [4/6] 방화벽(firewalld) 포트 개방..."
if systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http
  firewall-cmd --permanent --add-service=https
  firewall-cmd --reload
  echo "   firewalld: 80, 443 개방 완료"
else
  echo "   firewalld 미실행 — Lightsail 콘솔에서 방화벽 규칙을 확인하세요"
fi

echo "▶ [5/6] certbot으로 SSL 인증서 발급 (standalone, 80포트 사용)..."
mkdir -p /var/www/certbot
certbot certonly \
  --standalone \
  --non-interactive \
  --agree-tos \
  --email "$EMAIL" \
  -d "$DOMAIN" || {
    echo ""
    echo "⚠ certbot 실패. 확인사항:"
    echo "  1. Route 53 A 레코드: $DOMAIN → 이 서버 IP"
    echo "  2. Lightsail 콘솔 Firewall에서 80, 443 포트 허용 여부"
    echo "  3. dig +short $DOMAIN  (정상이면 이 서버 IP 출력)"
    exit 1
  }

echo "▶ [6/6] 인증서 자동 갱신 크론 등록..."
# 갱신 시 Docker nginx 재시작
(crontab -l 2>/dev/null || true; echo "0 3 * * 0 certbot renew --quiet --pre-hook 'docker stop \$(docker ps -q --filter name=nginx)' --post-hook 'cd /home/ec2-user/document-translate/deploy && docker compose start nginx'") | crontab -

echo ""
echo "✅ 초기 설정 완료!"
echo ""
echo "▶ 다음 단계:"
echo "  sudo bash /home/ec2-user/document-translate/deploy/deploy.sh"
