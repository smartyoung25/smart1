# Smart Farm AI Platform — developer shortcuts
# Usage: make <target>

.PHONY: help build up up-all down logs logs-pipeline logs-nginx logs-mqtt logs-weekly shell health seed-models clean test lint mqtt-pub report report-dry simulate simulate-anomaly simulate-dry

IMAGE_API      = smart-farm-api
IMAGE_PIPELINE = smart-farm-pipeline

help:
	@echo "Smart Farm AI Platform — make targets"
	@echo ""
	@echo "  build          Build all Docker images"
	@echo "  up             Start API only (detached)"
	@echo "  up-all         Start nginx + API + pipeline (detached, recommended)"
	@echo "  down           Stop all services"
	@echo "  logs           Follow API logs"
	@echo "  logs-pipeline  Follow pipeline logs"
	@echo "  logs-nginx     Follow nginx access/error logs"
	@echo "  shell          Shell into running API container"
	@echo "  health         Check API health via nginx"
	@echo "  seed-models    Copy local model artifacts into Docker volume"
	@echo "  clean          Remove images and volumes
  test           Run pytest with coverage (local)
  lint           Run ruff linter
  logs-mqtt      Follow MQTT subscriber logs
  logs-weekly    Follow weekly report logs
  mqtt-pub       Publish a test sensor message (requires mosquitto_pub)
  report         Send weekly report now (Docker)
  report-dry     Dry-run weekly report (print only, no Slack/email)
  simulate       Run MQTT simulator (3 farms, 5s interval)
  simulate-anomaly  Run simulator with anomaly injection (10% rate)
  simulate-dry   Run simulator in dry-run mode (no broker needed)"

build:
	docker compose build --no-cache

up:
	docker compose up -d api

up-all:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f api

logs-pipeline:
	docker compose logs -f pipeline

logs-nginx:
	docker compose logs -f nginx

logs-mqtt:
	docker compose logs -f mqtt-subscriber

logs-weekly:
	docker compose logs -f weekly-report

# 테스트용 센서 메시지 발행 (make mqtt-pub FARM=farm_001)
FARM ?= farm_001
mqtt-pub:
	mosquitto_pub -h localhost -t "smartfarm/$(FARM)/env" -m \
	  '{"farm_id":"$(FARM)","ts":"$(shell date -u +%Y-%m-%dT%H:%M:%SZ)","temp_internal":22.5,"humidity_int":75.0,"co2_ppm":800,"solar_rad":120.5,"soil_temp":20.1,"ec_dsm":2.1}'

shell:
	docker compose exec api bash

health:
	curl -sf http://localhost:$${NGINX_PORT:-80}/health | python3 -m json.tool

# Copy model artifacts from local disk into the named volume so API can load them
seed-models:
	@echo "Seeding model artifacts into Docker volume..."
	docker run --rm \
	  -v "$$(pwd)/models/artifacts:/src:ro" \
	  -v smart_farm_model_artifacts:/dst \
	  alpine sh -c "cp -r /src/. /dst/"
	@echo "Done."

clean:
	docker compose down -v --rmi local

# ── 테스트 / 린트 ─────────────────────────────────────────────────────────────
test:
	JWT_SECRET_KEY=test-secret-key-local \
	ADMIN_USERNAME=admin \
	ADMIN_PASSWORD=testpassword \
	ALLOWED_ORIGINS=http://localhost \
	pytest tests/ -v --tb=short \
	  --cov=api --cov=pipeline/notifier.py --cov=models \
	  --cov-report=term-missing --cov-fail-under=60

lint:
	ruff check api/ pipeline/ models/ tests/ --output-format=concise
	ruff format --check api/ pipeline/ models/ tests/

# 주간 리포트 즉시 발송 (Docker)
report:
	docker compose run --rm \
	  -e SLACK_WEBHOOK_URL=$${SLA