# NEXT — 다음 세션 시작점
> 마지막 커밋: fae69f3 (2026-06-25)

## 현재 상태 (1줄)
P0+P1 완료 — 서비스 신뢰도 버그 7건 수정, 프로세스 흐름 재설계.

## 이번 세션 완료 (fae69f3)
[x] P0-A: retrain_trigger.py — 재학습 후 clear_model_cache() 자동 호출
[x] P0-B: c5_erp.html — /erp/realtime 404 제거, costs+revenue 인라인 계산으로 대체
[x] P0-C: api/main.py — /health에 db_ok 필드 추가, DB미연결 시 CRITICAL 로그
[x] P1-A: index.html — F8 노지섹션→시스템·데이터연동 섹션 이동 (기관 전용 명시)
[x] P1-B: c12_joint.html — sf_pool_joined 확인 후 가입버튼 조건부 숨김
[x] P1-C: c17_diagnosis.html — 전문가 컨설팅 CTA 추가 (c18 연결)
[x] P1-D: c20_cluster_admin.html — 이상농가 섹션에 F8 작황상세 드릴다운 링크
[x] sw.js: v72→v73

## 완료 이력 (이번 세션)
[x] P2-A: climate-plan 엔드포인트 — 이미 구현되어 있었음 (L3537~3604), 오탐
[x] P2-B: retrain_trigger.py — evaluate_and_deploy 통합 + candidate/m2_meta.json 직접 읽기
          수정 전: pipeline_meta.json(수동파일) 읽기 → gate_passed 항상 False
          수정 후: model_gate 배포 결과 기반 정확한 판정 (커밋 82b0b80)
[x] P0+P1: 커밋 fae69f3 (7건 수정)

## 다음 작업 (우선순위 순)

### P2-C: farmer.py 분리 (진행 중 — 커밋 157a6d7)
**완료**:
  - [x] Step1: `farmer_state.py` + `farmer_irrigation.py` 추출 완료 (4300→3578줄, -722줄)
    - farmer_state: router, _verify_farm_ownership, _FARM_META, _FARM_ENV, _require_farm
    - farmer_irrigation: 관수 4개 + 노지 4개 = 8개 라우트
    - 순환 임포트 없음, app 라우트 160개 전수 유지 확인

**다음 세션**:
  2. `farmer_harvest.py` — harvest, revenue, costs, market/*, whatif (Grep으로 줄번호 확인 후)
  3. `farmer_env.py`     — environment, climate-plan
  4. `farmer_diagnosis.py` — capability, diagnosis/*
  5. `farmer_equipment.py` — equipment, consent, integration
**컨텍스트 전략**: 전체 파일 읽기 금지. Grep으로 함수명 → 줄번호 → 50줄 읽기.

### 사용자 액션 필요
- 2022+ 실수확 데이터 확보 → 딸기/완숙 M2 재학습
- Let's Encrypt 인증서 교체
- `.env` SMTP/Slack/CoolSMS 키 설정

## 배포 모델 현황 (v4c)
| 작물 | MAPE | 비고 |
|------|------|------|
| 참외 | 27.3% | 실용 수준 ✅ |
| 방울토마토 | 70.6% | 방향성 참고 |
| 파프리카 | 68.6% | 방향성 참고 |
| 딸기 | 102.4% | 데이터 부족 |
| 완숙토마토 | 137.5% | 데이터 부족 |

## 서버 실행
```powershell
$env:PYTHONPATH="C:\smart_farm"; $env:PUBLIC_DEMO="1"
python -m uvicorn api.main:app --port 8000
cloudflared tunnel --config deploy/cloudflare/config.yml run kaasa-smartos
```

## 주의사항
- SW 캐시 현재 **v73** — 화면 변경 시 sw.js CACHE 버전 bump 필수
- `PUBLIC_DEMO=1` 환경: `/api/admin/*` 전부 403
- IP Insight(C:\IPinsight) 관련 작업 절대 수행 금지
- farmer.py 4300줄 — 직접 전체 읽기 금지, Grep+함수명으로 접근
