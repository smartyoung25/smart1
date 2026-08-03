# NEXT — 다음 세션 시작점
> 마지막 커밋: 93b5ec8 (2026-07-18) · origin·iwinv 동기화됨 · 브랜치 feature/priva-mobile 대기

## 현재 상태 (1줄)
farmingsight.org iwinv 운영(SW v82) + farmer.py P2-C 리팩터 배포 + 프리바/모바일 트랙 브랜치 준비.

## ★ 다음 트랙: 프리바 연동 + 모바일 재설계 (feature/priva-mobile)
- **브랜치 개발 확정** — master가 운영 배포 소스(서버 `git checkout origin/master`)라, 다단계·안전critical
  프리바 물리제어(L2·L3) 코드를 master 직접에 두면 checkout 한 번에 운영 노출 위험. `feature/priva-mobile`
  브랜치(93b5ec8 기점, 생성 완료·빈 상태)에서 개발, master 병합은 L0→L1→L2·L3 게이트에 묶는다.
- **핸드오프 패키지는 저장소에 넣지 않음(사용자 결정)** — 설계 청사진+더미데이터 시안이고, 저장소가
  public이라 커밋 시 온실제어 설계·안전정책·192.168.x가 공개됨. zip 외부 참조로만 사용
  (`Downloads/KAASA_SmartOS_개발착수_핸드오프패키지_1.zip`, 스크래치패드에 해제해 열람함).
  ★ **저장소 비공개 전환이 프리바 코드 커밋의 선행 조건** — 태그맵·API·안전정책은 public 금지.
- **0단계 선행(개발 착수 전 확정)**: 프리바 Connext API vs 게이트웨이 · 태그맵(측정/설정값·Range·Scope) ·
  폴링주기 · L0~L3 안전정책·인터락 · MAN/0/AUTO 스위치 취득 · 권한매핑 · px→rem 토큰 · 오프라인 쓰기 범위.
- 착수 순서: **L0 읽기(N1 대시보드, 위험 0)** 우선 → L1(N2 설정 오프셋) → L2·L3(N3 관수·밸브+안전게이트).

## ★ 이번 세션 결론 (2026-07-18)

### 1. 운영 배포 (iwinv, farmingsight.org)
- 푸터 문의 채널 `iiam@iiam.co.kr` 3화면(index·intro·console) 추가, **SW v81→v82**.
- 배포 검증은 **3경로 대조**(컨테이너 실체 / localhost:8000 / 공개 도메인)로 수행 —
  세 경로 v82 일치 확인(터널 하이재킹 없음). Cloudflare 이메일 난독화로 curl엔 안 보이나
  실브라우저는 정상 복원(정상).
- 아티팩트는 named volume이라 `docker compose cp` 필수, 프론트는 이미지 베이크라 rebuild 필수.

### 2. 중간보고서 (out/, gitignore) — 스크립트만 커밋
- `이암허브_2026_중간보고서.docx` 갱신 + 스냅샷 `_20260718.docx` 보존.
- 제6장 환경실증 설계 구체화(DIF·CO₂·VPD 처치·농가내 구획·검정력 표본산정) —
  평가의견 "방법론 구체화" 응답. 배포 3경로 검증·문의채널 실적 반영.

### 3. ★ 모델 튜닝 = 신기루 (재현 가능하게 고정)
- 파프리카·완숙 M2 하이퍼파라미터/모드 스윕 순이득 미미(≤0.03).
- **모드 선택을 CV MAPE→CV R²로 바꾸면 전 작목 monthly 쏠려 R² 급등**(참외 -0.122→0.506,
  완숙 0.099→0.453 등) — 그러나 **자기상관 신기루**. SHAP 상위가 yield_lag1·yield_ewm3(지난달
  수확)·month_sin/cos·farm_yield_hist_mean뿐, 환경/경영 변수 0. 서빙 시점엔 지난달 실측 없어
  못 씀 → **모드선택 원복**(주석으로 함정 고정). 재현: `scripts/_tune_m2_experiment.py`.
- 부산물: 배포 아티팩트가 **stale**(재학습 시 값 변동)이나, run_crop 재학습은 MAPE 모드선택이
  annual(R² 음수)을 골라 오히려 악화 → 함부로 재학습 금지.
- **결론: 코드 튜닝으로 얻는 실질 개선 없음. 게이트 판정(아래) 정직하게 유효.**

### 4. 진짜 지렛대 = 외부 데이터 (문서화 완료)
- `docs/DATA_ACQUISITION_DESIGN.md`(신규) — 6축 병목 성격 분류 + **외부 입력 우선순위**:
  ①품질·등급(당도·특품율) ②농가 실비용 13항목 ③가격 선행지표 ④근권·양액 실측 ⑤품종·정식일 ⑥병해 라벨.
  다섯이 과업①(소득조사 20개소)과 겹침.
- **같은 환경센서 축적은 무효**(신호 약 0.12~0.19·교란). 환경축은 외부입력 아닌 **처치 실험**만이 해법.
- 수량(kg/m²) 아니라 **소득**을 목표로: 품질·등급 → 매출, 실비용 → 소득 검증.

## 코드리뷰 작업지시서 처리 완료 (커밋 3489892)
[x] P0-1 보안: admin 쓰기 불변식 복원(deny-list→전면차단), demo토큰 누출 차단
[x] P1-2 parcels_jeju NaN→null / P1-3 콘솔필터 공백 / P1-4 위성 null NDVI 블랭크
[x] P2-5,6 pdca 드리프트 부활(level→alert 키) + NaN 가드
[x] P3-7 whatif 부분매칭 / P3-8 undefined점 / P3-9 None[:10] 가드
→ CODE_REVIEW_WORKORDER.md 9건 전부 [x], 런타임 검증·푸시 완료

## P2-C farmer.py 분리 진행 (4300→3226줄)
[x] Step1: farmer_state.py + farmer_irrigation.py (커밋 157a6d7)
[x] farmer_pdca.py — PDCA 4라우트 (커밋 1562123)
[x] farmer_equipment.py — 기자재·연동·동의 10라우트 (커밋 82d9b20)
    · _equipment_path는 get_system_diagnosis도 사용 → farmer_state로 이관(공유)
[x] farmer_env.py — climate-plan 5라우트 (커밋 d73a444) · clean 추출
[x] 선행 헬퍼 이관 (커밋 c38355a, 2026-07-18): _activity_path·_checklist_path·_load_checklist
    → farmer_state 이관. 순환 없음(farmer→farmer_state 단방향). 앱 import OK·라우트 166 유지,
    영향 엔드포인트 4개(activity/summary·diagnosis/checklist·diagnosis·costs) 데모 200 검증.
    farmer.py 3225→3203줄. ★ 서빙 변경이나 미배포 — 배포 시 사용자 지시 필요.
[ ] 다음 후보:
    - _compute_costs 이관 (남은 선행): 동반 _RESOURCE_COSTS(L188~)·_now, 외부 import
      (persistence·stats_loader·schemas.farmer) 재배치 + ★외부 호출부 import 갱신 필수
      (api/services/ai_chat.py:700, api/services/pdca.py:158 — from api.routers.farmer import _compute_costs).
      farmer.py 내부 호출부: 385,1159,1505,1599,2651,2711,2810 부근.
    - diagnosis 클러스터 추출: get_system_diagnosis(@/diagnosis, 현재 L2569~3021 ~450줄) +
      diagnosis/* 라우트. 세 경로/체크리스트 헬퍼는 이관 완료 → _compute_costs 이관 후 통째 추출.
    - harvest(흩어짐): _get_env·_detect_alerts·_compute_costs 얽힘. _compute_costs 이관 선행.
    분리모듈 5개: state·irrigation·pdca·equipment·env (farmer.py 4300→3203줄, -25%)

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

[x] farm_registry JSON 무결성 (커밋 1182352) — bare NaN 제거 + 공백 작물명 정규화
    · area_stats "파프리카 " NaN 버킷 제거(JS JSON.parse 거부값), 함안농가 crop 공백→정상
    · 엄격 JSON 파싱 OK / 클러스터 by_crop 공백정크 0

## ⚠️ area_stats_by_crop 주의 (재계산 금지)
- farms dict 파생 아님 = 별도 면적 survey 소스(딸기 n=238 vs farms 실측area 4개)
- farms에서 재계산 시 좋은 집계(238) 파괴(→4). 절대 farms 기준 재계산 말 것.
- farms의 700+는 클러스터 proxy 농가(area_m2 없음, crop/sido만)

## 콘솔 잔여(선택)
[ ] 관제 보고서 — 현재 c20_report iframe(A4), 적정. 필요시 헤더 정리
[ ] launch.json "uvi-preview"(포트8001) — 검증 전용. 운영은 8000 워치독

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
- **외부 데이터 확보**(모델 성능의 실질 지렛대) → 우선순위·설계는 `docs/DATA_ACQUISITION_DESIGN.md`.
  요약: ①품질·등급 ②농가 실비용 13항목 ③가격 선행지표 ④근권·양액 실측 ⑤품종·정식일 ⑥병해 라벨.
- **환경 실증 실험** 설계 협의(농진청) — 관측으로는 환경효과 식별 불가, 처치 배정만이 해법(보고서 6장).
- ANTHROPIC 크레딧 충전(챗봇 LLM off) · `.env` SMTP/Slack/CoolSMS 키 · Let's Encrypt(현재 Cloudflare 터널 TLS).
- ★ 저장소 `github.com/smartyoung25/smart1` **공개 상태**(2026-07-18 재확인) — 비공개 전환은 사용자만 가능.

## 배포 모델 현황 (M2 stage2 · CV R² 게이트 · 2026-07-18 재확인)
> ★ 판정 축은 **교차검증 CV R²**(pipeline/gates.py: MIN=0.20·FALLBACK=0.0). 학습 MAPE 금지.
> ★ 과거 이 표의 "참외 27.3% 실용" 등 MAPE 수치는 **학습오차라 무효** — CV R²로 대체.

| 작물 | CV R² | 판정 | 비고 |
|------|-------|------|------|
| 오이 | 0.386 | 서비스 적용 ✅ | annual, n=61(취약) |
| 딸기 | 0.291 | 서비스 적용 ✅ | monthly, n=6427 |
| 파프리카 | 0.076 | 조건부 | monthly, n=858 |
| 완숙토마토 | 0.099 | 조건부 | annual, n=177 |
| 참외 | -0.122 | 폴백 | 표본 84·피처 64 |
| 방울토마토 | -0.257 | 폴백 | n=103, 신호부족 |

※ monthly 고R²는 자기상관 신기루(위 결론 3). 위 값은 **의사결정용 정직한 값**.

## 서버 실행
- **운영(farmingsight.org)**: iwinv Ubuntu(115.68.226.231) Docker가 서빙. 터널은 iwinv
  systemd `cloudflared-kaasa.service`. 배포는 `git checkout origin/master -- <코드경로>` +
  프론트 rebuild + 아티팩트 `docker compose cp` (CLAUDE.md 참조).
- **로컬 개발만**:
  ```powershell
  $env:PYTHONPATH="C:\smart_farm"; $env:PUBLIC_DEMO="1"
  python -m uvicorn api.main:app --port 8000
  ```
- ★ **이 PC에서 cloudflared 실행 금지** — iwinv와 같은 터널 UUID라 farmingsight.org 트래픽을
  이 PC로 가로챈다(2026-07-17 실제 사고). 배포 검증은 3경로 대조(위 결론 1).

## 주의사항
- SW 캐시 현재 **v82** — 화면 변경 시 sw.js CACHE 버전 bump 필수
- `PUBLIC_DEMO=1` 환경: `/api/admin/*` 전부 403
- IP Insight(C:\IPinsight) 관련 작업 절대 수행 금지
- farmer.py 4300줄 — 직접 전체 읽기 금지, Grep+함수명으로 접근
