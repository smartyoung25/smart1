# KAASA SmartOS — 작업 메모리 (CLAUDE.md)
> 매 세션 시작 시 이 파일을 반드시 먼저 읽을 것.
> 매 세션 종료 시 결정사항·진행상태·남은 일을 반드시 이 파일에 기록할 것.

---

## ★ 리브랜딩·인증·전략표·대시보드 일원화 세션 (2026-06-11)
> 제품명 **KAASA SmartOS → KAASA smartfarmingsight** 전면 변경. 고정도메인 **https://farmingsight.org**(Cloudflare Named Tunnel). PUBLIC_DEMO 읽기전용 유지.

### 리브랜딩·첫화면·테마
- 브랜드명 전 화면 122곳 치환(기능식별자 `/smartos`·`kaasa-smartos` 터널·SW키는 보존)
- 첫화면(`/intro`) 리디자인 + 전역 `.section-label` 강조바(41화면 일괄)
- **다크/라이트 테마 토글**: `base.css html[data-theme="dark"]` 변수 + `data.js` `toggleTheme()`(localStorage `sf_theme`) + 전역 플로팅 🌙/☀️. (intro는 data.js 미로드 → 토글 없음)
- 전역 플로팅 버튼(🏠 홈·❓ 페이지별 도움말) data.js `_installFab()`

### 인증 강화 (api/routers/auth.py, persistence.py)
- 회원가입 **이메일·전화번호 필수+형식검증**(정규식). phone은 DB컬럼 권한없으면 `data/user_contacts.json` 폴백
- **비밀번호 찾기/재설정**: `/password/forgot`·`/reset` + 토큰(`data/password_resets.json`, 30분) + `api/services/mailer.py`(SMTP). 신규 `screens/c0_reset.html`. C0에 로그인 탭·비번찾기 추가
- 공개 데모에서 **실가입 허용**(사용자 선택). 데모 쓰기 허용목록 확대(아래)

### PUBLIC_DEMO 쓰기 허용목록 (api/main.py) — 사용자 요청 기능만 선별 개방
- `_WRITE_ALLOW`: auth token·register·password/forgot·reset·telemetry·`/api/data/{growth,harvest}`
- `_WRITE_ALLOW_SUFFIX`: `/chat`·`/integration-request`·`/equipment`·`/climate-plan`·`/consent`·`/daily-temp`·`/whatif`
- 운영데이터(activity 등)·`/api/admin/*` 쓰기는 **여전히 403**

### C1 정정 + 신규 화면
- **재배방식 분류 정정**: 잘못된 '양액' 독립항목 제거(수경·배지경 모두 양액재배). 안내문 추가
- **목표 수확량 → 면적당(kg/10a)**, 총량 자동환산
- **데이터동의 저장**: 전용 `GET/POST /consent`(farmer.py) — 기존 /activity 경유 403 해소
- 신규 **C21 `c21_apply.html`**(연동·서비스 신청) + `/integration-catalog`·`/integration-request`. C16에 연동신청 CTA, 메뉴·네비게이터 등록

### ★ G2 환경관리 전략표 (api/services/climate_plan.py 신규)
- 2축: 행=생육시기(정식기준, 생육단계/주별/월별) × 열=하루4구간(야간·일출·주간·일몰전), 셀=온도/습도/CO₂(VPD자동)
- `GET/POST /environment/climate-plan`·`/active`·`/evaluate`. 작물별 기본템플릿(딸기 겨울값+_default, 부분일치)
- **선진 벤치마크**: Priva 광연동승온(일사 ref200 초과 100W당+0.6℃·상한+3) · HNT 24h평균/DIF · Plant Empowerment VPD밴드 · 농진청
- **AI제어 연동**(고정임계값 폐기): `evaluate()`가 전략표 목표 대비 실측편차로 처방생성 → G2 `_updateAiControls` 전략표 우선·정식일없으면 규칙폴백
- **②일출·일몰 동적경계**: `sun_times()` Open-Meteo 무키. **③온도적산(HNT)**: `record_daily_temp`/`integration_state` 최근5일 누적부족→오늘목표±2℃ 보정. `POST /environment/climate-plan/daily-temp`

### ★ PC 대시보드(dashboard/, 다크) ↔ 모바일(screens/) 통합
- **값 불일치 통일(PC→모바일 표준)**: DLI에 PAR계수 4.57(누락시 ~4.6배 과소) / VPD밴드 0.4·0.6 / 배액률 norm[20,35]·crit[15,45]
- 나머지 KPI(원가·마진·소득률·수확량)는 **동일 엔드포인트→값 일치**
- **PC강점 6종 모바일 이식**: C6 드리프트모니터링+M1~M5 매트릭스(비관리자 model-performance MAPE 산출) / G4 What-if·SFROP 4시나리오(/whatif)·수확실측입력(/api/data/harvest, M2학습) / G2 권고빈도(/journal/advisory)
- **진입 일원화**: 루트 `/`·`/dashboard/*` 전부 `/intro` 307 리다이렉트. dashboard/ 파일은 보존(롤백 안전, 마운트 제거만)

### 운영(ops) — Error 1033 재발방지
- `deploy/cloudflare/watchdog.ps1`: uvicorn+cloudflared 죽으면 30초주기 자동재기동. **단일 인스턴스 가드(Mutex)** — 중복 watchdog→cloudflared 이중기동→터널충돌(1033) 원인 해결. 시작프로그램 폴더 등록(로그온 자동)
- 서버 구동: `PYTHONPATH=C:\smart_farm PUBLIC_DEMO=1 python -m uvicorn api.main:app --port 8000`. 터널: `cloudflared tunnel --config deploy/cloudflare/config.yml run kaasa-smartos`
- SW 캐시 v3→**v16**(변경마다 bump). GitHub: `smartyoung25/smart1` push 완료

### ⚠️ 남은 사용자 조치(비밀/권한 필요 — 내가 못함)
- **SMTP 자격증명**: `.env`의 `SMTP_USER`·`SMTP_PASSWORD` 비어있음(Gmail 주소+앱비번 16자). 채우면 비번재설정 메일 자동발송(현재 데모링크 방식). `PUBLIC_BASE_URL=https://farmingsight.org`·`SMTP_HOST=smtp.gmail.com`·`SMTP_PORT=587`은 설정됨. mailer는 `SMTP_PASSWORD`/`SMTP_PASS` 둘다 인식
- **LLM 키**: `ANTHROPIC_API_KEY` 비어있음 → 챗봇·AI총평이 규칙기반 폴백. pro/enterprise 티어시 `claude-haiku-4-5`/`claude-sonnet-4-5`. **보고서 생성은 LLM 아님**(결정론적 집계)
- **터널 부팅영속**(선택): 관리자 권한 `cloudflared service install`(A안). 현재는 로그온시 watchdog 자동기동(B안)
- **잔여파일 정리**(선택, 미삭제): `dashboard/index.html.tmp1`, 루트 `tmp_*.py/png` 등 — 내가 안 만든 파일이라 보류

---

## 데모 충실화·왜곡교정·노지 실데이터 노출 (2026-06-10)
> 원칙: 샘플데이터는 **실제 시스템 산출과 일치**해야 함(허구 금지). 보안 게이트(PUBLIC_DEMO 읽기전용) 유지.

### UI·네비게이션
- 보고서(c14/c17/c20) 어두운 배경 #5a6678→#e7edf3 가독성 / F1 노지 현장컨설팅 배너(C17·C18·C19·C4)
- 메뉴 진입점 감사: c13 막다른화면→헤더 ≡ / c11·c6·c8 맥락진입 추가 / `window.KaasaData` 전역노출. `docs/ENTRYPOINT_AUDIT.md`
- 네비게이터 섹션 재정리: 잡탕 19카드→5그룹(진단·컨설팅/경영전략/출하/시스템/계정), 노지 상향. 38카드 보존

### ★ C20 왜곡 교정 (자체검증으로 발견)
- 손으로 지어낸 데모(제주 노지작물·이상6.5% 미화)가 실제와 불일치 → 실제 `build_overview`(725농가·이상31.3%·온실작목)로 교체. **데모=인증관리자뷰 일치**

### 작물별 온실 데모 전환기 (단일농장 고정 해소)
- `data.js _DEMO_FARMS`: 오이(001)·방울토마토(002)·딸기(003)·완숙토마토(004)·파프리카·제주. `_syncFarmSelectors()` 전화면 #farmSel 통일
- 온실 관수 샘플 추가(farm_002/003/004/파프리카, 농학적 차별값): 전환 시 G3 관수까지 작물별 재시뮬레이션. G1~G6 빈상태0

### 모델 임계점·최적모델 노출 (C6)
- 배포게이트(MAPE≤35%·R²≥0)·챔피언/챌린저(M2 5%p↓·M1 R²+0.02) + M2 게이트표(딸기·오이·완숙토마토·파프리카 통과/방울토마토48.6%·참외63.9% 탈락→폴백)

### 연합학습(federated-lite) 스캐폴드 + 전송계층
- `pipeline/federated/{local_correction,aggregate,edge_runner}.py`: 농장 로컬 보정계수(raw_geo^shrink)만 산출·업로드(원본 미반출). 중앙값 재현 검증
- `api/routers/federated.py`: POST /correction(인증·원본반출가드·데모403차단)·GET /corrections/{crop}. `docs/FEDERATED_ONPREM_LEARNING.md`
- 한계: 모델 가중치 FedAvg는 Flower 도입 선행(미구현)

### ★ 노지 실데이터 노출 버그 2건 수정
- `_require_farm` 레지스트리 meta를 `_FARM_META` 미캐시 → 18개 사이트 빈meta → 캐싱 1줄 추가(전역)
- `_real_parcels_lookup` 읍면명↔시군구키 불일치 폴백 추가 → 제주농장 soil naas_soil_real(7189필지)·parcels farmmap_real(4601필지) 노출

### ★ ERA5 외부기상 보강 — 딸기 M2 개선(측정 기반, 거짓향상 0)
- **무키 경로**: Copernicus CDS(계정필요) 대신 **Open-Meteo 아카이브(ERA5 재분석, 무키)**로 확보. `scripts/fetch_era5_openmeteo.py`(5작물 주산지 좌표)+`inject_era5_into_cache.py`. backlog "ERA5 확보" 영구 해결
- **딸기 채택**: temp_external 결측20%를 ERA5 월별기온 보강 → LOYO CV R² **0.192→0.295(+0.103)**·MAPE 20.8→17.8%·게이트 FAIL→PASS. 라이브 서빙(C6 게이트표 반영)
- **측정 기반 기각(롤백)**: ①무ERA5 재학습=개선0(±0.003) ②타작물(참외·방울·완숙) temp보강=개선없음/악화 ③딸기 solar_rad 보강=악화(0.295→0.262). cache solar_rad=온실내부일사라 ERA5외부와 상관 R²0.13뿐
- **결론**: ERA5 외부기온은 겨울딸기(외부기온 민감)에만 유효. 추가향상은 **학습farm 실좌표**(현재 익명) 필요=데이터 게이트
- **원칙 확립**: 모든 재학습은 baseline 대비 LOYO CV 측정→개선시만 채택, 미달 즉시 롤백(model_gate 규율)

### UX·기능 보강 (2026-06-10 PM2)
- **AI비서(C13) 정상화**: 데모 POST /chat 허용(읽기전용 게이트 유지) + 평년기상·데이터입력 의도 + LLM 시스템프롬프트에 평년/진단/역량/작황 통합
- **회원가입(C0)**: 데모 403 graceful(흐름유지) + **유통전문가 역할 추가**(5역할) + 역할별 진입 라우팅(유통→C12·전문가→C4·공공→C20)
- **앱 내 도움말**: `screens/help.html`(빠른시작·FAQ·용어·출처배지·AI질문CTA) + 드로어·챗봇❓·네비 진입점
- **DecisionDeck 정직성**: 데모 403 거짓성공 제거('🔒 데모: 기록 비활성')
- **SW 캐시 수정**: HTML network-first + CACHE v3 → 묵은 화면(스테일) 방지
- **메뉴별 통찰 개선**(데이터→해석·권고): G1 온실핵심·C12 출하타이밍·C10 추천투자안·F6 방제적기·F7 수확출하·C5 최대비용절감. (G4·F4·G2 등은 기존 해석 보유로 미변경)
- **v1.7 릴리스**: releases/kaasa_smartos_v1.7_*.zip(4.5MB·988파일·41화면) + RELEASE_v1.7.md
- **사용자 매뉴얼**: docs/USER_MANUAL.md(17장) · docs/DEMO_GUIDE_BY_CROP.md

### 배포 준비도 (2026-06-10 검수)
- 전 41화면 콘솔에러0·4xx0·깨진링크0(전역 data.js 변경 후 회귀0)
- 성능: TTFB~310ms·FCP<440ms·load<530ms — LCP<3s 충족
- PUBLIC_DEMO 읽기전용(쓰기·관리자403) 유지. 무료 퀵터널(재시작 시 URL변경=계정필요한 고정도메인 미적용)
- 고정도메인 턴키: `deploy/cloudflare/setup_named_tunnel.ps1 -Domain x`(login→create→DNS→config 자동). 사용자=계정·도메인·로그인만

### 품질 감사 라운드 (2026-06-10, "다음" 연속) — 전부 실측·회귀0
- **데이터 출처버그 수정**: F4 naas_soil_real·F2 farmmap_real Mock 오표기 / C3 관리자시세403→비관리자 폴백+KAMIS 출처정정
- **모델 가시화**: C6 학습화면 ERA5 파이프단계+딸기 ERA5↑ 배지
- **접근성 3축**: 레이블/alt/input누락0 / 터치타겟(c16삭제22×15→44×32·g3·c12) / 색대비 --orange #d97706→#b45309(3.2→5.0:1 AA)
- **온보딩 통합**: C1저장→C2 데이터동의(권장,?next=)→계속 / flow.html 여정지도 동의단계 반영
- **빈상태 복원력**: 신규농장도 모델폴백으로 깨짐0(이상무)

### ★ 신규 기능: 평년 대비 외부기상 (ERA5 climatology) — 26작물·3화면
- `api/services/climatology.py`+`GET /environment/climatology?crop=`: 작물 주산지 ERA5(2018~2022) 월별 평년값(기온·일사·강수·GDD). 작물별 GDD기준온도(감귤13·고구마15·수박12 등)
- 페처 `scripts/fetch_era5_openmeteo.py`(무키 Open-Meteo archive). 인젝터 `inject_era5_into_cache.py`
- **26작물**: 온실6(딸기·참외·방울토마토·완숙토마토·오이·파프리카)+노지채소9(감귤·월동무·당근·양배추·마늘·양파·배추·무·대파)+과수5(사과·배·복숭아·감·포도)+주식고소득6(벼·고추·콩·감자·고구마·수박)
- **3화면 통합**: G2(온실 냉난방계획)·F3(노지 작황)·F8(클러스터 우세작물). 미지원작물 자동숨김
- **★ F8 작동진단**: 16일예보 vs 평년 편차(|Δ기온|≥3℃ or 강수±50%) → 광역 이상기상 감지 시 이상필지 알림 심각도 상향(주의→시급)+🌡️칩+배너("개별관리 아닌 광역기상")

### ERA5 × M2 재학습 — 6작물 측정 결론(확정)
- ✅ 딸기 +0.103(0.192→0.295) 채택·라이브 — 겨울시설 외부기온 민감
- ↩ 참외·방울·완숙·오이 무개선/노이즈(오이 +0.007 n=30 비유의)·롤백 / ⛔ 파프리카 학습캐시부재
- 원칙: LOYO CV가 noise(±0.003) 초과 개선시만 채택, 미달 즉시 롤백. 거짓향상 0

## 실데이터 주입 + 시각화·UX 강화 (2026-06-09 PM)
### 제주 실데이터 주입(PII 제외 집계, 지역매칭 자동전환)
- 흙토람 토양검정 13,842필지→`/field/soil` naas_soil_real / 팜맵 276,491필지→`/field/parcels`·F8 farmmap_real / 소득조사 102농가→`/benchmark` 실비교군
- importer: `scripts/import_real_{soil,parcels,income,pest}.py`, `api/data/real/*.json`. `docs/REALDATA_VERIFICATION.md`
- 병해충 예찰: `/field/pest` 파이프라인 완성(소형 parquet 인라인반환으로 적재대기). M2 재학습=생육조사 수확량타깃 부재로 불가(문서화)
### 화면 시각화 10건(의존성0 SVG/CSS): C3 우수농가바·실데이터배지 / C17 6대영역 레이더 / F8 NDVI 히트맵 / G3 일일WC곡선 / C14 전월대비 다이버징 / G2 온습도·VPD추이 / G6 신뢰구간밴드 / F3 16일 기온·강수 / G4 초장추세
### 프레임워크 통일(base.css 전역)
- 차트 팔레트 토큰 --chart-hot/cool/good/warn/rain(hex 하드코딩 제거, 온실·노지·공통 동일 색의미)
- 접근성: :focus-visible·prefers-reduced-motion·.sum-tab 40px
- UX 효과성·효율성: 촉각 피드백 scale(.975)·헤더버튼 40×40·앵커 scroll-margin·hover 어포던스
- 신규: C20 다중농가 클러스터 관제(723농가)+보고서PDF+일괄알림, c17_report·c14_report_pdf
- 최종검수: **41화면 콘솔에러·API4xx·깨진링크 0 · 백엔드 22엔드포인트 200 OK**

## 외부연동·챗봇·릴리스 (2026-06-09)
- **외부키 가이드**: `docs/INTEGRATION_GUIDE.md`(연동별 환경변수·미주입거동·단계활성화) + `check_integrations.py` 위성NDVI행 추가
- **C13 챗봇 고도화**: build_farm_context에 진단·역량·작황 주입 + 신규의도(진단/역량·작황/위성·경영전략), /chat 폴백→컨텍스트 rule-v2(LLM키 없이 동작)
- **v1.3 릴리스**: 39화면·71파일 zip + RELEASE_v1.3.md. 성능 FCP 420~520ms·load<600ms(목표 LCP<3s 충족)
- 최종검수: 39화면 0건·23 API 200 OK

## 사용자 여정 무단절 정합 (2026-06-09)
시설·노지 사용자가 가입→세팅→진단→운영→경영전략 전 구간 끊김 없이 이어지도록 단절 6건 해소.
- **노지**: C1 저장 CTA 농장유형 분기(노지→F8/F1, 온실→C16) · 온보딩 farm_type 영속화 · 역량 FIELD_SERVICES 치환 · F8을 맞춤메뉴/드로어 노출
- **시설**: 경영전략 고립섬(C5·C10) → `data.js _renderStratBand()` 교차연결 밴드(C17·C14·C5·C10·C9 상호) · C16 등록 후 'C17 진단 받기' CTA
- **여정지도**: `flow.html` 9단계 클릭형(분기·진단·역량·경영전략·학습환원) 갱신
- 위성 실측: `satellite_ndvi()` SATELLITE_NDVI_URL 주입 시 프록시→sentinel-2 자동전환
- F1 노지홈: 클러스터 작황 이상 → DecisionDeck 최우선 카드. 검수: 39화면 0건

## 노지 클러스터 작황 모니터링 (F8 신규, 2026-06-09)

### 무센서·위성/AI/기상 광역관리 — 3대 원칙 벤치마킹
- ① 무센서: 위성 식생지수(미연동 시 결정론적 프록시=필지ID해시+기상보정)+16일 기상 스트레스. source='satellite-proxy'→'sentinel-2' 자동전환
- ② 클러스터: 다수 필지(→다수농가·계약재배·정부사업·광역) 집계 — 평균NDVI·작황등급·**균일도**·이상필지
- ③ 진단→위치특정→실행: 필지 위치+클러스터 평균 대비 정량편차(Δ%)+심각도+실행지시(현장확인 원탭 기록)
- `api/services/field_cluster.py`·`GET /field/cluster`·`f8_cluster.html`(작황hero·균일도·기상스트레스·NDVI그리드·위치특정알림)
- 진입점: F1 노지홈 서브카드·역량 4단계 핵심서비스·네비게이터 F8. `docs/FIELD_CLUSTER_MONITORING.md`
- 검수: 경남창녕 4필지 2.3ha 작황우수·균일도69%, 2번필지 NDVI0.49 Δ-29.7% 생육저조 알림. **39화면 콘솔에러·API4xx·깨진링크 0건**

## 역량별 핵심 서비스 큐레이션 + 진단 추세 (2026-06-09)

### C19 역량 라우팅 (신규) — 현장컨설팅 단계 모델 벤치마킹
- `api/services/capability_router.py`: 진단→**4단계**(기반구축/데이터정착/정밀제어/경영고도화) 판정 + 단계별 핵심서비스 3~5개 + 다음단계 과제. 센서·데이터 기반 미충족 시 점수 높아도 1단계(기본부터) 강제
- `GET /capability`; `c19_capability.html`(스테퍼·진행바·서비스카드). 진입점: C3 홈 역량배너·C17 CTA·네비게이터 C19
- `docs/CAPABILITY_SERVICE_MAP.md`: 35+화면 과잉노출 방지·역량맞춤 라우팅 프로세스 정립

### 진단 이력·추세
- `GET /diagnosis/history`·`POST /diagnosis/snapshot`; 문진 저장 시 자동 스냅샷(같은날 갱신·24회)
- C17 추세 스파크라인(회차별 종합점수·전회比 ±N점), c17_report 회차별 추세표
- 검수: 추세 52→61→68→74(+6), 38화면 콘솔에러·API4xx·깨진링크 0건

## 진단·장기예보 확장 (2026-06-09)

### 16일 장기예보 + 노지 선행 의사결정
- `api/services/extended_weather.py`: Open-Meteo 16일(무키)·시군구→좌표·6h캐시·재해경보(강풍/호우/폭염/서리)
- `GET /environment/weather/extended`; F3 '16일 장기예보' 스트립(ET₀·일사·강수확률)
- `DecisionDeck.buildFieldHazards()`: 16일 재해→F1 노지 선행 결정카드(D-day·처방·원탭기록)

### 현장컨설팅 종합진단 (C17 확장 + C18 신규) — RDA 체크리스트 벤치마킹
- 출처: RDA/이암허브 현장컨설팅 체크리스트·결과보고서·소득333 농가사례(안성·고양·가평)
- `api/services/consulting_diagnosis.py`: **6대 도메인**(센서·구동기[환기/냉난방/스크린/양액]·재배·경영노동·유통·데이터) 점수+진단+ROI우선처방
- `GET/POST /diagnosis/checklist` + `api/data/diagnosis_checklist_schema.json`(30항목): 텔레메트리 외 항목(원수·필터·RO·유황훈증·병해충·인증) 현장 점검
- `_blend_checklist()`: 텔레메트리:현장=50:50, 불량→danger·주의→warn 처방 자동생성
- **C18 `c18_checklist.html`**(신규): 현장 문진 입력 / **C17**: 6도메인 카드+우선처방+원탭기록
- 폐루프 연결: **C14 월간리포트**(현장점검 진단 누적) + **C4 전문가컨설팅**(진단결과 자동첨부·추천전문가 자동선택)
- 검수: 양액·병해충 불량 입력→재배 75→38, danger 처방 1순위 승격. **전 35화면 콘솔에러·API4xx·깨진링크 0건**

---

## ★ 핵심 재정의 (2026-05-31 확정)

### P1~P6은 하루 관수 Period (Priority가 아님) — Grodan/Priva 일일 WC·EC 곡선 기반
| Period | 시간대 | 의미 | 핵심 지표 |
|--------|--------|------|-----------|
| P1 | 일출 전 (05:00~07:00) | 야간 dry-back 확인·첫 관수 산정 | EC/pH 기준값, 야간 dry-back 10~20% |
| P2 | 첫 관수·재포화 (일출 후 2~3h) | 큰 급액으로 염류 세척·EC↓ | 급액량 슬랩 4~6%, 첫 배액 前 |
| P3 | 오전 첫 배액 (≈400 J/cm²) | 최고 일사대에서 배액 EC 최저 | 배액률 20~30%, VPD |
| P4 | 정오 고부하·유지 (12:00~15:00) | 함수율 64~65% 유지 | 배액률 20~30%(고EC 25~50% 세척), 12%↓ 즉시추가 |
| P5 | 오후 dry-down (15:00~일몰) | 조기 종료·생식생장 유도 | 일몰까지 dry-back 2~5%, EC 상향 |
| P6 | 야간 dry-back (일몰~05:00) | 생식/영양 조절·뿌리 산소화 | dry-back 10~20%, 배액 0%, EC 상향(무관수 기본) |

**트리거는 일사 적산(J/cm²) 우선·시각은 폴백. 작업지시서의 P1/P2/P3 우선순위 표기는 전면 폐기.**
**(2026-06-02) P6 야간 dry-back 추가 — `components/data.js` PERIODS, getCurrentPeriod(야간 분기), base.css --p6-*, g3 jump-btn 셀렉터. 6화면 회귀 에러0.**

---

## 프로젝트 개요

- **프로젝트명**: KAASA SmartOS 모바일 최적화 + 데이터 연동 구현
- **목표**: 온실 농가가 스마트폰으로 P1~P5 관수 Period를 실시간 관리하고, AI 추천을 즉시 실행할 수 있는 모바일 퍼스트 시스템
- **기준 파일**: kaasa_smartos_wireframe_html.html (원본 와이어프레임)
- **산출물 위치**: C:\smart_farm\

---

## 핵심 아키텍처 결정

### 1. 산출물 구조 (단일 파일 → 분리 구조)
```
C:\smart_farm\
├── CLAUDE.md          ← 이 파일 (작업 메모리)
├── PROGRESS.md        ← 화면별 진행 상태
├── index.html         ← 전체 화면 네비게이터
├── components/
│   ├── base.css       ← CSS 변수, 공통 스타일
│   ├── components.css ← 컴포넌트 클래스 (KPI, To-do, Bottom Sheet 등)
│   └── data.js        ← 데이터 연동 레이어 (API 모킹 + 실제 연동 준비)
├── screens/
│   ├── g3_period.html ← ★ 핵심: P1~P5 관수 Period 관리 (최우선)
│   ├── c3_home.html   ← 통합 홈 (To-do 중심)
│   ├── g2_env.html    ← 환경제어
│   └── ...
└── releases/
    └── v*.zip
```

### 2. 데이터 연동 레이어 (3단계)
```
[센서/API 원천] → [data.js 연동 레이어] → [화면 렌더링]
     ↑                    ↑                      ↑
  실제 연동 시          Mock → Real 전환          Period 상태
  교체 가능             점진적 연동               시각화
```

### 3. 모델 연계 구조
- **Layer 0**: 농진청 표준모델 (정적 기준값 — JSON 파일로 제공)
- **Layer 1**: KAASA 현장학습모델 (API 호출 → 추천값 반환)
- **Layer 2**: 내 농장 맞춤모델 (농장별 보정 파라미터 적용)
- **data.js**가 이 3개 레이어를 순서대로 폴백(fallback) 처리

---

## G3 관수·양액 Period — 데이터 스펙

### 센서 데이터 (실시간)
| 항목 | 단위 | 정상 범위 | 경보 기준 |
|------|------|-----------|-----------|
| 급액 EC | dS/m | 2.5~3.5 | >4.0 또는 <2.0 |
| 배액 EC | dS/m | 3.0~4.5 | >5.0 |
| 배액률 | % | 20~30% | <15% (부족), >40% (과잉) |
| 급액 pH | — | 5.5~6.5 | <5.0 또는 >7.0 |
| 급액량 | mL/주 | Period별 상이 | 농장 기준값 ±20% |

### AI 모델 추천 입력값
- 현재 Period (P1~P5)
- 배액률 현재값
- 누적 DLI (일사량 누적)
- 실외 VPD 예측값
- 전일 수확량 대비 현재 생육단계

### AI 추천 출력값
- 추가 관수 여부 (boolean)
- 추천 급액량 (mL/주)
- 추천 EC 조정값 (dS/m)
- 신뢰도 점수 (0~100%)
- 추천 근거 (텍스트, max 50자)

---

## 검수 기준 (Verification Criteria)

### 1. 정확성 (Accuracy)
- AI 추천값이 농진청 표준모델 기준 ±15% 이내인지
- Period별 배액률 계산이 센서값과 일치하는지
- 경보 임계값이 설정값과 정확히 연동되는지
- 데이터 갱신 주기: 실시간(5초) / 집계(1분) / 일간(자정)

### 2. 사용성 (Usability)
- 온실 현장에서 장갑 낀 손으로 조작 가능한지 (터치 타겟 48px 이상)
- 현재 Period(P1~P5) 상태를 3초 이내에 파악할 수 있는지
- AI 추천 → 실행 → 결과 확인이 3탭 이내로 가능한지
- 에러/경보 상태가 색맹 사용자에게도 명확한지 (색상 + 아이콘 + 텍스트 3중 표현)

### 3. 효율성 (Efficiency)
- 첫 화면 로딩 3초 이내 (LCP < 3.0s, Slow 3G 기준)
- Period 전환 시 화면 갱신 1초 이내
- 관수 적용 버튼 → 실행 피드백 0.5초 이내
- 하루 관수 의사결정(P1~P5)에 소요되는 총 화면 조작 시간 < 2분

### 4. 효과성 (Effectiveness)
- 배액률 목표(20~30%) 달성 여부를 화면에서 즉시 확인 가능한지
- AI 추천 수용률 추적 (수용 vs 거부 비율 기록)
- Period별 실제 적용값 vs 추천값 편차 추적
- 농진청 표준 대비 내 농장 모델 정확도 비교 가능한지

---

## 결정 로그 (Decision Log)

| 날짜 | 결정 | 근거 | 결정자 |
|------|------|------|--------|
| 2026-05-31 | P1~P5를 관수 Period로 재정의 | 사용자 지시 | 사용자 |
| 2026-05-31 | 단일 HTML → 화면별 분리 | 컨텍스트 효율, 유지보수 | Claude |
| 2026-05-31 | data.js Mock → Real 전환 방식 | 점진적 연동 가능 | Claude |
| 2026-05-31 | G3 Period 화면을 최우선 구현 | 핵심 업무 빈도 최고 | 합의 |
| 2026-06-01 | 등급(티어) 차등 3계층 구현 | basic/smart/pro/enterprise SaaS 모델 | 합의 |
| 2026-06-01 | 글로벌 의사결정 UI 벤치마킹 → DecisionDeck | Priva·CropX·Source.ag 등 Top12 패턴 | 합의 |

## 등급 차등 & 의사결정 UI (2026-06-01)

### 등급 차등 (tier_features.json 기반)
- 레벨① index.html 맞춤메뉴+핵심그리드 잠금/배지 + 현재등급 칩
- 레벨② `components/tier_guard.js` 위젯 오버레이 — g2(VPD)·g3(드레인EC)·g4(수확예측)·g5(병해상세)·c5(이익률)·g6(AI출하)
- 레벨③ /billing/* + 402 게이팅 (백엔드 기존)
- 업그레이드 시트 → POST /billing/upgrade(manual) 실연동
- 검수: basic 잠금↑ / pro 해제, 콘솔 에러 0건

### DecisionDeck (글로벌 벤치마킹 적용)
- `components/decision_card.{css,js}` — `DecisionDeck.render(el, items, {onApply})`
- C3 홈 "오늘의 결정": 이상감지(배액률·VPD)+AI추천 통합, 심각도3중코딩+처방+신뢰도+출처+신선도+원탭(→/activity 폐루프)
- 벤치마킹 정리: `docs/UI_BENCHMARK.md`

### 벤치마크 Top12 전부 적용 (2026-06-01 2차)
- DecisionDeck → g1·f1 확장 (빌더 buildGreenhouse/buildField)
- `band_chart.js`(의존성0 SVG): g3 배액률 목표대 밴드 음영 (패턴6)
- `device_alert.js`: c3·g2 기기/연결 알림을 데이터 알림과 분리 (패턴12)
- F2 GIS: peelable 레이어 토글(필지경계/토양수분/NDVI) + 값 히트맵 (패턴7·8)
- 전 화면(10) 콘솔 에러 0건 회귀검수 통과

## 운영 기록 입력 + 기자재 통합 (2026-06-02)

### 운영 기록 폐루프 (RecordSheet)
- `components/record_sheet.js`: RecordSheet.open/logActivity/renderRecent
- 입력 화면: F4(관개)·F6(방제)·F7(필지수확)·G2(환경설정)·G3(관수)·G4(생육측정)·F3(작업계획) → POST /activity
- 각 화면 '최근 기록' 타임라인 (GET /activity/summary recent[])
- C4(전문가 consult)·C12(공동출하 joint_ship+물량/등급)·C2(consent) 실제 서버 적재
- C14 월간리포트: 이행 활동 상세(by_kind 칩)+최근기록 + 학습기여 재학습 트리거 연동(remaining_rows·near_retrain 배지)

### 시설 기자재 + 이기종 통합 (C16 신규)
- `docs/EQUIPMENT_INTEGRATION.md` + `api/data/equipment_schema.json`(8군·프로토콜·표준변수22)
- `screens/c16_equipment.html`: 장비 등록 + 데이터포인트→canonical_name 매핑
- 백엔드: GET /equipment/schema·GET/POST/DELETE /equipment (data/equipment/{farm}.json)
- C1 저장 후 CTA로 C16 연결 / `equipment_link.js`로 G2·G3에 '연동 장비' 배지 + device_alert 연계
- 전 32화면 콘솔 에러 0건 회귀검수 통과

## 사업계획서 정합 + 종합진단 (2026-06-04)

### 프리바 관수 정밀화 (PDF/매뉴얼 벤치마킹)
- P6 야간 dry-back 추가(일일 6단계 곡선) + 일사적산(J/cm²) 트리거
- `data.js` IRRIGATION_START(시작조건 우선순위)·IRRIGATION_STRUCTURE(시작프로그램→밸브그룹→밸브·처방 EC/pH·유량 사전제어)
- 백엔드: irrigation_adapter `dryback_night_pct` 계산, IrrigationPayload period le=6, store 등록

### 사업계획서(SFROP v2.0) 반영 — `docs/BUSINESS_PLAN_ALIGNMENT.md`
- C13 챗봇 UC1~UC10 활용사례 칩 + RAG 출처
- C16 물리 캘리브레이션(액추에이터 응답·명령-실반응 편차)
- **C17 시스템 종합진단(신규)**: GET /diagnosis — 장비·연동·데이터·운영·캘리브 5영역 점수 + ROI 개선 우선순위
- overview 5대 농가문제·효과 / G2 AI에이전트 빠른루프(에너지 자동절감·LED) / G3 다층 시간창(7·14·작기)
- F5 원격탐사 → 현장확인 기록 폐루프 통합
- 전 33화면 콘솔 에러 0건

### 인트로·메뉴·연결 무결성 (2026-06-04)
- `screens/intro.html` + `/intro` 라우트: 시스템 소개 랜딩(가치제안·5대문제·6층·CTA)
- 전역 기능형 드로어(data.js 자동주입): ≡ 메뉴 → 검색·등급칩·빠른이동22·농장전환·로그아웃 (전 33화면)
- **버그 수정**: intro CTA 상대경로 404 / 전 화면 `../index.html`→`/index.html` 401 (→ /index.html 네비게이터 서빙+공개경로)
- 정밀 감사(실제 URL 해석+인터랙션+쓰기경로): 37경로·35링크 200, 콘솔/API/깨진링크 0건

### 외부 의존 개선 (LLM·실측 없이도 동작)
- C13 챗봇: `farmer.py /chat` stub + `ai_chat._rule_based_reply` 실데이터 의도응답(관수·환경·에너지·수확·수익·병해·알림). 키 주입 시 LLM 고도화
- F5: 활력셀을 `/field/soil` 실측 토양수분 파생(흙토람 연동 시 자동 실측)

---

## 완료된 화면 (2026-06-01 — 원본 28개 100% 완성)

| 모듈 | 화면 | 실연동 여부 |
|------|------|-----------|
| 공통 C (13) | C0 C1 C2 C3 C4 C5 C6 C7 C8 C9 C10 C11 C12 | C3·C4·C5·C6·C12 실연동, 나머지 auth/Mock |
| 온실 G (6) | G1 G2 G3 G4 G5 G6 | 전부 실연동 |
| 노지 F (7) | F1 F2 F3 F4 F5 F6 F7 | F1·F3·F4·F6·F7 실연동, F2·F5 Mock |
| 개요 (2) | overview.html, flow.html | 정적 |
| 네비게이터 | index.html → /smartos | 28화면 완료 배지 |

- 전 화면 **표준 하단 5탭**(홈/온실/노지/출하/메뉴) 통일 · 죽은 링크 0건 · 콘솔 에러 0건
- 표준 템플릿: `_ensureToken()` 자동로그인(admin/1250) + `KaasaData` 레이어 + Playwright 검수
- Mock 부분은 화면에 라벨 명시 (노지 토양수분·필지 GIS·원격탐사, C6~C10 일부)

## 백엔드 수정 누적 (2026-06-01)

- `api/services/irrigation_store.py` — DB 컬럼명 수정, PostgreSQL 실저장
- `api/routers/farmer.py` — Priva ET0 500 버그 수정
- `api/main.py` — /screens /components 마운트, KAMIS 일일 스케줄러
- `api/middleware/auth.py` — /screens /components /smartos 공개
- `pipeline/nightly_db_etl.py` — IRR canonical_name + --since 옵션
- `pipeline/kamis_fetcher.py` — ITEM_CODE 전면 수정 + 단위 환산 + 평일 소급
- `components/data.js` — horizon_days 30, 빈 recs 폴백, 농진청표준 강화
- `scripts/tune_stage1_strawberry.py` — Optuna (R² 0.244→0.284)

## 다음 세션 작업 (우선순위)

- [ ] C12 공동출하 화면 구현
- [ ] Lighthouse LCP < 3.0s 검수
- [ ] 실기기 QR 테스트 환경 구성
- [ ] ERA5 실측 CSV 확보 → 딸기 Stage1 재학습 (R² > 0.45)
- [ ] KAMIS 딸기 비수기 → 성수기 전환 시 단가 자동 반영 확인

## 미해결 Backlog

- [ ] KAASA 실제 API 엔드포인트 확인
- [ ] 농진청 표준모델 JSON 수신 방법
- [ ] 실기기 MQTT 연결 테스트
- [ ] kaasa_smartos_mobile.html (90KB 단일 파일) → 분리 작업 계획

---

## 다음 세션 시작 메시지 템플릿

```
CLAUDE.md를 읽고 시작합니다.
오늘 목표: [화면명] 완성
현재 상태: PROGRESS.md [해당 항목] 참조
주의사항: [특이사항]
```


## 최종 구현 현황 (2026-06-01)

### 화면 33개 (원본 28 + AI챗봇·월간리포트·교육·기타)
- 공통 C: C0~C12 + c13(AI챗봇) + c14(월간리포트) + c15(교육)
- 온실 G: G1~G6 / 노지 F: F1~F7 / 개요: overview·flow

### 작물 12종
딸기·방울토마토·완숙토마토·참외·파프리카·오이 + 제주7종(감귤·월동무·당근·양배추·브로콜리·마늘·양파)

### 정책(스마트농업법) 대응 — 기능 이행 완료
- 6대 영역 통합 모니터링 / 9대 성과지표(목표대비+전월대비 변화율)
- 월간 경영성과 리포트(제5·6·9조) / 교육과정·이수율(제8조)
- 결로·IPM 조기경보 / AI진단·전문가 컨설팅(C4)
- **이행→축적→학습→환원 폐루프**: activity 적재→retrain_trigger→report 학습블록→C7 보상

### 외부 의존 잔여 (코드 구조 완비, 키/데이터만 주입하면 자동 전환)
- 노지 토양·필지·NDVI 실데이터(흙토람·팜맵 키+IP) / LLM 챗봇 실응답(.env 키)
- 제주작물 M2 수확모델(생산 실측) / 전월 변화율 실수치(월 누적)

### 신규 백엔드 (이번 세션)
- GET /report/monthly, POST /activity, GET /activity/summary
- GET /field/soil, /field/parcels (흙토람·팜맵 어댑터+Mock폴백)
- external_api_hub: naas_soil_by_pnu, farmmap_parcels
- crop_config 제주7종, kamis_fetcher ITEM_CODES 제주7종
