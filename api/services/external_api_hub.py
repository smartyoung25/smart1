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
        "get_key_url": "https://web.plant.id/",
        "cost": "무료: 100건/월  |  유료: $9/월(500건), $29/월(무제한)",
        "env_var": "PLANT_ID_API_KEY",
        "setup": (
            "1. https://web.plant.id/ → 가입 (GitHub/Google OK)\n"
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
        "Anthropic Claude":           {"key_var": "ANTHROPIC_API_KEY",
                                     "status": "connected" if _has("ANTHROPIC_API_KEY") else "MISSING — AI채팅 규칙기반 폴백 중",
                                     "used_for": "AI 채팅 1순위",
                                     "get_key_url": "https://console.anthropic.com"},
        "OpenAI GPT":                 {"key_var": "OPENAI_API_KEY",
                                     "status": "connected" if _has("OPENAI_API_KEY") else "미설정 (Anthropic→Ollama→규칙기반 폴백)",
                                     "used_for": "AI 채팅 2순위 폴백"},
        "Slack 알림":                 {"key_var": "SLACK_WEBHOOK_URL",
                                     "status": "connected" if _has("SLACK_WEBHOOK_URL") else "MISSING — 알림 비활성",
                                     "used_for": "이상감지·병해 경보 알림",
                                     "get_key_url": "https://api.slack.com/messaging/webhooks"},
        # ── 이미지 병해 탐지 ─────────────────────────────────────────────────
        "Plant.id 병해 탐지":         {"key_var": "PLANT_ID_API_KEY",
                                     "status": "connected" if _has("PLANT_ID_API_KEY") else "MISSING — 환경기반 폴백 중 (무료 100건/월)",
                                     "used_for": "M5 이미지 병해 탐지 (EfficientNet 대체)",
                                     "get_key_url": "https://web.plant.id/"},
        # ── 수확량 기준 ──────────────────────────────────────────────────────
        "USDA NASS 수확량기준":        {"key_var": "USDA_NASS_API_KEY",
                                     "status": "connected" if _has("USDA_NASS_API_KEY") else "미설정 (RDA 내장 기준값 사용 중)",
                                     "used_for": "M2 과적합 예측값 클리핑",
                                     "get_key_url": "https://quickstats.nass.usda.gov/api"},
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
    }
    return {
        "report_time": datetime.utcnow().isoformat() + "Z",
        "apis": connected,
        "missing_guide": MISSING_API_GUIDE,
        "mcp_guide": MCP_CONNECTION_GUIDE,
    }
