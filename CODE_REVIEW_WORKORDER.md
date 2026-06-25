# 코드리뷰 작업지시서 (2026-06-26)

> 리뷰 범위: farmer.py 분리모듈 / PC 관리자 콘솔 JS / PUBLIC_DEMO 보안 게이트 / 서비스 레이어
> 방식: 4개 병렬 에이전트 정밀 리뷰 + 핵심 발견 직접 재검증. **추정 없음, 코드 확인 완료분만 수록.**
> 사용법: 기존 세션에서 이 파일을 열고 우선순위 순으로 처리. 각 항목 `[ ]` → `[x]`.

---

## 🔴 P0 — 보안 (즉시 검토 필요, 운영 공개도메인)

### [x] 1. PUBLIC_DEMO 관리자 쓰기 게이트가 문서화된 불변식("/api/admin/* 전부 403")을 위반

**근거 파일**
- `api/main.py:88` — `_ADMIN_BLOCK_CONTAINS = ("/models/promote", "/models/rollback")`
- `api/main.py:97-100` — admin 분기: `blocked = (method in _WRITE) and (heavy or method == "DELETE")`
- `api/middleware/auth.py:153-164` — `require_admin_view`가 `role == "demo"`를 **모든 메서드** 통과시킴
- `api/routers/auth.py:308-340` — 누구나 `POST /api/v1/auth/demo-token` 으로 `role=demo` 토큰 발급 가능

**문제**
- CLAUDE.md 불변식과 `main.py:78` 주석은 "`/api/admin/*` 관리자 쓰기 항상 403"이라 명시하지만, 실제 게이트는 **deny-list 방식**이라 promote/rollback/DELETE 외 모든 admin POST/PUT/PATCH를 통과시킴.
- `auth.py:316` docstring은 "require_admin_view가 demo 역할의 **GET만** 허용"이라 적혀 있으나, `middleware/auth.py:163`은 메서드 구분 없이 통과 → **주석이 거짓**. 결국 admin 쓰기를 막는 유일한 방어선은 deny-list뿐.
- 결과: 익명 사용자가 demo 토큰을 받아 아래 admin 쓰기 도달 가능 (직접 검증 완료):
  - `POST /api/admin/billing/set-tier` (`api/routers/billing.py`, `main.py:120`에서 `/api/admin` 마운트) — **임의 농가 구독 tier 변경(실데이터 변조)**
  - `POST /api/admin/cluster/notify` (`admin.py:1676`) — 디스크에 공지 무한 append(디스크 고갈) + SLACK/COOLSMS 키 설정 시 **공격자 내용으로 실제 알림 발송**
  - `POST /api/admin/prices/refresh` (`admin.py:1071`) — 외부 KAMIS API 호출 + 캐시 재기록 무제한 트리거
- `_ADMIN_BLOCK_CONTAINS`의 `/models/promote`는 **존재하지 않는 라우트**(admin.py에 promote 핸들러 없음) → deny-list가 라우트와 동기화 안 됨을 입증.

**조치 (택1, 사용자 의도 확인 권장)**
- (A·권장) 불변식 복원: admin 분기를 `blocked = method in _WRITE` 로 변경 → 모든 admin 쓰기 차단. 데모에 꼭 필요한 안전 쓰기가 있으면 **정확경로 allow-list**로 명시 개방(현 deny-list 폐기).
- (B) 현 설계 유지 시: ① `auth.py:316` docstring 수정(거짓 제거), ② `require_admin_view`에서 demo는 GET/HEAD만 통과하도록 메서드 가드 추가, ③ `billing/set-tier`·`cluster/notify`·`prices/refresh`에 데모 가드 추가.
- `_ADMIN_BLOCK_CONTAINS`의 죽은 `/models/promote` 항목 제거.

> ⚠️ 이 항목은 설계 변경 가능성이 있어, 수정 전 "데모에서 admin 쓰기 허용이 의도인지" 사용자에게 1줄 확인 후 진행.

---

## 🟠 P1 — 프론트 화면 깨짐 (사용자 직접 도달)

### [x] 2. parcels_jeju.json bare `NaN` → 제주 농가 `/field/parcels` 프론트 JSON.parse 실패

**근거**
- `api/data/real/parcels_jeju.json` 259, 1417, 1423, 1429, 2197, 2311, 2323행 — `"crop": NaN`
- `api/routers/farmer_irrigation.py:435` `json.loads`(Python은 NaN 허용) → `:456` parcels 그대로 반환 → `GET /field/parcels`(`:481`)가 FastAPI 직렬화 시 리터럴 `NaN` 토큰 출력 → 엄격 `JSON.parse` 거부.
- farm_registry에서 이미 겪은 동일 버그 클래스. 제주 노지 농가 영향.

**조치**
- JSON의 7개 `NaN` → `null`(또는 `""`)로 치환.
- 추가 방어: `_real_parcels_lookup` 반환 직전 parcel 레코드 NaN 새니타이즈.

### [x] 3. console_cluster.js — 필터 1회 변경 후 드롭다운 영구 공백

**근거**: `components/console_cluster.js:97`(전체 `root.innerHTML` 재구성) + `:114-124`
- `render()`가 매번 `<select id="ccRegion">`/`<select id="ccCrop">`를 빈 채로 재생성하는데, 옵션 채우기(116-118)가 `if (!state.inited)`로 게이트됨. 첫 렌더 후 `state.inited=true` → 이후 reload(필터 변경)마다 else 분기(121-123)가 빈 select에 `.value`만 설정 → **옵션 0개**.

**조치**: `state.inited` 게이트 제거하고 `render()`에서 항상 옵션 채운 뒤 선택값 복원:
```js
fr.innerHTML = '<option value="">전체 지역</option>' + (d.regions||[]).map(...).join('');
fc.innerHTML = '<option value="">전체 작목</option>' + (d.crops||[]).map(...).join('');
fr.value = state.region || ''; fc.value = state.crop || '';
```

### [x] 4. console_satellite.js — null NDVI에 `.toFixed()` → 위성 뷰 전체 블랭크

**근거**: `components/console_satellite.js:78-79`(heatmap, title+타일 라벨 2회) + `:92`(parcelTable) — `p.ndvi.toFixed(2)` 무가드. `:79` `heatColor(p.ndvi)`도 null 산술 → NaN 색. 같은 파일 `:108` alertsTable은 `a.ndvi != null ? ... : '–'` 가드가 있어 **불일치**.
- 신규 필지/미동기 proxy 필지의 null ndvi 시 `TypeError` → `root.innerHTML` 할당 중단 → 화면 블랭크.

**조치**: `alertsTable` 패턴과 동일하게 `var ndvi = (p.ndvi != null ? p.ndvi : 0);` 후 `ndvi.toFixed(2)`/`heatColor(ndvi)` 사용, 또는 null 타일 `–` 처리.

---

## 🟡 P2 — 로직 결함 (조용히 동작 안 함)

### [x] 5. pdca.py — 드리프트 신호 사망 (딕셔너리 키 불일치)

**근거**: `api/services/pdca.py:198` 및 `:582` — `badge.get("level", "green")`. 그러나 `drift_monitor.py:331-346` `summary_badge()`는 키 `"alert"`로 반환(`:340`), `"level"` 키 없음 → **항상 "green"**.
- 영향: ① `:199` `drift_penalty` 항상 `0.0`(드리프트가 PDCA 점수에 영향 없음), ② `_drift_summary_all`이 모든 작목 green 처리 → `needs_correction` 트리거(`:646`, red ≥2 작목 시) **영구 미발동**.

**조치**: 두 줄 모두 `badge.get("alert", "green")`로 변경.

### [x] 6. pdca.py — drift_detail에 bare `NaN` 직렬화 → JSON 응답 깨짐

**근거**: `api/services/pdca.py:200` `drift_detail.append({..., "mape": stats.mape})`. `stats.mape`는 작목 harvest 레코드 `_MIN_SAMPLES`(3) 미만 시 `float("nan")`(`drift_monitor.py:265-280`). `drift_detail`은 응답(`:215`)에 그대로 포함되며 admin.py와 달리 `_finite` 새니타이저 없음.

**조치**: 직렬화 전 NaN→None. 예: `"mape": (stats.mape if math.isfinite(stats.mape) else None)` 또는 응답 전체 `_finite` 재귀 처리.

---

## 🔵 P3 — 견고성 / 정리 (낮음)

### [x] 7. main.py — `_WRITE_ALLOW_CONTAINS` 부분문자열 매칭 과허용

**근거**: `api/main.py:85` `_WRITE_ALLOW_CONTAINS = ("/equipment/", "/whatif")` — `c in path`(부분문자열). `/whatif`가 세그먼트 미고정이라 `/api/.../whatif-admin` 같은 미래 경로도 쓰기 허용될 수 있음. `_WRITE_ALLOW_SUFFIX`(`:79`)의 `endswith`도 동일 류.

**조치**: `/` 분할 세그먼트 비교 또는 정확경로 매칭으로 강화.

### [x] 8. console_cluster.js — summary 부분 응답 시 `'undefined점'` 표시

**근거**: `components/console_cluster.js:45`(`s.avg_diag + '점'`) + `:99`. summary에 `avg_diag`/`avg_vigor` 누락 시 `"undefined점"`/리터럴 `"undefined"` 표시(크래시 아님, 미관 결함).

**조치**: `!= null ? ... : '–'` 가드.

### [x] 9. drift_monitor.py — 정렬 키 `None[:10]` 잠재 TypeError

**근거**: `api/services/drift_monitor.py:102` `(r.get("harvest_date") or r.get("recorded_at", ""))[:10]`. `recorded_at`가 존재하지만 `null`이고 `harvest_date`도 없으면 `None[:10]` → TypeError. 안전 형태는 `data_collection.py:640`의 `(... or r.get("recorded_at") or "")[:10]`. 현재 writer가 항상 비-null 기록이라 저위험(잠재).

**조치**: `(r.get("harvest_date") or r.get("recorded_at") or "")[:10]`.

---

## ✅ 검증 결과 — 이상 없음 (재확인 완료, 조치 불필요)

- **farmer.py 분리(P2-C)**: 전 검증 통과. 헬퍼 NameError 없음, 라우터 단일 공유객체(`farmer_state.router`)에 side-effect import로 정상 등록(44라우트), 중복 (path,method) 0건, 순환 import 없음, `_equipment_path` 공유 정상.
- **region_canon.py**: 충남/충청남도→충청남도, 전북→전북특별자치도, junk/공백→미상 병합 로직 정상. `"도"` 전역 strip 안전.
- **cluster_overview.py**: 나눗셈 가드(`len or 1`, count≥1) 정상. farm_registry 716농가 sido/crop NaN 0.
- **model_loader.py / climate_plan.py / anomaly_detector.py / persistence.py**: `.get()` 기본값·try/except·UTF-8·`ensure_ascii=False` 일관. persistence 중복 할당 이미 제거됨.
- **콘솔 JS XSS**: 모든 API 유래 문자열 `esc()` 통과. 이벤트 리스너 누수 없음(전체 innerHTML 재구성으로 GC). 중복 ID 없음. 다크모드·≤1100px 반응형 정상.

---

## 처리 순서 권장
1. **P0-1** 보안 — 의도 확인 후 즉시 (운영 공개도메인 노출).
2. **P1-2,3,4** 화면 깨짐 — 사용자 직접 도달, 빠른 수정.
3. **P2-5,6** pdca 로직 — 드리프트 기능 복구.
4. **P3-7,8,9** 정리 — 여유 시.

> 수정 후: SW 캐시 버전 bump(콘솔 JS 변경 시), 콘솔 에러 0 / API 4xx 0 재검수.
