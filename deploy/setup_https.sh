#!/bin/bash
# Smart Farm — Let's Encrypt HTTPS 설정 원스텝 스크립트
#
# 사용법:
#   bash deploy/setup_https.sh <도메인> <이메일>
#   예: bash deploy/setup_https.sh smartfarm.example.com admin@example.com
#
# 사전 조건:
#   - 도메인의 A 레코드가 이 서버 IP를 가리키고 있어야 합니다
#   - 포트 80이 방화벽에서 열려 있어야 합니다 (ACME 챌린지용)
#   - docker compose up -d 로 HTTP 스택이 실행 중이어야 합니다

set -e

DOMAIN="${1:?사용법: $0 <도메인> <이메일>}"
EMAIL="${2:?사용법: $0 <도메인> <이메일>}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "========================================"
echo " Smart Farm HTTPS 설정"
echo " 도메인: $DOMAIN"
echo " 이메일: $EMAIL"
echo "========================================"
echo ""

# ── 1단계: HTTP 스택 실행 확인 ───────────────────────────────────────────────
echo "[1/5] HTTP 스택 상태 확인..."
cd "$PROJECT_ROOT"
if ! docker compose ps nginx | grep -q "running\|Up"; then
    echo "  nginx가 실행 중이 아닙니다. 먼저 실행합니다..."
    docker compose up -d nginx api
    sleep 10
fi
echo "  OK"

# ── 2단계: Certbot으로 인증서 최초 발급 ─────────────────────────────────────
echo "[2/5] Let's Encrypt 인증서 발급 중..."
docker run --rm \
    -v "$(docker volume inspect smart_farm_certbot_www --format '{{.Mountpoint}}'):/var/www/certbot" \
    -v "$(docker volume inspect smart_farm_certbot_certs --format '{{.Mountpoint}}'):/etc/letsencrypt" \
    certbot/certbot:latest certonly \
    --webroot \
    --webroot-path /var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"
echo "  인증서 발급 완료"

# ── 3단계: DOMAIN_NAME 환경변수 추가 ─────────────────────────────────────────
echo "[3/5] .env에 DOMAIN_NAME 추가..."
if grep -q "^DOMAIN_NAME=" "$PROJECT_ROOT/.env" 2>/dev/null; then
    sed -i "s/^DOMAIN_NAME=.*/DOMAIN_NAME=$DOMAIN/" "$PROJECT_ROOT/.env"
else
    echo "DOMAIN_NAME=$DOMAIN" >> "$PROJECT_ROOT/.env"
fi
echo "  DOMAIN_NAME=$DOMAIN"

# ── 4단계: nginx SSL 설정 교체 ───────────────────────────────────────────────
echo "[4/5] nginx를 HTTPS 모드로 전환..."

# nginx-ssl.conf의 ${DOMAIN_NAME} 플레이스홀더를 실제 도메인으로 치환
sed "s/\${DOMAIN_NAME}/$DOMAIN/g" \
    "$PROJECT_ROOT/nginx/nginx-ssl.conf" \
    > "$PROJECT_ROOT/nginx/nginx-active.conf"

# docker-compose.yml nginx 볼륨을 nginx-active.conf로 교체
docker compose stop nginx
docker run --rm \
    -v "$PROJECT_ROOT/nginx/nginx-active.conf:/src/nginx.conf:ro" \
    -v "$(docker volume inspect smart_farm_certbot_certs --format '{{.Mountpoint}}'):/etc/letsencrypt:ro" \
    nginx:1.25-alpine nginx -t -c /src/nginx.conf 2>&1 \
    && echo "  nginx-ssl.conf 문법 OK" \
    || { echo "  nginx 설정 오류 — 롤백합니다"; docker compose up -d nginx; exit 1; }

# nginx.conf를 SSL 버전으로 교체
cp "$PROJECT_ROOT/nginx/nginx-active.conf" "$PROJECT_ROOT/nginx/nginx.conf"
docker compose up -d nginx
echo "  nginx HTTPS 모드 전환 완료"

# ── 5단계: Certbot 자동 갱신 서비스 시작 ─────────────────────────────────────
echo "[5/5] Certbot 자동 갱신 서비스 시작..."
docker compose --profile https up -d certbot
echo "  Certbot 갱신 서비스 시작 완료 (12시간마다 갱신 시도)"

echo ""
echo "========================================"
echo " HTTPS 설정 완료!"
echo " 대시보드: https://$DOMAIN"
echo " API 문서: https://$DOMAIN/docs"
echo "========================================"
echo ""
echo "인증서 갱신 테스트:"
echo "  docker compose exec certbot certbot renew --dry-run"
