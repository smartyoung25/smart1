# 작물별 시연 가이드 (KAASA SmartOS)

> 단일 데모계정(**admin / 1250**, 자동로그인) + 드로어 "농장 전환"으로 작물 전환.
> 공개 URL은 `deploy/cloudflare/current_url.txt` 참조(퀵터널·재시작 시 변경).
> 아래 경로는 `<BASE>` = `http://localhost:8000` 또는 공개 URL 뒤에 붙임.

## 한눈에 — 작물별 데모 농장

| # | 작물 | farm_id | 지역 | 비고 |
|---|------|---------|------|------|
| 1 | 🥒 오이 | `farm_001` | 경남 창녕 | 기본농장·M2 CV R²0.39(권위 stage2_meta) |
| 2 | 🍅 방울토마토 | `farm_002` | 충북 충주 | |
| 3 | 🍓 딸기 | `farm_003` | 전북 군산 | ★ERA5 보강 M2 |
| 4 | 🍅 완숙토마토 | `farm_004` | 경북 상주 | |
| 5 | 🫑 파프리카 | `강원_철원_파프리카_8_1` | 강원 철원 | |
| 6 | 🌱 제주(노지 실데이터) | `제주_한경_딸기_57_1` | 제주 한경 | ★흙토람·팜맵 실데이터 |

## 시연 동선 (작물 1개 기준)
1. **농장 전환**: 우상단 ≡ → "농장 전환 · 작물별 온실 데모" → 작물 선택 (페이지 자동 새로고침)
2. **G1 온실 홈**: 오늘의 결정(DecisionDeck)·수확 D-day·매출
3. **G2 환경제어**: 실내환경 + ★평년 대비 외부기상 카드(ERA5)
4. **G3 관수·양액**: P1~P6 곡선·배액률·EC(작물별 상이)
5. **G4 생육·수확예측**: M1/M2 모델
6. **C6 학습**: 모델 게이트표(딸기 🛰️ERA5↑)

## 작물별 바로가기 딥링크 (로그인 자동)
> `<BASE>` 뒤에 붙여 사용. farm 파라미터로 작물 고정.

### 🥒 오이 (farm_001)
- `<BASE>/screens/g1_home.html?farm=farm_001`
- `<BASE>/screens/g3_period.html?farm=farm_001` (관수)
- `<BASE>/screens/g2_env.html?farm=farm_001` (평년기상)

### 🍓 딸기 (farm_003) — ERA5 개선 모델
- `<BASE>/screens/g1_home.html?farm=farm_003`
- `<BASE>/screens/g4_growth.html?farm=farm_003` (수확예측)
- `<BASE>/screens/c6_learning.html` (게이트표: 딸기 ERA5↑)

### 🍅 완숙토마토 (farm_004)
- `<BASE>/screens/g1_home.html?farm=farm_004`
- `<BASE>/screens/g6_harvest.html?farm=farm_004` (수확·유통)

### 🍅 방울토마토 (farm_002) / 🫑 파프리카
- `<BASE>/screens/g1_home.html?farm=farm_002`
- `<BASE>/screens/g2_env.html?farm=%EA%B0%95%EC%9B%90_%EC%B2%A0%EC%9B%90_%ED%8C%8C%ED%94%84%EB%A6%AC%EC%B9%B4_8_1` (파프리카 평년)

### 🌱 제주 노지 실데이터 (제주_한경_딸기_57_1)
- `<BASE>/screens/f4_soil.html?farm=%EC%A0%9C%EC%A3%BC_%ED%95%9C%EA%B2%BD_%EB%94%B8%EA%B8%B0_57_1` (🟢흙토람 실데이터)
- `<BASE>/screens/f2_gis.html?farm=%EC%A0%9C%EC%A3%BC_%ED%95%9C%EA%B2%BD_%EB%94%B8%EA%B8%B0_57_1` (🟢팜맵 실데이터)
- `<BASE>/screens/f3_weather.html?farm=...` (감귤 등 노지 평년 카드)

## 광역 시연 (작물 무관)
- **F8 클러스터 작황**: `<BASE>/screens/f8_cluster.html` — 다필지 작황+★광역 이상기상 진단(가뭄/폭염 시 알림 상향)
- **C20 다중농가 관제**: `<BASE>/screens/c20_cluster_admin.html` — 725농가 샘플 시뮬레이션
- **전체 네비게이터**: `<BASE>/smartos`

## 평년 기상 카드 지원 26작물 (G2·F3·F8 자동)
온실 6(딸기·참외·방울토마토·완숙토마토·오이·파프리카) · 노지채소 9(감귤·월동무·당근·양배추·마늘·양파·배추·무·대파) · 과수 5(사과·배·복숭아·감·포도) · 주식고소득 6(벼·고추·콩·감자·고구마·수박)
> 농장 작물이 위 중 하나면 해당 화면에서 평년 카드 자동 표시. 데모 농장이 없는 작물은 climatology 데이터·엔드포인트로 지원.
