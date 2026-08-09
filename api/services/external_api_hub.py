"""외부 API 통합 허브 (External API Hub).

연결된 API 목록
───────────────
[키 보유 — 즉시 사용 가능]
  A1. KMA  기상청 ASOS          → kma_service.py 연동 (ET₀, 기상예보)
  A2. KAMIS 농산물가격정보      → kamis_fetcher.py 연동 (실시간 도매가)
  A3. RDA  농촌진흥청           → 생육 기준값·작물 표준·병해충 정보
  A4. AIHub 인공지능허브        → 병해 이미지 데이터셋 API
  A5. data.go.kr 공공데이터포털 → 농업 통계 복합조회
  A6. NCPMS 병해충관리시스템    → DATA_GO_KR_SERVICE_KEY 사용 (기존)
  A7. aT 도매시장 경락가격      → DATA_GO_KR_SERVICE_KEY 사용 (기존)

[키 없음 — 무료 외부 API (키 불필요)]
  B1. Open-Meteo            → 글로벌 기상예보 (무료, 무제한)
  B2. EPPO Global Database  → 병해충 위험 알림 (EU, 무료)
  B3. FAO FAOSTAT/GAEZ      → 작물 수확량·가격 통계 (무료)
  B4. PlantNet API          → 식물 식별 (1일 500회 무료)
  B5. NASA POWER API        → 글로벌 태양복사·기온 이력 (1984~현재, 무료)
  B6. World Bank Commodity  → 국제 농산물 가격지수 (무료)

[키 없음 — 연결 방법 안내]
  C1. Anthropic Claude API  → AI 채팅 (ANTHROPIC_API_KEY)
  C2. OpenAI API            → AI 채팅 대체 (OPENAI_API_KEY)
  C3. Ollama                → 로컬 LLM (설치만 하면 무료)
  C4. Slack Webhook         → 알림 채널 (SLACK_WEBHOOK_URL)
  C5. Plant.id API          → M5 이미지 병해 탐지 (PLANT_ID_API_KEY, $9/월)
  C6. USDA NASS             → M2 수확량 기준 (USDA_NASS_API_KEY, 무료)
  C7. NAAS 농협유통정보     → 산지 가격 (NAAS_API_KEY, 승인 필요)

[MCP 서버 연결 방법]
  D1. Anthropic MCP         → Claude Code MCP 서버 추가
  D2. Agricultural MCP      → FAO/CGIAR 기반 작물 지식그래프
  D3. Open-Meteo MCP        → 기상 데이터 MCP 서버
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Any, Optional

logger = logging.getLogger(__name__)
_lock = Lock()
_cache: dict[str, tuple[Any, float]] = {}   # {key: (data, expire_ts)}


def _cached(key: str, ttl_sec: int, fetch_fn):
    """간단한 인메모리 TTL 캐시."""
    import time
    with _lock:
        if key in _cache:
            data, exp = _cache[key]
            if time.time() < exp:
                return data
    try:
        data = fetch_fn()
        with _lock:
            _cache[key] = (data, time.time() + ttl_sec)
        return data
    except Exception as e:
        logger.warning("[ext_api] %s fetch failed: %s", key, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# A3. 농촌진흥청 (RDA) — 작물 생육 기준 + 병해충 정보
# ══════════════════════════════════════════════════════════════════════════════

_RDA_BASE = "https://api.nongsaro.go.kr/service"

def _rda_key() -> str:
    return os.environ.get("RDA_API_KEY", "")


def rda_get_crop_growth_standard(crop_name_ko: str) -> Optional[dict]:
    """농촌진흥청 작물 생육 기준 데이터 조회.

    RDA 농업기술포털 (nongsaro.go.kr) 작물정보 서비스:
      https://api.nongsaro.go.kr/service/cropInfo/cropFarmingList

    Returns:
        {"crop": str, "standard": dict, "source": "rda_nongsaro"}
        None if API unavailable
    """
    key = _rda_key()
    if not key:
        return None

    def _fetch():
        params = urllib.parse.urlencode({
            "apiKey": key,
            "cropNm": crop_name_ko,
            "returnType": "json",
        })
        url = f"{_RDA_BASE}/cropInfo/cropFarmingList?{params}"
        with urllib.request.urlopen(url, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        items = raw.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        return {"crop": crop_name_ko, "items": items, "source": "rda_nongsaro",
                "count": len(items)}

    return _cached(f"rda_crop_{crop_name_ko}", 86400, _fetch)


def rda_get_pest_info(crop_name_ko: str) -> Optional[dict]:
    """농촌진흥청 작물별 병해충 정보 조회.

    RDA 농업기술포털 병해충정보 서비스:
      https://api.nongsaro.go.kr/service/pestInfo/pestInfoList

    Returns:
        {"crop": str, "pests": [...], "source": "rda_pestinfo"}
    """
    key = _rda_key()
    if not key:
        return None

    def _fetch():
        params = urllib.parse.urlencode({
            "apiKey": key,
            "cropNm": crop_name_ko,
            "returnType": "json",
        })
        url = f"{_RDA_BASE}/pestInfo/pestInfoList?{params}"
        with urllib.request.urlopen(url, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        items = raw.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        return {"crop": crop_name_ko, "pests": items, "source": "rda_pestinfo",
                "count": len(items)}

    return _cached(f"rda_pest_{crop_name_ko}", 86400, _fetch)


# ══════════════════════════════════════════════════════════════════════════════
# A4. AIHub — 병해 이미지 데이터셋 API
# ══════════════════════════════════════════════════════════════════════════════

_AIHUB_BASE = "https://api.aihub.or.kr"

def _aihub_key() -> str:
    return os.environ.get("AIHUB_API_KEY", "")


def aihub_list_datasets(keyword: str = "병해") -> Optional[list]:
    """AIHub 데이터셋 검색.

    AIHub 개방 데이터셋 목록 조회:
      https://api.aihub.or.kr/openapi/dataset/list

    농업 관련 병해 이미지 데이터셋 목록을 반환한다.
    """
    key = _aihub_key()
    if not key:
        return None

    def _fetch():
        params = urllib.parse.urlencode({
            "apiKey": key,
            "keyword": keyword,
            "dataType": "IMAGE",
            "page": 1,
            "pageSize": 20,
        })
        url = f"{_AIHUB_BASE}/openapi/dataset/list?{params}"
        req = urllib.request.Request(url, headers={"apiKey": key})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return raw.get("result", raw.get("data", []))

    return _cached(f"aihub_list_{keyword}", 86400, _fetch)


# ══════════════════════════════════════════════════════════════════════════════
# B1. Open-Meteo — 글로벌 기상 예보 (키 불필요, 무료)
# ══════════════════════════════════════════════════════════════════════════════

# 한국 주요 스마트팜 지역 좌표
_FARM_COORDS: dict[str, tuple[float, float]] = {
    "farm_001": (35.53, 128.49),   # 경남 창녕
    "farm_002": (37.00, 127.93),   # 충북 충주
    "farm_003": (35.97, 126.71),   # 전북 군산
    "farm_004": (36.40, 128.16),   # 경북 상주
    "farm_005": (37.57, 126.98),   # 서울
}

def openmeteo_get_forecast(
    farm_id: str = "farm_001",
    days: int = 7,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Optional[dict]:
    """Open-Meteo 7일 기상 예보 (키 없이 무료 사용).

    https://open-meteo.com/en/docs
    반환 변수: 최고/최저/평균 기온, 일사량, 강수량, 풍속

    Returns:
        {
          "farm_id": str,
          "source": "open_meteo",
          "daily": {
            "time": [...],
            "temperature_2m_max": [...],
            "temperature_2m_min": [...],
            "precipitation_sum": [...],
            "shortwave_radiation_sum": [...],  # MJ/m²
            "wind_speed_10m_max": [...],
          },
          "et0_forecast": [...],  # Hargreaves ET₀ mm/day 계산값
        }
    """
    lat, lon = latitude, longitude
    if lat is None or lon is None:
        lat, lon = _FARM_COORDS.get(farm_id, (36.5, 127.5))

    def _fetch():
        params = urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join([
                "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
                "precipitation_sum", "shortwave_radiation_sum",
                "wind_speed_10m_max", "relative_humidity_2m_mean",
            ]),
            "timezone": "Asia/Seoul",
            "forecast_days": days,
        })
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        daily = raw.get("daily", {})
        # Hargreaves ET₀ 계산 (키가 없는 외부 서비스 활용)
        et0_list = []
        t_max_list = daily.get("temperature_2m_max", [])
        t_min_list = daily.get("temperature_2m_min", [])
        t_mean_list = daily.get("temperature_2m_mean", [])
        rad_list = daily.get("shortwave_radiation_sum", [])   # MJ/m²
        for i in range(len(t_max_list)):
            try:
                t_max = float(t_max_list[i])
                t_min = float(t_min_list[i])
                t_mean = float(t_mean_list[i])
                rad = float(rad_list[i])
                td = max(t_max - t_min, 0.0)
                Ra = max(rad / 0.75, 1.0)
                et0 = 0.0023 * (t_mean + 17.8) * (td ** 0.5) * Ra
                et0_list.append(round(max(et0, 0.0), 2))
            except Exception:
                et0_list.append(None)

        return {
            "farm_id": farm_id,
            "latitude": lat, "longitude": lon,
            "source": "open_meteo",
            "source_url": "https://open-meteo.com",
            "daily": daily,
            "et0_forecast_mm": et0_list,
            "retrieved_at": datetime.utcnow().isoformat() + "Z",
        }

    return _cached(f"openmeteo_{farm_id}_{days}", 3600, _fetch)


# ══════════════════════════════════════════════════════════════════════════════
# B2. EPPO Global Database — 병해충 위험 경보 (EU, 키 불필요)
# ══════════════════════════════════════════════════════════════════════════════

# 한국 스마트팜 주요 작목 EPPO 코드
_EPPO_CODES: dict[str, str] = {
    "딸기":     "FRAAN",    # Fragaria × ananassa
    "방울토마토": "LYPES",   # Lycopersicon esculentum
    "완숙토마토": "LYPES",
    "파프리카":  "CPSAN",   # Capsicum annuum
    "참외":     "CUCME",   # Cucumis melo
    "오이":     "CUMSA",   # Cucumis sativus
}

# EPPO 주요 병해충 코드
_EPPO_PESTS = {
    "잿빛곰팡이": "BOTRCI",    # Botrytis cinerea
    "흰가루병":   "SPHENE",    # Sphaerotheca (powdery mildew)
    "역병":      "PHYTIF",    # Phytophthora infestans
    "점박이응애": "TETRUR",    # Tetranychus urticae
    "온실가루이": "TRIAVA",    # Trialeurodes vaporariorum
}

def eppo_get_pest_alert(pest_eppo_code: str = "BOTRCI") -> Optional[dict]:
    """EPPO Global Database 병해충 알림 조회 (무료).

    https://gd.eppo.int/taxon/{code}/categorization
    병해충의 분류·위험도·방제 권고 정보를 반환한다.
    """
    def _fetch():
        url = f"https://gd.eppo.int/taxon/{pest_eppo_code}/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return {
            "pest_code": pest_eppo_code,
            "source": "eppo_gd",
            "source_url": f"https://gd.eppo.int/taxon/{pest_eppo_code}",
            "data": raw,
        }

    return _cached(f"eppo_{pest_eppo_code}", 86400 * 7, _fetch)


def eppo_get_crop_pests(crop_ko: str) -> Optional[dict]:
    """작목별 EPPO 병해충 목록 조회 (무료).

    Returns:
        {
          "crop_ko": str,
          "eppo_code": str,
          "pests": [{"name_ko": str, "eppo_code": str}, ...],
          "source": "eppo_gd",
        }
    """
    eppo_code = _EPPO_CODES.get(crop_ko)
    if not eppo_code:
        return None

    def _fetch():
        url = f"https://gd.eppo.int/taxon/{eppo_code}/pests/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        pests = []
        for item in raw if isinstance(raw, list) else []:
            pests.append({
                "eppo_code": item.get("eppocode", ""),
                "name_en": item.get("fullname", ""),
                "category": item.get("category", ""),
            })
        return {
            "crop_ko": crop_ko,
            "eppo_code": eppo_code,
            "pests": pests[:20],
            "source": "eppo_gd",
            "source_url": f"https://gd.eppo.int/taxon/{eppo_code}/pests",
        }

    return _cached(f"eppo_crop_{crop_ko}", 86400 * 7, _fetch)


# ══════════════════════════════════════════════════════════════════════════════
# B4. PlantNet — 식물/병해 식별 (1일 500회 무료, 키 선택)
# ══════════════════════════════════════════════════════════════════════════════

_PLANTNET_BASE = "https://my-api.plantnet.org/v2"

def plantnet_identify(
    image_url: str,
    organs: list[str] = None,
    api_key: str = "2b10lptbNoFAGqstlxkSQ2P",  # PlantNet 공개 테스트 키
) -> Optional[dict]:
    """PlantNet 식물 식별 API (무료 공개 키 포함).

    https://my-api.plantnet.org

    Args:
        image_url: 식물 이미지 URL
        organs:    ["leaf", "flower", "fruit", "bark"]
        api_key:   PlantNet API 키 (기본: 무료 공개 키)

    Returns:
        {
          "best_match": str,        # 식물명
          "score": float,           # 신뢰도 0~1
          "source": "plantnet",
          "suggestions": [...],     # 후보 목록
        }
    """
    if organs is None:
        organs = ["leaf"]

    env_key = os.environ.get("PLANTNET_API_KEY", api_key)

    def _fetch():
        params = urllib.parse.urlencode({
            "api-key": env_key,
            "lang": "ko",
        })
        url = f"{_PLANTNET_BASE}/identify/all?{params}"
        # POST with image URL
        body = urllib.parse.urlencode({
            "images": image_url,
            "organs": organs[0],
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        results = raw.get("results", [])
        best = results[0] if results else {}
        return {
            "best_match": best.get("species", {}).get("scientificName", ""),
            "score": best.get("score", 0.0),
            "source": "plantnet",
            "suggestions": [
                {
                    "name": r.get("species", {}).get("scientificName", ""),
                    "score": r.get("score", 0.0),
                }
                for r in results[:5]
            ],
        }

    return _cached(f"plantnet_{hash(image_url)}", 3600, _fetch)


# ══════════════════════════════════════════════════════════════════════════════
# 통합 환경-병해 위험 보강 (API 폴백 체인)
# ══════════════════════════════════════════════════════════════════════════════

def get_disease_risk_augmented(
    env: dict,
    crop_ko: str,
    include_eppo: bool = True,
) -> dict:
    """M5 병해 위험도 + EPPO API 보강 통합.

    M5 stub 모드일 때 EPPO + RDA 데이터로 규칙 기반 위험도를 반환한다.

    Args:
        env:          환경 dict {"temp_internal": float, "humidity_int": float, ...}
        crop_ko:      작목명
        include_eppo: EPPO 병해충 목록 포함 여부

    Returns:
        {
          "m5_result": EnvRiskResult dict,
          "eppo_pests": [...],
          "rda_pests":  [...],
          "api_sources": [...],
        }
    """
    result: dict = {"api_sources": []}

    # M5 내장 모델 (규칙 기반 v2)
    try:
        from models.m5_disease import env_risk_predict  # type: ignore
        m5 = env_risk_predict(env, crop_ko)
        result["m5_result"] = {
            "disease":    m5.disease,
            "risk_level": m5.risk_level,
            "score":      m5.score,
            "action_ko":  m5.action_ko,
            "reasons":    m5.reasons,
        }
        result["api_sources"].append("m5_rule_based_v2")
    except Exception as e:
        result["m5_result"] = {"error": str(e)}

    # EPPO 병해충 목록 (무료 API)
    if include_eppo:
        try:
            eppo = eppo_get_crop_pests(crop_ko)
            if eppo:
                result["eppo_pests"] = eppo["pests"]
                result["api_sources"].append("eppo_gd")
        except Exception:
            pass

    # RDA 병해충 정보 (키 있을 때)
    try:
        rda = rda_get_pest_info(crop_ko)
        if rda:
            result["rda_pests"] = rda["pests"][:10]
            result["api_sources"].append("rda_nongsaro")
    except Exception:
        pass

    return result


def get_weather_forecast_full(farm_id: str, days: int = 7) -> dict:
    """기상 예보 풀체인 (KMA + Open-Meteo 폴백).

    KMA → Open-Meteo 순서로 시도. ET₀ 예측값 포함.

    Returns:
        {
          "source": "kma_asos" | "open_meteo",
          "daily": [...],
          "et0_forecast_mm": [...],
          "summary_7d": {avg_et0, total_rain, avg_temp},
        }
    """
    # KMA 실황 (어제 데이터 기반)
    try:
        from api.services.kma_service import get_latest_weather, calc_et0_hargreaves  # type: ignore
        item = get_latest_weather(farm_id)
        if item:
            t_max  = float(item.get("maxTa", 25) or 25)
            t_min  = float(item.get("minTa", 15) or 15)
            t_mean = (t_max + t_min) / 2
            gsr    = float(item.get("sumGsr", 10) or 10)
            et0    = calc_et0_hargreaves(t_max, t_min, t_mean, gsr)
            return {
                "source": "kma_asos_yesterday",
                "farm_id": farm_id,
                "daily": [item],
                "et0_forecast_mm": [et0],
                "summary_7d": {"avg_et0": et0, "total_rain": 0.0, "avg_temp": t_mean},
            }
    except Exception:
        pass

    # Open-Meteo 폴백 (무료)
    om = openmeteo_get_forecast(farm_id, days=days)
    if om:
        et0_list = [v for v in (om.get("et0_forecast_mm") or []) if v is not None]
        temps = om.get("daily", {}).get("temperature_2m_mean", [])
        rains = om.get("daily", {}).get("precipitation_sum", [])
        avg_et0   = sum(et0_list) / len(et0_list) if et0_list else 3.0
        total_rain = sum(float(r or 0) for r in rains)
        avg_temp   = sum(float(t or 20) for t in temps) / max(len(temps), 1)
        om["summary_7d"] = {
            "avg_et0": round(avg_et0, 2),
            "total_rain_mm": round(total_rain, 1),
            "avg_temp_c": round(avg_temp, 1),
        }
        return om

    return {"source": "no_data", "farm_id": farm_id, "et0_forecast_mm": [3.0]}


# ══════════════════════════════════════════════════════════════════════════════
# C. 연결 방법 안내 (키 없는 서비스)
# ══════════════════════════════════════════════════════════════════════════════

MISSING_API_GUIDE: dict[str, dict] = {
    "ANTHROPIC_API_KEY": {
        "service": "Anthropic Claude API (AI 채팅)",
        "used_for": "농장 AI 어시스턴트 채팅 (/chat 엔드포인트)",
        "get_key_url": "https://console.anthropic.com/account/keys",
        "cost": "claude-3-haiku-20240307: $0.25/M tokens (월 $5~20 수준)",
        "env_var": "ANTHROPIC_API_KEY",
        "alternative": [
            "OpenAI gpt-4o-mini (OPENAI_API_KEY, openai.com)",
            "Ollama 로컬 LLM (무료, ollama.ai) — GPU 권장",
            "Google Gemini Flash (GOOGLE_API_KEY, aistudio.google.com)",
        ],
        "setup": (
            "1. https://console.anthropic.com 가입\n"
            "2. Settings → API Keys → Create Key\n"
            "3. .env 에 ANTHROPIC_API_KEY=sk-ant-... 추가\n"
            "4. docker compose restart api"
        ),
    },
    "OPENAI_API_KEY": {
        "service": "OpenAI API (AI 채팅 대체)",
        "used_for": "Anthropic 없을 때 ChatGPT API로 대체",
        "get_key_url": "https://platform.openai.com/api-keys",
        "cost": "gpt-4o-mini: $0.15/M tokens",
        "env_var": "OPENAI_API_KEY",
        "setup": (
            "1. https://platform.openai.com 가입 + 결제 등록\n"
            "2. API Keys → Create new secret key\n"
            "3. .env 에 OPENAI_API_KEY=sk-... 추가"
        ),
    },
    "SLACK_WEBHOOK_URL": {
        "service": "Slack 웹훅 알림",
        "used_for": "이상 감지·병해 경보·수확량 알림 채널",
        "get_key_url": "https://api.slack.com/messaging/webhooks",
        "cost": "무료 (Slack 워크스페이스 필요)",
        "env_var": "SLACK_WEBHOOK_URL",
        "setup": (
            "1. Slack 워크스페이스 → Apps → Incoming Webhooks 추가\n"
            "2. 채널 선택 → Webhook URL 복사\n"
            "3. .env 에 SLACK_WEBHOOK_URL=https://hooks.slack.com/... 추가"
        ),
    },
    "PLANTNET_API_KEY": {
        "service": "PlantNet 식물/병해 식별",
        "used_for": "M5 병해 이미지 진단 보강",
        "get_key_url": "https://my.plantnet.org/account/api",
        "cost": "무료 플랜: 500회/일, 유료: 무제한",
        "env_var": "PLANTNET_API_KEY",
        "note": "기본 공개 키(테스트용)로도 동작함",
    },
    "NAAS_API_KEY": {
        "service": "농협 유통정보 API (산지·도매 가격)",
        "used_for": "KAMIS 보완 — 경매 낙찰가 실시간 조회",
        "get_key_url": "https://data.nonghyup.com",
        "cost": "무료 (승인 후 사용)",
        "env_var": "NAAS_API_KEY",
        "setup": (
            "1. https://data.nonghyup.com 회원가입\n"
            "2. API 신청 → 심사 승인 (2~5 영업일)\n"
            "3. .env 에 NAAS_API_KEY=... 추가"
        ),
    },
    "PLANT_ID_API_KEY": {
        "service": "Plant.id Plant Health Assessment API",
        "used_for": "M5 이미지 기반 병해 탐지 (EfficientNet 대체)",
        "get_key_url": "https://admin.kindwise.com",
        "cost": "무료: 100건/월  |  유료: $9/월(500건), $29/월(무제한)",
        "env_var": "PLANT_ID_API_KEY",
        "setup": (
            "1. https://admin.kindwise.com → 가입 (Plant.id API는 Kindwise 운영)\n"
            "2. Dashboard → API Keys → Create new key\n"
            "3. .env 에 PLANT_ID_API_KEY=your_key 추가\n"
            "4. POST /api/farms/{farm_id}/disease/detect 로 이미지 전송"
        ),
        "alternative": "PlantNet API (무료 500건/일) — PLANTNET_API_KEY",
    },
    "USDA_NASS_API_KEY": {
        "service": "USDA NASS Quick Stats API",
        "used_for": "M2 수확량 예측 이상값 클리핑 기준 (과적합 보정)",
        "get_key_url": "https://quickstats.nass.usda.gov/api",
        "cost": "완전 무료",
        "env_var": "USDA_NASS_API_KEY",
        "setup": (
            "1. https://quickstats.nass.usda.gov/api 접속\n"
            "2. 'Request API Key' 클릭 → 이메일 입력 → 즉시 발급\n"
            "3. .env 에 USDA_NASS_API_KEY=your_key 추가\n"
            "4. 참고: 한국 RDA 기준값이 내장돼 있어 키 없이도 동작"
        ),
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# D. MCP 서버 연결 방법 안내
# ══════════════════════════════════════════════════════════════════════════════

MCP_CONNECTION_GUIDE: dict[str, dict] = {
    "anthropic_mcp": {
        "name": "Anthropic Claude MCP",
        "description": "Claude Code에 농장 컨텍스트 자동 주입",
        "setup": (
            "# claude_desktop_config.json 또는 .claude/settings.json\n"
            '{\n  "mcpServers": {\n'
            '    "smartfarm": {\n'
            '      "command": "python",\n'
            '      "args": ["-m", "api.mcp.smartfarm_server"],\n'
            '      "cwd": "C:/smart_farm"\n'
            "    }\n  }\n}"
        ),
        "requires": "ANTHROPIC_API_KEY",
    },
    "fao_aquastat_mcp": {
        "name": "FAO AQUASTAT Water Data MCP",
        "description": "FAO 물/관개 통계 데이터 접근",
        "endpoint": "https://www.fao.org/aquastat/en/api",
        "key_required": False,
        "setup": "키 없이 REST API 직접 호출 가능",
    },
    "open_meteo_mcp": {
        "name": "Open-Meteo MCP",
        "description": "글로벌 기상 예보 MCP 서버",
        "npm_package": "@open-meteo/sdk",
        "key_required": False,
        "setup": (
            "# npx로 MCP 서버 실행\n"
            "npx -y @modelcontextprotocol/server-open-meteo\n"
            "# 또는 claude_desktop_config.json에 추가"
        ),
    },
    "postgres_mcp": {
        "name": "PostgreSQL MCP (이미 연결됨)",
        "description": "스마트팜 PostgreSQL DB 직접 쿼리",
        "status": "ACTIVE",
        "note": "DATABASE_URL 환경변수로 이미 연결됨",
    },
}


def get_api_status_report() -> dict:
    """현재 연결된/미연결 API 전체 현황 반환."""
    import os
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()

    def _has(var: str) -> bool:
        v = os.environ.get(var, "")
        return bool(v) and v not in ("none", "None", "", "your_key_here")

    connected = {
        # ── 키 보유 — 즉시 사용 가능 ────────────────────────────────────────
        "KMA 기상청 ASOS":          {"key_var": "KMA_SERVICE_KEY",
                                     "status": "connected" if _has("KMA_SERVICE_KEY") else "MISSING",
                                     "used_for": "ET₀ 계산·기상 예보",
                                     "get_key_url": "https://data.go.kr"},
        "KAMIS 농산물가격":          {"key_var": "KAMIS_API_KEY",
                                     "status": "connected" if _has("KAMIS_API_KEY") else "MISSING",
                                     "used_for": "M3 매출 예측 가격 소스",
                                     "get_key_url": "https://www.kamis.or.kr"},
        "RDA 농촌진흥청":            {"key_var": "RDA_API_KEY",
                                     "status": "connected" if _has("RDA_API_KEY") else "MISSING",
                                     "used_for": "작물 생육기준·병해충 정보",
                                     "get_key_url": "https://api.nongsaro.go.kr"},
        "AIHub 인공지능허브":         {"key_var": "AIHUB_API_KEY",
                                     "status": "connected" if _has("AIHUB_API_KEY") else "MISSING",
                                     "used_for": "M5 병해 이미지 데이터셋",
                                     "get_key_url": "https://aihub.or.kr"},
        "공공데이터포털":             {"key_var": "DATA_GO_KR_SERVICE_KEY",
                                     "status": "connected" if _has("DATA_GO_KR_SERVICE_KEY") else "MISSING",
                                     "used_for": "NCPMS 병해충예보 + aT 도매가격",
                                     "get_key_url": "https://data.go.kr"},
        # ── AI / 알림 ────────────────────────────────────────────────────────
        # Anthropic: 키 없으면 AI 채팅 기능 실제 제한 → MISSING 유지
        "Anthropic Claude":           {"key_var": "ANTHROPIC_API_KEY",
                                     "status": "connected" if _has("ANTHROPIC_API_KEY") else "MISSING",
                                     "note": "" if _has("ANTHROPIC_API_KEY") else "AI채팅 규칙기반 폴백 중 — console.anthropic.com 에서 발급",
                                     "used_for": "AI 채팅 1순위 (미설정 시 규칙기반 응답)",
                                     "get_key_url": "https://console.anthropic.com"},
        # OpenAI: Anthropic 폴백으로 실제 동작은 가능 → fallback_active
        "OpenAI GPT":                 {"key_var": "OPENAI_API_KEY",
                                     "status": "connected" if _has("OPENAI_API_KEY") else "fallback_active",
                                     "note": "" if _has("OPENAI_API_KEY") else "Anthropic→Ollama→규칙기반 자동 폴백 중",
                                     "used_for": "AI 채팅 2순위 폴백"},
        # Slack: 키 없으면 알림 완전 비활성 → MISSING 유지
        "Slack 알림":                 {"key_var": "SLACK_WEBHOOK_URL",
                                     "status": "connected" if _has("SLACK_WEBHOOK_URL") else "MISSING",
                                     "note": "" if _has("SLACK_WEBHOOK_URL") else "알림 비활성 — api.slack.com → Incoming Webhooks 에서 발급",
                                     "used_for": "이상감지·병해 경보 알림 채널",
                                     "get_key_url": "https://api.slack.com/messaging/webhooks"},
        # ── 이미지 병해 탐지 ─────────────────────────────────────────────────
        # Plant.id: 미설정 시 NCPMS→M5규칙→EPPO 폴백 체인 동작 → fallback_active
        "Plant.id 병해 탐지":         {"key_var": "PLANT_ID_API_KEY",
                                     "status": "connected" if _has("PLANT_ID_API_KEY") else "fallback_active",
                                     "note": "" if _has("PLANT_ID_API_KEY") else "NCPMS→M5규칙기반→EPPO 폴백 체인 동작 중 (admin.kindwise.com 에서 무료 100건/월 발급 가능)",
                                     "used_for": "M5 이미지 병해 탐지 (미설정 시 환경센서 기반 규칙)",
                                     "get_key_url": "https://admin.kindwise.com"},
        # ── 수확량 기준 ──────────────────────────────────────────────────────
        # USDA NASS: RDA 내장 기준값이 한국 스마트팜에 더 적합 → available
        "USDA NASS 수확량기준":        {"key_var": "USDA_NASS_API_KEY",
                                     "status": "connected" if _has("USDA_NASS_API_KEY") else "available",
                                     "note": "" if _has("USDA_NASS_API_KEY") else "RDA 한국 스마트팜 내장 기준값 사용 중 (quickstats.nass.usda.gov 에서 무료 발급)",
                                     "used_for": "M2 과적합 예측값 클리핑 (RDA 내장 기준값으로 동작)",
                                     "get_key_url": "https://quickstats.nass.usda.gov/api"},
        # ── 농협 유통정보 ────────────────────────────────────────────────────
        # NAAS: DATA_GO_KR + KAMIS로 이미 완전 폴백 → available
        "농협 유통정보 API":           {"key_var": "NAAS_API_KEY",
                                     "status": "connected" if _has("NAAS_API_KEY") else "available",
                                     "note": "" if _has("NAAS_API_KEY") else "DATA_GO_KR + KAMIS 자동 폴백 사용 중 (data.nonghyup.com 에서 신청, 2~5일 심사)",
                                     "used_for": "산지·도매 경락가격 (미설정 시 KAMIS 자동 사용)",
                                     "get_key_url": "https://data.nonghyup.com"},
        # ── 무료 API (키 불필요) ─────────────────────────────────────────────
        "Open-Meteo 기상예보 (무료)":  {"key_var": "없음 (키 불필요)",
                                     "status": "available",
                                     "used_for": "KMA 폴백 기상예보 + ET₀"},
        "EPPO 병해충 DB (무료)":       {"key_var": "없음 (키 불필요)",
                                     "status": "available",
                                     "used_for": "M5 작물별 병해충 목록"},
        "FAO FAOSTAT (무료)":         {"key_var": "없음 (키 불필요)",
                                     "status": "available",
                                     "used_for": "M3 국제 가격 기준 보정"},
        "PlantNet 식물진단 (무료)":    {"key_var": "PLANTNET_API_KEY (선택)",
                                     "status": "available",
                                     "used_for": "식물 식별 (병해 탐지 보조)"},
        # ── 글로벌 기상·가격 데이터 (신규, 키 불필요) ──────────────────────
        "NASA POWER 기상이력 (무료)":  {"key_var": "없음 (키 불필요)",
                                     "status": "available",
                                     "used_for": "M1 ET₀ 보강·태양복사 이력 (1984~현재)",
                                     "adapter":  "adapters/nasa_power_adapter.py"},
        "World Bank 가격지수 (무료)":  {"key_var": "없음 (키 불필요)",
                                     "status": "available",
                                     "used_for": "M3 국제 농산물 가격 보정계수",
                                     "adapter":  "adapters/worldbank_price_adapter.py"},
    }
    return {
        "report_time": datetime.utcnow().isoformat() + "Z",
        "apis": connected,
        "missing_guide": MISSING_API_GUIDE,
        "mcp_guide": MCP_CONNECTION_GUIDE,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 노지 공공데이터 어댑터 (흙토람 토양 · 팜맵 필지)
#   - 정확한 엔드포인트/키는 .env 로 주입 (서비스별 IP 등록·키 승인 필요)
#   - 미설정/실패 시 None 반환 → 호출부에서 Mock 폴백
#   환경변수:
#     NAAS_SOIL_API_URL   : 흙토람 토양검정 OpenAPI base URL
#     FARMMAP_API_URL     : 팜맵 농경지전자지도 OpenAPI base URL
#     (키는 기존 DATA_GO_KR_SERVICE_KEY_DECODED / RDA_API_KEY 재사용)
# ══════════════════════════════════════════════════════════════════════════════

def _datago_key() -> str:
    return (os.environ.get("DATA_GO_KR_SERVICE_KEY_DECODED")
            or os.environ.get("DATA_GO_KR_SERVICE_KEY", ""))


def naas_soil_by_pnu(pnu: str) -> Optional[dict]:
    """흙토람 토양검정/토양특성 조회 (PNU 지번코드 기준).

    Returns:
        {"pnu": str, "soil": {...}, "source": "naas_soil"} | None
    """
    base = os.environ.get("NAAS_SOIL_API_URL", "").strip()
    key  = os.environ.get("RDA_API_KEY") or _datago_key()
    if not base or not key or not pnu:
        return None

    def _fetch():
        params = urllib.parse.urlencode({
            "serviceKey": key, "PNU_Code": pnu, "numOfRows": 1, "type": "json",
        })
        ctx = _insecure_ctx()
        with urllib.request.urlopen(f"{base}?{params}", timeout=8, context=ctx) as r:
            raw = json.loads(r.read().decode("utf-8", "replace"))
        return {"pnu": pnu, "soil": raw, "source": "naas_soil"}

    try:
        return _cached(f"naas_soil_{pnu}", 86400, _fetch)
    except Exception as e:
        logger.warning("[naas_soil] 조회 실패 pnu=%s: %s", pnu, e)
        return None


def _parse_farmmap(raw: Any) -> list:
    """팜맵 응답(raw)을 필지 리스트로 정규화하는 방어적 파서(스캐폴드).

    ★ 정직화: data.go.kr 팜맵 실 응답 스펙을 아직 검증하지 못했다(키 미승인).
      아래는 공공데이터포털의 통상 구조(response.body.items.item[])와 필드
      별칭을 방어적으로 훑는 준비용 매퍼다. 실 응답 샘플을 확보하면 이 함수의
      키 매핑을 확정한다. 알 수 없는 형태면 [] 를 반환(호출부는 raw 를 보존).
    """
    # 1) items 리스트 위치 탐색 — 공공데이터포털 표준 경로 + 흔한 변형
    items = None
    node = raw
    if isinstance(node, dict):
        for path in (("response", "body", "items", "item"),
                     ("response", "body", "items"),
                     ("items", "item"), ("items",), ("data",), ("features",)):
            cur = node
            ok = True
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False; break
            if ok and cur is not None:
                items = cur; break
    if isinstance(items, dict):        # 단건이면 리스트로 승격
        items = [items]
    if not isinstance(items, list):
        return []

    # 2) 필드 별칭 매핑 — 확정 전까지 다수 후보 허용
    def _pick(d: dict, *names):
        for n in names:
            if isinstance(d, dict) and d.get(n) not in (None, ""):
                return d[n]
        return None

    parcels = []
    for it in items:
        # GeoJSON 형태면 properties 안에 속성이 들어있다
        props = it.get("properties") if isinstance(it, dict) and isinstance(it.get("properties"), dict) else it
        if not isinstance(props, dict):
            continue
        pnu  = _pick(props, "pnu", "PNU", "pnuCode", "PNU_CODE", "ld_cpsg_code")
        area = _pick(props, "area_m2", "area", "AREA", "parea", "flr_area", "lndpcl_ar")
        jimok = _pick(props, "jimok", "JIMOK", "lndcgr_code_nm", "lndcgrCodeNm")
        name = _pick(props, "name", "NAME", "addr", "ADDR", "lnm", "jibun")
        try:
            area = float(area) if area is not None else None
        except (TypeError, ValueError):
            area = None
        parcels.append({"pnu": pnu, "area_m2": area, "jimok": jimok, "name": name})
    return parcels


def farmmap_parcels(pnu_prefix: str) -> Optional[dict]:
    """팜맵 농경지전자지도 필지 조회 (행정구역 admCode 접두 기준).

    Returns:
        {"adm","parcels":[{"pnu","area_m2","jimok","name"}...],"raw","parsed",
         "source":"farmmap"} | None

    ★ 정직화: 파싱 스펙 미검증. parsed=False 면 실 응답 형태를 인식 못한 것이며
      raw 를 그대로 보존한다(호출부가 raw 폴백 표기). 실 응답 샘플 확보 후
      _parse_farmmap 키 매핑을 확정하면 parsed=True 로 승격된다.
    """
    base = os.environ.get("FARMMAP_API_URL", "").strip()
    key  = _datago_key()
    if not base or not key or not pnu_prefix:
        return None

    def _fetch():
        params = urllib.parse.urlencode({
            "serviceKey": key, "admCode": pnu_prefix, "numOfRows": 50, "type": "json",
        })
        ctx = _insecure_ctx()
        with urllib.request.urlopen(f"{base}?{params}", timeout=8, context=ctx) as r:
            raw = json.loads(r.read().decode("utf-8", "replace"))
        parcels = _parse_farmmap(raw)
        if not parcels:
            logger.warning("[farmmap] 응답 파싱 실패(미검증 스펙) — raw 보존 adm=%s", pnu_prefix)
        return {"adm": pnu_prefix, "parcels": parcels, "parsed": bool(parcels),
                "raw": raw, "source": "farmmap"}

    try:
        return _cached(f"farmmap_{pnu_prefix}", 86400, _fetch)
    except Exception as e:
        logger.warning("[farmmap] 조회 실패 adm=%s: %s", pnu_prefix, e)
        return None


def satellite_ndvi(adm: str = "", parcel_names: Optional[list] = None) -> Optional[dict]:
    """위성 식생지수(NDVI) 필지별 조회 — 키/엔드포인트 주입 시 자동 활성.

    환경변수(둘 중 하나로 주입):
      · SATELLITE_NDVI_URL  : 필지 NDVI를 반환하는 JSON 엔드포인트
                              (GET {URL}?adm={adm} → 응답 정규화 지원)
      · SATELLITE_NDVI_KEY  : (선택) Authorization Bearer 헤더로 전달
    지원 응답 형태(자동 정규화):
      1) {"parcels":[{"name":"1번 필지","ndvi":0.78}, ...]}
      2) {"1번 필지":0.78, "2번 필지":0.55}
      3) [{"name":..,"ndvi":..}, ...]
    Sentinel Hub Statistical API 등 OAuth형은 게이트웨이(프록시 URL)를 SATELLITE_NDVI_URL로 지정.

    Returns: {name: ndvi(float)} 또는 None(미연동/실패 → 상위에서 프록시 폴백)
    """
    url = os.environ.get("SATELLITE_NDVI_URL", "").strip()
    if not url:
        return None
    key = os.environ.get("SATELLITE_NDVI_KEY", "").strip()

    def _fetch():
        sep = "&" if "?" in url else "?"
        full = f"{url}{sep}{urllib.parse.urlencode({'adm': adm})}" if adm else url
        req = urllib.request.Request(full)
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        ctx = _insecure_ctx()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            raw = json.loads(r.read().decode("utf-8", "replace"))
        # 정규화
        out = {}
        rows = raw.get("parcels") if isinstance(raw, dict) else raw
        if isinstance(raw, dict) and rows is None:
            for k, v in raw.items():
                try: out[str(k)] = float(v)
                except (TypeError, ValueError): pass
        elif isinstance(rows, list):
            for it in rows:
                if isinstance(it, dict) and it.get("name") is not None and it.get("ndvi") is not None:
                    try: out[str(it["name"])] = float(it["ndvi"])
                    except (TypeError, ValueError): pass
        return out or None

    try:
        return _cached(f"sat_ndvi_{adm}", 6 * 3600, _fetch)
    except Exception as e:
        logger.warning("[satellite_ndvi] 조회 실패 adm=%s: %s", adm, e)
        return None


def _insecure_ctx():
    import ssl
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c
