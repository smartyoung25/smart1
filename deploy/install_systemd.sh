#!/bin/bash
# Smart Farm — systemd 서비스 설치 스크립트
# 사용: sudo bash deploy/install_systemd.sh

set -e

INSTALL_DIR="/opt/smart_farm"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_USER="smartfarm"

echo "[1/5] 서비스 사용자 생성 (없으면)"
id "$SERVICE_USER" &>/dev/null || useradd --system --no-create-home --shell /sbin/nologin "$SERVICE_USER"

echo "[2/5] 디렉토리 권한 설정"
mkdir -p "$INSTALL_DIR/logs" "$INSTALL_DIR/etl_data" "$INSTALL_DIR/pipeline/state"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/logs" \
    "$INSTALL_DIR/etl_data" \
    "$INSTALL_DIR/pipeline/state" \
    "$INSTALL_DIR/models/artifacts"

echo "[3/5] .env 파일 확인"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "  경고: $INSTALL_DIR/.env 없음. .env.example을 복사하여 설정하세요."
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env" 2>/dev/null || true
fi

echo "[4/5] systemd unit 파일 복사"
UNITS=(
    "smart-farm-api.service"
    "smart-farm-etl.service"
    "smart-farm-etl.timer"
    "smart-farm-retrain.service"
    "smart-farm-retrain.timer"
    "smart-farm-kamis.service"
    "smart-farm-kamis.timer"
    "smart-farm-weekly.service"
    "smart-farm-weekly.timer"
)
for unit in "${UNITS[@]}"; do
    cp "$(dirname "$0")/systemd/$unit" "$SYSTEMD_DIR/$unit"
    echo "  설치: $SYSTEMD_DIR/$unit"
done

echo "[5/5] systemd 리로드 및 서비스 활성화"
systemctl daemon-reload

# API 서버 — 항상 실행
systemctl enable --now smart-farm-api.service

# ETL + Retrain — 타이머로 실행 (service 직접 enable 하지 않음)
systemctl enable --now smart-farm-etl.timer
systemctl enable --now smart-farm-retrain.timer
systemctl enable --now smart-farm-kamis.timer

# 주간 리포트 — 매주 월요일 08:00
systemctl enable --now smart-farm-weekly.timer

echo ""
echo "설치 완료. 상태 확인:"
echo "  systemctl status smart-farm-api"
echo "  systemctl status smart-farm-etl.timer"
echo "  systemctl status smart-farm-retrain.timer"
echo "  systemctl status smart-farm-kamis.timer"
echo "  systemctl status smart-farm-weekly.timer"
echo ""
echo "즉시 ETL 실행:"
echo "  systemctl start smart-farm-etl.service"
echo ""
echo "즉시 가격 갱신 실행:"
echo "  systemctl start smart-farm-kamis.service"
echo ""
echo "즉시 주간 리포트 발송:"
echo "  systemctl start smart-farm-weekly.service"
echo ""
echo "로그 확인:"
echo "  journalctl -u smart-farm-api -f"
echo "  journalctl -u smart-farm-kamis -f"
echo "  journalctl -u smart-farm-weekly -f"
echo "  tail -f $INSTALL_DIR/logs/etl.log"
echo "  tail -f $INSTALL_DIR/logs/retrain.log"
