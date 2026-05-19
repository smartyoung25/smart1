# Smart Farm AI Platform — 운영 전 체크리스트

> 버전: Phase 30 완성 기준 (2026-05-16)  
> 현장 배포 전 아래 항목을 순서대로 점검하세요.

---

## 1. 환경 설정 (`.env`)

| 항목 | 필수 | 확인 |
|------|------|------|
| `JWT_SECRET_KEY` — `openssl rand -hex 32`으로 생성 | ✅ | ☐ |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` — 기본값 변경 필수 | ✅ | ☐ |
| `ALLOWED_ORIGINS` — 실제 도메인/IP로 변경 | ✅ | ☐ |
| `NGINX_PORT` — 외부 포트 (기본 80) | ✅ | ☐ |
| `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` — 실제 브로커 주소 | ✅ | ☐ |
| `ETL_DATA_DIR` — CSV 수신 디렉터리 (호스트 절대경로) | ✅ | ☐ |
| `KAMIS_API_KEY` / `KAMIS_API_ID` — 미설정 시 과거 평균 사용 | 권장 | ☐ |
| `COOLSMS_API_KEY` / `COOLSMS_API_SECRET` — SMS/카카오 알림 | 권장 | ☐ |
| `NOTIFY_PHONE_FROM` / `NOTIFY_PHONE_TO` — 수신 번호 | 권장 | ☐ |
| `KAKAO_PFID` / `KAKAO_TEMPLATE_ID` — 미설정 시 SMS 대체 | 선택 | ☐ |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` — 이메일 알림 | 권장 | ☐ |
| `NOTIFY_EMAIL_TO` — 수신 이메일 | 권장 | ☐ |
| `SLACK_WEBHOOK_URL` — Slack 알림 (선택) | 선택 | ☐ |
| `ADVISOR_COOLDOWN_SEC` — 권고 재발송 대기(초, 기본 1800) | 선택 | ☐ |
| `LOG_LEVEL` — 운영 시 `info`, 디버그 시 `debug` | 선택 | ☐ |

```bash
# .env 생성
cp .env.example .env
vi .env   # 위 항목 채우기
```

---

## 2. Docker 빌드 및 실행

```bash
# 이미지 빌드
make build

# 전체 서비스 시작 (nginx + API + pipeline + MQTT + DB)
make up-all

# 상태 확인
docker compose ps
make health          # {"status":"healthy"} 확인
```

| 서비스 | 정상 상태 |
|--------|-----------|
| `nginx` | Up, 포트 80 열림 |
| `api` | Up, /health → healthy |
| `pipeline` | Up, 로그에 ETL/retrain 메시지 |
| `mqtt` (Mosquitto) | Up, 포트 1883/9001 열림 |
| `mqtt-subscriber` | Up, 브로커 연결 성공 로그 |

---

## 3. 모델 아티팩트 확인

```bash
# 로컬 모델 파일이 있을 경우 Docker 볼륨에 복사
make seed-models

# API에서 모델 로드 확인
curl -s http://localhost/api/crops | python3 -m json.tool
# → 작물 목록이 반환되면 정상
```

| 파일 | 위치 | 설명 |
|------|------|------|
| `model_m1_*.pkl` | `model_artifacts/` | M1 생육 예측 |
| `model_m2_*.pkl` | `model_artifacts/` | M2 수확량 예측 |
| `farm_registry.json` | `api/data/` | 농장 메타데이터 |
| `price_stats.json` | `api/data/` | KAMIS 과거 시세 |
| `yield_stats.json` | `api/data/` | 작목별 수확량 통계 |

---

## 4. MQTT 연동 테스트

```bash
# 방법 A: make 명령 (mosquitto_pub 필요)
make mqtt-pub FARM=farm_001

# 방법 B: Python 시뮬레이터 (브로커 연결 확인)
make simulate-dry                  # 브로커 없이 stdout 출력
make simulate FARM=farm_001        # 실제 브로커로 발행
make simulate-anomaly              # 이상값 포함 (알림 테스트)

# MQTT 구독자 로그 확인
make logs-mqtt
# → "[mqtt] 브로커 연결 성공" 확인
# → 메시지 수신 로그 확인
```

---

## 5. 대시보드 접속 및 기능 점검

접속: `http://<서버IP>` 또는 `http://localhost`

| 기능 | 테스트 방법 | 확인 |
|------|-------------|------|
| 로그인 (admin/비밀번호) | 로그인 화면 → 대시보드 진입 | ☐ |
| KPI 카드 (모델 수, 학습 로우, 농장 수) | 숫자 표시 확인 | ☐ |
| 실시간 센서 WebSocket | `make simulate` 후 센서 값 갱신 확인 | ☐ |
| 전체 농장 현황 테이블 | 농장 목록 + 상태 표시 확인 | ☐ |
| 센서 이력 차트 | 농장 행 클릭 → Chart.js 시계열 | ☐ |
| 재배 권고 이력 피드 | `make simulate-anomaly` 후 피드 확인 | ☐ |
| ETL 로그 | 파이프라인 로그 표시 확인 | ☐ |
| 재학습 이력 | 재학습 이벤트 목록 확인 | ☐ |
| KAMIS 가격 갱신 | API 키 있으면 실시간, 없으면 과거 평균 | ☐ |
| 모바일 반응형 | 스마트폰 브라우저에서 레이아웃 확인 | ☐ |

---

## 6. 알림 채널 테스트

```bash
# 이상값 발생 → Slack/이메일/SMS 발송 확인
make simulate-anomaly

# 주간 리포트 드라이런
make report-dry

# 실제 발송 테스트 (Docker)
make report
```

| 채널 | 테스트 확인 |
|------|-------------|
| 이메일 (SMTP) | 수신함 확인 | ☐ |
| SMS (CoolSMS) | 문자 수신 확인 | ☐ |
| 카카오 알림톡 | 카카오 수신 확인 (미설정 시 SMS 대체) | ☐ |
| Slack Webhook | Slack 채널 메시지 확인 | ☐ |

---

## 7. 자동화 스케줄 확인

```bash
# systemd 타이머 (베어메탈 배포)
systemctl status smart-farm-etl.timer
systemctl status smart-farm-retrain.timer
systemctl status smart-farm-weekly.timer

# Docker 배포 시 pipeline 컨테이너 cron 로그 확인
make logs-pipeline
```

| 스케줄 | 기본값 | 확인 |
|--------|--------|------|
| 증분 ETL | 매일 02:00 | ☐ |
| 재학습 트리거 | 매일 03:00 | ☐ |
| 주간 리포트 | 매주 월 08:00 | ☐ |
| KAMIS 가격 갱신 | 매일 06:00 (자동) | ☐ |

---

## 8. 보안 점검

| 항목 | 확인 |
|------|------|
| `JWT_SECRET_KEY` — 32바이트 이상 랜덤값 | ☐ |
| `ADMIN_PASSWORD` — 8자 이상, 특수문자 포함 | ☐ |
| HTTPS 인증서 적용 (Let's Encrypt / 자체 서명) | ☐ |
| nginx `server_tokens off` 설정 | ☐ |
| MQTT 브로커 인증 (`MQTT_USERNAME`/`PASSWORD`) | ☐ |
| `ALLOWED_ORIGINS` — 와일드카드(`*`) 사용 금지 | ☐ |
| Docker 네트워크 — API 포트 직접 외부 노출 금지 | ☐ |

---

## 9. 통합 테스트 실행

```bash
# 전체 테스트 (커버리지 60% 이상)
make test

# 현장 시나리오 전용
pytest tests/test_e2e_field.py -v

# 특정 시나리오만
pytest tests/test_e2e_field.py::TestCropAdvisor -v
pytest tests/test_e2e_field.py::TestAdminAPI -v
```

---

## 10. 장애 대응 Quick Reference

| 증상 | 원인 | 조치 |
|------|------|------|
| API `/health` 504 | nginx→API 연결 실패 | `make logs` 확인, `make up-all` 재시작 |
| 센서 데이터 미수신 | MQTT 구독자 다운 | `make logs-mqtt`, 브로커 주소 확인 |
| 재학습 미발생 | 임계값 미달 | `RETRAIN_ENV_ROWS`/`PROD_ROWS` 낮추기 |
| SMS 미발송 | CoolSMS 잔액/인증 | CoolSMS 콘솔에서 잔액 및 발신번호 확인 |
| 카카오 미발송 | 템플릿 미승인 | 알림톡 대신 SMS 자동 대체 (`disableSms:false`) |
| KAMIS 가격 0 | API 키 누락 | `KAMIS_API_KEY` 설정 또는 과거 평균 사용 |
| 대시보드 차트 공백 | ETL 데이터 없음 | `make simulate` 후 확인 |
| 권고 알림 미발송 | 쿨다운 중 | `ADVISOR_COOLDOWN_SEC` 줄이기 또는 대기 |
| 모델 로드 실패 | 아티팩트 누락 | `make seed-models` 재실행 |

---

## 11. 백업 정책

```bash
# 모델 아티팩트 백업
docker run --rm -v smart_farm_model_artifacts:/src -v $(pwd)/backup:/dst \
  alpine tar czf /dst/models_$(date +%Y%m%d).tar.gz -C /src .

# 파이프라인 상태 (이력 JSON) 백업
tar czf backup/state_$(date +%Y%m%d).tar.gz pipeline/state/

# ETL 완료 CSV 백업
tar czf backup/etl_done_$(date +%Y%m%d).tar.gz etl_data/done/
```

권장 백업 주기: 모델 아티팩트 주 1회, 파이프라인 상태 일 1회.

---

_체크리스트 완료 후 현장 운영을 시작하세요._  
_문의: Smart Farm AI Platform 운영팀_
