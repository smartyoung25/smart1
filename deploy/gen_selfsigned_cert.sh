#!/bin/bash
# Self-signed TLS 인증서 생성 (내부망 / 개발 환경용)
# Let's Encrypt를 사용할 수 없는 경우에만 사용하세요.
#
# 사용법:
#   bash deploy/gen_selfsigned_cert.sh [도메인명]
#   예: bash deploy/gen_selfsigned_cert.sh smartfarm.local
#
# 생성 파일:
#   nginx/certs/fullchain.pem  — 인증서
#   nginx/certs/privkey.pem    — 개인키

set -e

DOMAIN="${1:-smartfarm.local}"
CERT_DIR="$(dirname "$0")/../nginx/certs"
mkdir -p "$CERT_DIR"

echo "[1/2] Self-signed 인증서 생성 — 도메인: $DOMAIN"
openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout "$CERT_DIR/privkey.pem" \
    -out    "$CERT_DIR/fullchain.pem" \
    -subj   "/CN=$DOMAIN/O=Smart Farm/C=KR" \
    -addext "subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"

echo "[2/2] DH 파라미터 생성 (약 30초 소요)"
openssl dhparam -out "$CERT_DIR/dhparam.pem" 2048

echo ""
echo "인증서 생성 완료:"
ls -lh "$CERT_DIR"
echo ""
echo "다음 단계:"
echo "  1. nginx/nginx-selfsigned.conf 를 nginx.conf 로 교체"
echo "  2. docker compose restart nginx"
echo "  3. 브라우저에서 https://$DOMAIN 접속 (보안 경고 무시 후 진행)"
