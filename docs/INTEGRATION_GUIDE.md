# 외부 데이터 연동 가이드 (실측 전환)

> 모든 연동은 **키/URL만 `.env`에 주입하면 코드 수정 없이 자동 전환**되도록 설계됨.
> 미주입 시 폴백(Mock·프록시·규칙형)으로 동작. 점검: `python scripts/check_integrations.py`

## 한눈에 보기
| 연동 | 환경변수 | 미주입 거동 | 주입 후 |
|------|----------|------------|---------|
| KAMIS 도매시세 | `KAMIS_API_KEY` | rda_static 폴백 | 실시간 도매가 |
| KMA 기상/ASOS | `KMA_SERVICE_KEY` | 계절 추정 | ASOS 실측 ET₀ |
| 공공데이터(NCPMS·aT·RDA) | `DATA_GO_KR_SERVICE_KEY` | Mock | 병해충·경락가 |
| 농진청 작물·병해 표준 | `RDA_API_KEY` | 내장 표준값 | 실시간 표준 |
| 흙토람 토양 | `NAAS_SOIL_API_URL` | Mock 토양수분 | 실측 토양 |
| 팜맵 필지 | `FARMMAP_API_URL` | Mock 필지 | 실측 경계 |
| **위성 NDVI 작황(F8)** | `SATELLITE_NDVI_URL` (+`_KEY`) | 결정론 프록시 | **sentinel-2 실측** |
| 16일 장기예보(F3) | (없음·무료) | Open-Meteo 상시 | — |
| AI 챗봇 LLM | `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` | 규칙형 응답 | LLM 응답 |
| 알림 | `SLACK_WEBHOOK_URL`·`COOLSMS_*`·`SMTP_*` | 미발송 | 실발송 |

## 단계별 활성화

### 1. 위성 NDVI 작황 (F8 클러스터 — 프록시→실측)
```
SATELLITE_NDVI_URL=https://<게이트웨이>/ndvi   # GET ?adm= 지원
SATELLITE_NDVI_KEY=<선택: Authorization Bearer>
```
응답 형식(자동 정규화): `{"parcels":[{"name","ndvi"}]}` / `{"name":ndvi}` / `[{"name","ndvi"}]`
- **Sentinel Hub Statistical API**(OAuth)는 토큰을 붙여 위 형식으로 반환하는 얇은 게이트웨이를 두고 그 URL을 지정.
- 주입 즉시 `/field/cluster` source가 `satellite-proxy`→`sentinel-2`, F8 배지·F1 결정카드 실측 전환.

### 2. 노지 실측 (흙토람·팜맵)
```
NAAS_SOIL_API_URL=<data.go.kr 흙토람 토양특성 OpenAPI>
FARMMAP_API_URL=<팜맵 농경지전자지도 OpenAPI>
DATA_GO_KR_SERVICE_KEY=<공공데이터포털 인증키>   # 팜맵 serviceKey 공용
```

### 3. 시세·기상 (KAMIS·KMA)
```
KAMIS_API_KEY=<KAMIS 인증키>      # 없으면 pipeline/kamis_fetcher 캐시·rda_static
KMA_SERVICE_KEY=<기상청 ASOS키>   # 없으면 계절 추정 ET₀
```

### 4. AI 챗봇 LLM (C13)
```
ANTHROPIC_API_KEY=sk-ant-...      # 우선
OPENAI_API_KEY=sk-...             # 대체
# 또는 로컬: OLLAMA_ENABLED=true + `ollama pull llama3.2`
```
미주입 시에도 규칙형 응답이 **실데이터(관수·환경·진단·역량·작황·경영전략)** 기반으로 동작.

### 5. 알림 (조기경보·리포트 발송)
```
SLACK_WEBHOOK_URL=...
COOLSMS_API_KEY=... / COOLSMS_API_SECRET=...
SMTP_USER=... / SMTP_PASSWORD=...
```

## 점검 방법
```
python scripts/check_integrations.py    # 연동별 LIVE/폴백/미설정 + 활성화 경로
python scripts/smoke_test.py            # 핵심 엔드포인트 200 스모크
```
주입 후 서버 재기동 → 위 스크립트로 🟢 전환 확인.
