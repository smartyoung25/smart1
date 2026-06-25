# NEXT — 다음 세션 시작점
> 마지막 커밋: a6a0134 (2026-06-25)

## 현재 상태 (1줄)
PC 관리자 콘솔 신설(Step1~4 완료) — admin/manager 풀폭 콘솔 + 역할 라우팅.

## PC 관리자 콘솔 진행 상황 (계획: ~/.claude/plans/peppy-fluttering-quilt.md)
[x] Step1: TokenResponse.role 노출 (커밋 9f527be)
[x] Step2: /console 라우트 + 셸 + 공개경로 (a6a0134)
[x] Step3: c0_signup _login() admin/manager→/console 분기 (a6a0134)
[x] Step4: 사이드바 해시라우팅 + iframe 임베드(c20/f8/c9/c6/c20_report) (a6a0134)
    ★ 핵심수정: base.css main{max-width:600px} 오염을 .con-main 풀폭 override로 차단
[x] Step6: 클러스터 관제 PC 풀폭 네이티브 뷰 승격 (커밋 ec6e198)
    · console_cluster.js: KPI6열 + 지역/작목 2열 데이터테이블 + 이상농가 풀폭테이블
    · 실데이터 검증: 농가732·이상228 / 풀폭1200px / 콘솔에러0
[x] 위성 작황 풀폭 네이티브 승격 + 클러스터→위성 드릴다운 (커밋 b0757df)
    · console_satellite.js: KPI6열 + NDVI히트맵 + 필지표 2열 + 이상알림 풀폭표
    · F8은 per-farm 상세 → 클러스터 이상농가 🛰️클릭으로 콘솔 내 드릴다운(동선완결)
[x] AI 학습·모델 풀폭 네이티브 승격 (커밋 2f713e4)
    · console_model.js: KPI6열 + 파이프라인5 + M2게이트/드리프트 2열 + M1~M5매트릭스 + M1표20
    · system/model-performance(전역) 사용 — 관리자 콘솔에 본질적 적합

[x] 벤치마킹 메뉴 제거 → 위성 뷰에 흡수 (커밋 1a63a3c)
    · c9는 per-farm이라 별도 메뉴 부적합 → 위성 드릴 맥락에 "우수농가 대비" 카드로 통합
    · 마지막 480px iframe 제거. 드릴다운 시 해당농가 NDVI+벤치마킹 한 화면

[x] 대시보드 랜딩 실시간 운영요약 (커밋 912a628)
    · console_dashboard.js: cluster+model 결합 KPI6 + 하이라이트(이상다발지역·드리프트위험)
[x] 다크모드·반응형(≤1100px) 검증 통과 — 사이드바200·KPI3열·그리드1열·다크패널 정상

## 콘솔 사이드바 현황 (완료)
- 대시보드(실시간요약) / 클러스터 관제 / 위성 작황(+벤치마킹+드릴) / AI 학습·모델 → ✅ 풀폭 네이티브
- 관제 보고서(c20_report) → iframe 794px A4, 적정(유지)
- ✅ 480px 모바일 iframe 전부 제거. 다크모드·반응형 검증 완료.
- 검증 전부 포트8001(운영8000 무영향). launch.json "uvi-preview"

[x] QA 테스트 시드 16개 제거 (커밋 a31ad7e) — 자동 온보딩/QA 아티팩트
    · total_farms 732→716, 충청남도 89→77, 미상 6→2(데모 farm_005·farm_link1 보존)
    · 명시적 ID 리스트 제거(연관데이터 0 확인), console.html 하드코딩 "725개농가" 제거
    · 콘솔 대시보드 716 반영 확인
    · 참고: area_stats_by_crop는 캐시 집계 유지(폴백 추정 근사값)

## 콘솔 잔여(선택)
[ ] 관제 보고서 — 현재 c20_report iframe(A4), 적정. 필요시 헤더 정리
[ ] launch.json "uvi-preview"(포트8001) — 검증 전용. 운영은 8000 워치독
[ ] (선택) area_stats_by_crop 재계산 — 테스트농가 제거분 반영(딸기 카운트 미세 정정)

## ✅ 해결: 클러스터 집계 시도명 정규화 (커밋 98f82d8)
- api/services/region_canon.py 신규(정규화 단일소스) → cluster_overview·main.py 공용
- 충남+충청남도→충청남도(89), 충북+충청북도→충청북도(35) 병합
- 정크(test/Chungnam/Chungbuk/—) → 미상(6) 통합, by_region 14→11행
- 모바일 C20·PC 콘솔 동시 해결

## 참고: farm_registry 테스트 시드 잔존(정상 데이터 아님, 선택적 정리)
- farm_recfill75208(sido=test)·farm_fullcheck75230(Chungnam)·farm_dashcheck75277(Chungbuk)
  = QA 자동점검 아티팩트. 현재 미상 버킷으로 무해 처리됨. 레지스트리에서 제거하면 더 깔끔.
- 스킬: .claude/skills/ui-ux-pro-max-skill/ 설치됨(gitignore). 검색CLI 실행은 보안차단 → 데이터 직접 읽기로 활용
- 검증서버: 별도 포트 8001 (운영 8000 비건드림). launch.json "uvi-preview"

## 이전 세션 완료 (fae69f3)
P0+P1 — 서비스 신뢰도 버그 7건 수정, 프로세스 흐름 재설계.

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
