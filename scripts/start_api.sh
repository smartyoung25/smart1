#!/usr/bin/env bash
# start_api.sh — 포트 충돌 없이 API 서버 시작
# 사용: bash scripts/start_api.sh [PORT]
PORT=${1:-8010}

echo ">> 포트 $PORT 기존 프로세스 정리..."
fuser -k ${PORT}/tcp 2>/dev/null || true
sleep 1

echo ">> uvicorn 시작 (port $PORT)..."
export PYTHONUTF8=1
exec python -m uvicorn api.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --reload \
  --reload-dir api \
  --reload-dir engine
