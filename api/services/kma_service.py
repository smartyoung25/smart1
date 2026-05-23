"""기상청 기상 데이터 서비스 (ASOS 실황 + 단기예보).

APIs:
  ASOS 일별 실황 : https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList
  단기예보       : https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst
인증: 공공데이터포털 서비스키 (serviceKey, 환경변수 KMA_SERVICE_KEY)

농가별 최인접 ASOS 관측소 + 격자(nx,ny) 매핑
  → 실황: 최근 1일 데이터 조회 → 1시간 캐시
  → 단기예보: 향후 3일 일별 요약 → 3시간 캐시
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

# ── 공공데이터포털 서비스키 (환경변수 KMA_SERVICE_KEY 에서 동적 로드) ──────────────
def _get_service_key() -> str:
    """호출 시점마다 os.environ을 재조회 — load_dotenv() 타이밍 문제 회피."""
    return os.environ.get("KMA_SERVICE_KEY", "")

_BASE_URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"

# ── 농가 → ASOS 관측소 ID 매핑 ───────────────────────────────────────────────
# 관측소 번호: https://www.kma.go.kr/ASOS (종관기상관측)
FARM_STATION: dict[str, int] = {
    "farm_001": 189,   # 동서 오이 농장 (경남 창녕군) → 합천 189
    "farm_002": 127,   # 청풍 토마토 (충북 청풍) → 충주 127
    "farm_003": 140,   # 한솔 딸기 (전북 군산) → 군산 140
    "farm_004": 136,   # 대원 토마토 (경북 상주) → 상주 136
    "farm_005": 108,   # 농가 E → 서울 108 (기본)
}

# ── 농가 → 단기예보 격자 좌표 (nx, ny) 매핑 ──────────────────────────────────
# KMA 동네예보 격자 변환표 기반 (https://www.kma.go.kr/biz/forecast/service/grid.jsp)
FARM_GRID: dict[str, tuple[int, int]] = {
    "farm_001": (90, 77),    # 경남 창녕 → nx=90, ny=77
    "farm_002": (69, 107),   # 충북 충주 → nx=69, ny=107
    "farm_003": (54, 91),    # 전북 군산 → nx=54, ny=91
    "farm_004": (89, 97),    # 경북 상주 → nx=89, ny=97
    "farm_005": (60, 127),   # 서울      → nx=60, ny=127
}

# 단기예보 API URL
_FCST_BASE_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
_FCST_CACHE_TTL = 10800   # 3시간 (예보 갱신 주기)

# ── 인메모리 캐시 ─────────────────────────────────────────────────────────────
_cache: dict[str, dict] = {}            # ASOS 실황 캐시
_fcst_cache: dict[str, dict] = {}      # 단기예보 캐시
_cache_lock = Lock()
_CACHE_TTL_SECONDS = 3600   # 1시간 (ASOS)


def _is_fresh(farm_id: str) -> bool:
    entry = _cache.get(farm_id)
    if not entry:
        return False
    age = (datetime.now(tz=timezone.utc) - entry["fetched_at"]).total_seconds()
    return age < _CACHE_TTL_SECONDS


def _fetch_asos(station_id: int, obs_date: date) -> Optional[dict]:
    """ASOS API 호출 → item dict 1건 반환 (최신 1일)."""
    svc_key = _get_service_key()
    if not svc_key:
        logger.warning("[kma_service] KMA_SERVICE_KEY 미설정 — ASOS 조회 비활성화")
        return None
    date_str = obs_date.strftime("%Y%m%d")
    params = urllib.parse.urlencode({
        "serviceKey": svc_key,
        "pageNo": 1,
        "numOfRows": 1,
        "dataType": "JSON",
        "dataCd": "ASOS",
        "dateCd": "DAY",
        "startDt": date_str,
        "endDt": date_str,
        "stnIds": station_id,
    })
    url = f"{_BASE_URL}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        result_code = body["response"]["header"]["resultCode"]
        if result_code != "00":
            logger.warning("[kma_service] ASOS resultCode=%s station=%s", result_code, station_id)
            return None
        items = body["response"]["body"]["items"]["item"]
        return items[0] if items else None
    except Exception as exc:
        logger.error("[kma_service] ASOS fetch error station=%s: %s", station_id, exc)
        return None


def get_latest_weather(farm_id: str) -> Optional[dict]:
    """농가 ID → 최근 ASOS 기상 데이터 dict (캐시 우선).

    Returns:
        ASOS item dict or None (API 오류 or 관측소 미등록)
    """
    with _cache_lock:
        if _is_fresh(farm_id):
            logger.debug("[kma_service] cache hit farm=%s", farm_id)
            return _cache[farm_id]["data"]

    station_id = FARM_STATION.get(farm_id)
    if station_id is None:
        logger.warning("[kma_service] no station mapping for farm=%s", farm_id)
        return None

    # 어제 날짜 (오늘 데이터는 당일 오후 이전에는 미확정)
    yesterday = date.today() - timedelta(days=1)
    item = _fetch_asos(station_id, yesterday)

    # 어제 데이터 없으면 이틀 전 시도
    if item is None:
        two_days_ago = date.today() - timedelta(days=2)
        logger.info("[kma_service] retry with %s station=%s", two_days_ago, station_id)
        item = _fetch_asos(station_id, two_days_ago)

    with _cache_lock:
        _cache[farm_id] = {
            "data": item,
            "fetched_at": datetime.now(tz=timezone.utc),
        }

    if item:
        logger.info(
            "[kma_service] fetched ASOS farm=%s station=%s date=%s avgTa=%s",
            farm_id, station_id, item.get("tm"), item.get("avgTa"),
        )
    return item


# ═══════════════════════════════════════════════════════════════════════════════
# ET₀ 계산 (Hargreaves-Samani 간이식) + ETc 기반 관수 최적화
# ═══════════════════════════════════════════════════════════════════════════════

def calc_et0_hargreaves(
    temp_max: float,
    temp_min: float,
    temp_mean: float,
    solar_mj_m2: float,
    latitude_rad: float = 0.6370,   # 한국 평균 위도 36.5°N (radians)
) -> float:
    """Hargreaves-Samani (1985) 간이식으로 기준 증발산량(ET₀) 계산.

    ET₀ = 0.0023 × (T_mean + 17.8) × (T_max − T_min)^0.5 × Ra  [mm/day]

    Ra (외기 일사량, MJ/m²/day)는 입력 solar_mj_m2가 실측 일사량(Rg)일 때
    Ra ≈ Rg / 0.75 로 환산한다 (맑은 날 투과율 약 75%).
    실측 데이터 없을 때는 계절 평균 fallback을 사용한다.

    References:
        Hargreaves & Samani (1985), ApplEngAgric 1(2):96-99
        Allen et al. (1998), FAO-56, Chapter 3

    Args:
        temp_max:    일 최고기온 (°C)
        temp_min:    일 최저기온 (°C)
        temp_mean:   일 평균기온 (°C)
        solar_mj_m2: 실측 일사량 (MJ/m²/day)
        latitude_rad: 위도 (radians, 기본 36.5°N)

    Returns:
        ET₀ (mm/day), ≥ 0
    """
    import math as _m
    # Ra 추정: 맑은날 비율(0.75) 가정으로 실측 일사량 역산
    Ra = max(solar_mj_m2 / 0.75, 1.0)
    td = max(temp_max - temp_min, 0.0)
    et0 = 0.0023 * (temp_mean + 17.8) * (td ** 0.5) * Ra
    return round(max(et0, 0.0), 2)


def calc_etc(
    et0: float,
    crop_ko: str,
    growth_stage: str = "mid",
) -> float:
    """작물 증발산량 ETc = ET₀ × Kc 계산.

    Args:
        et0:          기준 증발산량 ET₀ (mm/day)
        crop_ko:      작목 한국어명 (CROP_CONFIGS 키)
        growth_stage: "initial" | "dev" | "mid" | "late"

    Returns:
        ETc (mm/day)
    """
    try:
        from models.crop_config import CROP_CONFIGS
        cfg = CROP_CONFIGS.get(crop_ko)
        if cfg is None:
            kc = 1.0
        else:
            kc = cfg.kc_stages.get(growth_stage, cfg.kc_stages.get("mid", 1.0))
    except Exception:
        kc = 1.0
    return round(et0 * kc, 2)


def get_etc_irrigation(
    farm_id: str,
    crop_ko: str = "딸기",
    growth_stage: str = "mid",
    slab_volume_l: float = 7.5,     # 표준 암면 슬라브 용량 (L)
    supply_ml_per_trigger: float = 250.0,
) -> dict:
    """ETc 기반 스마트팜 관수 권고 계산.

    알고리즘:
      1. ASOS 실측값에서 T_max, T_min, T_mean, 일사량 파싱
      2. Hargreaves ET₀ 계산
      3. ETc = ET₀ × Kc (작목·생육단계)
      4. 일 관수량(mm) = ETc × 1.15 (증산 보정 + 여유율 15%)
      5. 배액 목표율(drain_target_pct) 감안 → 총 공급량
      6. Priva 방식으로 1회 공급량(supply_ml)로 나누어 관수 횟수 산출

    Returns:
        dict with keys:
          et0_mm_day         - 기준 증발산량 (mm/day)
          etc_mm_day         - 작물 증발산량 (mm/day)
          kc                 - 사용된 Kc 값
          growth_stage       - 입력 생육단계
          irrigation_mm_day  - 권고 관수량 (mm/day)
          n_irrigations      - 권고 관수 횟수
          total_supply_ml    - 권고 총 공급량 (ml/slab)
          supply_per_shot_ml - 1회 공급량 (ml)
          drain_target_pct   - 목표 배액률 (%)
          daily_gsr_mj_m2    - 일사량 (MJ/m²/day)
          temp_max           - 최고기온 (°C)
          temp_min           - 최저기온 (°C)
          temp_mean          - 평균기온 (°C)
          obs_date           - 기상 관측 날짜
          source             - 데이터 출처
          method             - 계산 방법 ("hargreaves_etc")
          note               - 메모
    """
    import math as _m

    item = get_latest_weather(farm_id)
    today_month = date.today().month

    # ── 기상 파싱 ─────────────────────────────────────────────────────────────
    _MONTHLY_TMAX = {1:5.5,2:7.8,3:13.0,4:19.5,5:24.8,6:28.5,
                     7:31.2,8:31.8,9:26.5,10:20.5,11:12.5,12:6.8}
    _MONTHLY_TMIN = {1:-4.5,2:-2.8,3:2.2,4:8.5,5:13.8,6:19.2,
                     7:23.5,8:23.8,9:17.5,10:10.8,11:3.5,12:-2.2}
    _MONTHLY_GSR  = {1:7.5,2:9.8,3:12.5,4:15.0,5:16.5,6:15.8,
                     7:13.2,8:14.0,9:13.0,10:11.5,11:8.5,12:7.0}

    def _fv(key: str) -> Optional[float]:
        if item is None:
            return None
        try:
            v = float(item.get(key) or 0)
            return v if v != 0.0 else None
        except (TypeError, ValueError):
            return None

    t_max  = _fv("maxTa")  or _MONTHLY_TMAX.get(today_month, 20.0)
    t_min  = _fv("minTa")  or _MONTHLY_TMIN.get(today_month, 10.0)
    t_mean = _fv("avgTa")  or (t_max + t_min) / 2.0
    gsr    = _fv("sumGsr") or _MONTHLY_GSR.get(today_month, 12.0)

    source = "kma_asos" if (item and _fv("avgTa")) else "seasonal_fallback"
    obs_date = item.get("tm") if item else None

    # ── ET₀ / ETc 계산 ────────────────────────────────────────────────────────
    et0 = calc_et0_hargreaves(t_max, t_min, t_mean, gsr)
    etc = calc_etc(et0, crop_ko, growth_stage)

    # 작목별 drain 목표 로드
    drain_pct = 20.0
    try:
        from models.crop_config import CROP_CONFIGS
        _cfg = CROP_CONFIGS.get(crop_ko)
        if _cfg:
            drain_pct = _cfg.drain_target_pct
    except Exception:
        pass

    # ── 관수량 계산 ───────────────────────────────────────────────────────────
    # 스마트팜 슬라브 재배: 공급량 = ETc / (1 - drain_pct/100)  (배액 손실 보정)
    # 단위 환산: mm/day × slab_area(m²) → L/day → mL/day
    # 암면 슬라브 표준: 0.15m × 1.0m = 0.15m² 면적으로 환산 (100mm = 1.5L/slab)
    _drain_factor = max(1.0, 1.0 / (1.0 - drain_pct / 100.0))
    irr_mm_day   = round(etc * 1.10 * _drain_factor, 2)  # 10% 안전율 포함

    # mL/slab/day: 1mm/m² = 1L/m² = 0.15L/slab → 150ml/slab
    _slab_area_m2 = 0.15
    total_ml_day  = round(irr_mm_day * _slab_area_m2 * 1000.0, 0)

    # 관수 횟수: 총 공급량 / 1회 공급량
    n_irr_raw = total_ml_day / max(supply_ml_per_trigger, 50.0)
    n_irr = max(2, min(16, round(n_irr_raw)))

    # Kc 역조회
    kc_used = etc / et0 if et0 > 0 else 1.0

    note = (
        f"ET₀={et0}mm (Hargreaves), Kc={kc_used:.2f}({growth_stage}), "
        f"ETc={etc}mm → 관수량={irr_mm_day}mm ({n_irr}회×{supply_ml_per_trigger}ml)"
    )

    return {
        "et0_mm_day":         et0,
        "etc_mm_day":         etc,
        "kc":                 round(kc_used, 2),
        "growth_stage":       growth_stage,
        "irrigation_mm_day":  irr_mm_day,
        "n_irrigations":      n_irr,
        "total_supply_ml":    total_ml_day,
        "supply_per_shot_ml": supply_ml_per_trigger,
        "drain_target_pct":   drain_pct,
        "daily_gsr_mj_m2":    round(gsr, 2),
        "temp_max":           round(t_max, 1),
        "temp_min":           round(t_min, 1),
        "temp_mean":          round(t_mean, 1),
        "obs_date":           obs_date,
        "source":             source,
        "method":             "hargreaves_etc",
        "note":               note,
    }


def get_solar_irrigation_schedule(
    farm_id: str,
    trigger_mj_m2: float = 2.0,
    supply_ml_per_trigger: float = 250.0,
    min_irrigations: int = 2,
    max_irrigations: int = 12,
    crop_ko: Optional[str] = None,
    growth_stage: str = "mid",
) -> dict:
    """KMA ASOS 일사량 기반 내일 관수 스케줄 예측 (Priva 방식 + ETc 보정).

    Priva 일사비례 관수 원칙 (기본):
      - 누적 일사량 trigger_mj_m2 (기본 2 MJ/m²) 도달 시 1회 관수
      - 전일 sumGsr(MJ/m²)을 내일 예보값으로 사용 (단순 지속성 예측)
      - 첫 관수: 일출 후 30분, 마지막 관수: 일몰 2시간 전까지

    ETc 통합 (crop_ko 제공 시):
      - Hargreaves ET₀ 계산 → ETc = ET₀ × Kc
      - Priva 횟수와 ETc 기반 횟수를 블렌딩하여 더 정확한 권고

    Args:
        farm_id:               농가 ID (FARM_STATION 매핑)
        trigger_mj_m2:         관수 트리거 일사량 임계값 (MJ/m²)
        supply_ml_per_trigger: 1회 관수량 (ml/slab)
        min_irrigations:       최소 관수 횟수 (흐린 날 보호)
        max_irrigations:       최대 관수 횟수 (맑은 날 제한)
        crop_ko:               작목명 (있으면 ETc 기반 보정 활성화)
        growth_stage:          생육 단계 "initial"|"dev"|"mid"|"late"

    Returns:
        dict with keys:
          daily_gsr_mj_m2       - 전일 누적 일사량 (MJ/m²)
          solar_rad_avg_wm2     - 평균 일사량 추정 (W/m²)
          n_irrigations         - 권장 관수 횟수
          total_supply_ml       - 권장 총 공급량 (ml/slab)
          first_irrigation      - 첫 관수 예상 시각 "HH:MM"
          last_irrigation       - 마지막 관수 예상 시각 "HH:MM"
          trigger_mj_m2         - 사용된 트리거 임계값
          obs_date              - 참조 날짜 (어제)
          source                - 데이터 출처
          note                  - 상태 메모
          et0_mm_day            - ET₀ (crop_ko 제공 시)
          etc_mm_day            - ETc (crop_ko 제공 시)
          etc_method            - ETc 계산 방법 (crop_ko 제공 시)
    """
    import math as _math
    import datetime as _dt

    item = get_latest_weather(farm_id)
    today = _dt.date.today()

    # ── 일사량 파싱 ──────────────────────────────────────────────────────────
    gsr_mj: Optional[float] = None
    solar_avg: Optional[float] = None
    if item:
        try:
            raw_gsr = float(item.get("sumGsr", 0) or 0)
            if raw_gsr > 0:
                gsr_mj    = round(raw_gsr, 2)
                solar_avg = round(raw_gsr * 11.574, 1)  # MJ/m²/day → W/m² 일평균
        except (TypeError, ValueError):
            pass
        if gsr_mj is None:
            try:
                peak = float(item.get("hr1MaxIcsr", 0) or 0)
                if peak > 0:
                    solar_avg = round(peak * 0.40, 1)
                    # W/m² 일평균 → MJ/m²/day (역산)
                    gsr_mj = round(solar_avg / 11.574, 2)
            except (TypeError, ValueError):
                pass

    # 데이터 없을 때 계절 평균 fallback (한국 스마트팜 기준)
    if gsr_mj is None:
        month = today.month
        _MONTHLY_GSR = {
            1: 7.5, 2: 9.8, 3: 12.5, 4: 15.0, 5: 16.5, 6: 15.8,
            7: 13.2, 8: 14.0, 9: 13.0, 10: 11.5, 11: 8.5, 12: 7.0
        }
        gsr_mj    = _MONTHLY_GSR.get(month, 12.0)
        solar_avg = round(gsr_mj * 11.574, 1)
        note      = f"ASOS 데이터 없음 — {month}월 계절 평균 사용"
        source    = "seasonal_average"
    else:
        note   = f"전일({item.get('tm','?')}) ASOS 실측값 기반 단순 지속성 예측"
        source = "kma_asos_yesterday"

    # ── 관수 횟수 산출 ────────────────────────────────────────────────────────
    n_raw = gsr_mj / trigger_mj_m2
    n_irr = max(min_irrigations, min(max_irrigations, round(n_raw)))

    # ── 관수 시각 분포 계산 ───────────────────────────────────────────────────
    # 일출/일몰 시각 추정 (한국 36.5°N 기준)
    month_now = today.month
    _SUNRISE_H = {1: 7.5, 2: 7.1, 3: 6.5, 4: 5.7, 5: 5.2, 6: 5.0,
                  7: 5.2, 8: 5.5, 9: 6.0, 10: 6.4, 11: 7.0, 12: 7.5}
    _SUNSET_H  = {1: 17.5, 2: 18.2, 3: 18.8, 4: 19.5, 5: 20.0, 6: 20.3,
                  7: 20.2, 8: 19.7, 9: 18.8, 10: 18.0, 11: 17.3, 12: 17.2}
    sunrise = _SUNRISE_H.get(month_now, 6.5)
    sunset  = _SUNSET_H.get(month_now, 18.5)

    # 첫 관수: 일출 + 30분, 마지막 관수: 일몰 - 2시간
    first_h = sunrise + 0.5
    last_h  = sunset  - 2.0
    last_h  = max(first_h + 1.0, last_h)

    def _hm(h: float) -> str:
        return f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"

    total_supply = round(n_irr * supply_ml_per_trigger, 0)

    result = {
        "daily_gsr_mj_m2":       gsr_mj,
        "solar_rad_avg_wm2":     solar_avg,
        "n_irrigations":         n_irr,
        "total_supply_ml":       total_supply,
        "supply_per_trigger_ml": supply_ml_per_trigger,
        "first_irrigation":      _hm(first_h),
        "last_irrigation":       _hm(last_h),
        "trigger_mj_m2":         trigger_mj_m2,
        "obs_date":              item.get("tm") if item else None,
        "station_id":            FARM_STATION.get(farm_id),
        "source":                source,
        "note":                  note,
    }

    # ── ETc + Priva 전체 알고리즘 통합 (crop_ko 제공 시) ────────────────────
    if crop_ko:
        try:
            etc_data = get_etc_irrigation(
                farm_id, crop_ko=crop_ko, growth_stage=growth_stage,
                supply_ml_per_trigger=supply_ml_per_trigger,
            )
            # ETc 기반 횟수 블렌딩 (Priva 단순 + ETc 각 0.5)
            n_etc   = etc_data.get("n_irrigations", n_irr)
            n_blend = max(min_irrigations, min(max_irrigations,
                          round(0.5 * n_irr + 0.5 * n_etc)))
            result["n_irrigations"]  = n_blend
            result["total_supply_ml"] = round(n_blend * supply_ml_per_trigger, 0)
            result["et0_mm_day"]     = etc_data.get("et0_mm_day")
            result["etc_mm_day"]     = etc_data.get("etc_mm_day")
            result["kc"]             = etc_data.get("kc")
            result["growth_stage"]   = growth_stage
            result["etc_method"]     = "hargreaves_etc_blended"

            # ── Priva 전체 알고리즘 (증산량·P/I·3-상황) ────────────────────
            try:
                from api.services.priva_irrigation import (   # type: ignore
                    PrivaIrrigationConfig, compute_priva_schedule,
                    get_default_config,
                )
                _et0_val = etc_data.get("et0_mm_day") or 3.0
                _pcfg = get_default_config(crop_ko, growth_stage)
                _pcfg.supply_per_shot_ml = supply_ml_per_trigger
                _priva = compute_priva_schedule(
                    et0_mm=float(_et0_val),
                    daily_gsr_mj_m2=gsr_mj,
                    solar_avg_wm2=solar_avg or 200.0,
                    config=_pcfg,
                    date_str=str(today),
                )
                result["priva_schedule"] = _priva.to_dict()
                # Priva 증산량 기반 횟수로 최종 횟수 갱신
                n_final = max(min_irrigations, min(max_irrigations, _priva.n_irrigations))
                result["n_irrigations"]  = n_final
                result["total_supply_ml"] = _priva.supply_total_ml
                result["priva_drain_target_pct"] = _priva.drain_target_pct
                result["priva_transpiration_mm"] = _priva.transpiration_mm
                result["priva_pi_correction_lm2"] = _priva.pi_correction_lm2
                note_priva = (
                    f" | Priva 증산모델: 증산={_priva.transpiration_mm}mm "
                    f"공급={_priva.supply_total_ml:.0f}ml ({n_final}회) "
                    f"배액목표={_priva.drain_target_pct}%"
                )
            except Exception as _e_priva:
                logger.debug("[kma_service] Priva 전체 스케줄 계산 생략: %s", _e_priva)
                note_priva = ""

            result["note"] = (
                f"{note} | ETc보정: ET₀={etc_data.get('et0_mm_day')}mm "
                f"ETc={etc_data.get('etc_mm_day')}mm (Kc={etc_data.get('kc')}) "
                f"Priva {n_irr}회+ETc {n_etc}회 → 블렌딩 {n_blend}회"
                + note_priva
            )
        except Exception as _e_etc:
            logger.warning("[kma_service] ETc 계산 실패(%s) — Priva 단독 사용", _e_etc)

    return result


def get_weather_summary(farm_id: str) -> dict:
    """환경 엔드포인트용 요약 dict 반환.

    {
      "temp_external":  float | None,
      "humidity_ext":   float | None,
      "solar_rad_est":  float | None,   # W/m² 추정
      "soil_temp":      float | None,
      "wind_speed_ext": float | None,
      "obs_date":       str | None,
      "station_id":     int | None,
      "source":         "kma_asos",
    }
    """
    item = get_latest_weather(farm_id)
    if item is None:
        return {
            "temp_external": None, "humidity_ext": None,
            "solar_rad_est": None, "soil_temp": None,
            "wind_speed_ext": None, "obs_date": None,
            "station_id": FARM_STATION.get(farm_id),
            "source": "kma_asos",
        }

    def _f(key: str) -> Optional[float]:
        try:
            v = float(item[key])
            return v if v != 0.0 or item[key] != "" else None
        except (KeyError, TypeError, ValueError):
            return None

    # 일사량 추정 (hr1MaxIcsr 우선, 없으면 sumGsr 환산)
    solar: Optional[float] = None
    peak = _f("hr1MaxIcsr")
    if peak and peak > 0:
        solar = round(peak * 0.40, 1)
    else:
        gsr = _f("sumGsr")
        if gsr and gsr > 0:
            solar = round(gsr * 11.574, 1)

    return {
        "temp_external":  _f("avgTa"),
        "humidity_ext":   _f("avgRhm"),
        "solar_rad_est":  solar,
        "soil_temp":      _f("avgTs"),
        "wind_speed_ext": _f("avgWs"),
        "obs_date":       item.get("tm"),
        "station_id":     FARM_STATION.get(farm_id),
        "source":         "kma_asos",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 단기예보 (향후 3일) — VilageFcstInfoService_2.0/getVilageFcst
# ═══════════════════════════════════════════════════════════════════════════════

def _latest_fcst_base(now: Optional[datetime] = None) -> tuple[str, str]:
    """현재 시각 기준 가장 최근 발표된 단기예보 base_date / base_time 반환.

    단기예보는 매일 02, 05, 08, 11, 14, 17, 20, 23시(KST)에 발표.
    API는 발표 후 10분 이후부터 조회 가능하므로 10분 안전여유 포함.
    """
    import datetime as _dt
    KST = timezone(timedelta(hours=9))
    now_kst = (now or datetime.now(tz=timezone.utc)).astimezone(KST)
    issue_hours = [2, 5, 8, 11, 14, 17, 20, 23]

    current_h = now_kst.hour + (now_kst.minute - 10) / 60  # 10분 지연 고려
    # 현재보다 이전이면서 가장 늦은 발표시각 선택
    base_h = max((h for h in issue_hours if h <= current_h), default=23)

    # 00시~02시 10분 이전: 어제 23시 예보 사용
    if current_h < issue_hours[0]:
        base_dt = (now_kst - _dt.timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
    else:
        base_dt = now_kst.replace(hour=base_h, minute=0, second=0, microsecond=0)

    return base_dt.strftime("%Y%m%d"), f"{base_dt.hour:04d}"


def _fetch_village_fcst(nx: int, ny: int) -> list[dict]:
    """단기예보 API 호출 → items 리스트 반환."""
    svc_key = _get_service_key()
    if not svc_key:
        logger.warning("[kma_service] KMA_SERVICE_KEY 미설정 — 단기예보 비활성화")
        return []

    base_date, base_time = _latest_fcst_base()
    params = urllib.parse.urlencode({
        "serviceKey": svc_key,
        "pageNo":      1,
        "numOfRows":   1000,
        "dataType":    "JSON",
        "base_date":   base_date,
        "base_time":   base_time,
        "nx":          nx,
        "ny":          ny,
    })
    url = f"{_FCST_BASE_URL}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        rc = body.get("response", {}).get("header", {}).get("resultCode", "")
        if rc not in ("00", "0000"):
            logger.warning("[kma_service] 단기예보 resultCode=%s nx=%s ny=%s", rc, nx, ny)
            return []
        return body["response"]["body"]["items"]["item"] or []
    except Exception as exc:
        logger.error("[kma_service] 단기예보 fetch error nx=%s ny=%s: %s", nx, ny, exc)
        return []


def _parse_fcst_items(items: list[dict]) -> dict[str, dict]:
    """단기예보 items → {YYYYMMDD: {tmx, tmn, pop_max, sky_avg, pty_any, reh_avg}} 집계.

    category 코드 (관련 항목만 추출):
      TMP  : 1시간 기온 (°C)
      REH  : 1시간 습도 (%)
      TMX  : 일 최고기온 (°C)
      TMN  : 일 최저기온 (°C)
      SKY  : 하늘 상태 (1=맑음, 3=구름많음, 4=흐림)
      PTY  : 강수형태 (0=없음, 1=비, 2=비/눈, 3=눈, 4=소나기)
      POP  : 강수확률 (%)
    """
    daily: dict[str, dict] = {}

    for it in items:
        fcst_date = it.get("fcstDate", "")
        if not fcst_date or len(fcst_date) != 8:
            continue
        cat  = it.get("category", "")
        val  = it.get("fcstValue", "")
        day  = daily.setdefault(fcst_date, {
            "tmp_list": [], "reh_list": [], "pop_list": [],
            "sky_list": [], "pty_any": 0,
            "tmx": None, "tmn": None,
        })
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue

        if cat == "TMP":
            day["tmp_list"].append(fval)
        elif cat == "REH":
            day["reh_list"].append(fval)
        elif cat == "POP":
            day["pop_list"].append(fval)
        elif cat == "SKY":
            day["sky_list"].append(fval)
        elif cat == "PTY" and fval > 0:
            day["pty_any"] = 1
        elif cat == "TMX":
            day["tmx"] = fval
        elif cat == "TMN":
            day["tmn"] = fval

    result: dict[str, dict] = {}
    for fcst_date, d in sorted(daily.items()):
        tmp_list = d["tmp_list"]
        reh_list = d["reh_list"]
        pop_list = d["pop_list"]
        sky_list = d["sky_list"]

        tmx = d["tmx"] if d["tmx"] is not None else (max(tmp_list) if tmp_list else None)
        tmn = d["tmn"] if d["tmn"] is not None else (min(tmp_list) if tmp_list else None)
        tmp_avg  = round(sum(tmp_list) / len(tmp_list), 1) if tmp_list else None
        reh_avg  = round(sum(reh_list) / len(reh_list), 1) if reh_list else None
        pop_max  = round(max(pop_list), 0) if pop_list else None
        sky_avg  = round(sum(sky_list) / len(sky_list), 2) if sky_list else None

        # 하늘 상태 텍스트 변환 (평균 SKY 값 기반)
        sky_label = "맑음"
        if sky_avg is not None:
            if sky_avg >= 3.5:
                sky_label = "흐림"
            elif sky_avg >= 2.5:
                sky_label = "구름많음"

        # 월별 계절 평균 일사량 추정 (W/m²) — sky_avg 기반 보정
        month_now = int(fcst_date[4:6])
        _MONTHLY_SOLAR_WM2 = {
            1: 87.0, 2: 113.5, 3: 144.7, 4: 173.7,
            5: 191.2, 6: 183.0, 7: 152.9, 8: 162.1,
            9: 150.6, 10: 133.2, 11: 98.6, 12: 81.1,
        }
        base_solar = _MONTHLY_SOLAR_WM2.get(month_now, 140.0)
        if sky_avg is not None:
            # sky 1→맑음: ×1.20, sky 3→구름많음: ×0.70, sky 4→흐림: ×0.45
            sky_factor = max(0.3, 1.20 - (sky_avg - 1.0) * 0.375)
            solar_est = round(base_solar * sky_factor, 1)
        else:
            solar_est = base_solar

        result[fcst_date] = {
            "date":          fcst_date,
            "temp_max":      round(tmx, 1) if tmx is not None else None,
            "temp_min":      round(tmn, 1) if tmn is not None else None,
            "temp_avg":      tmp_avg,
            "humidity_avg":  reh_avg,
            "precip_prob":   pop_max,
            "sky_code":      sky_avg,
            "sky_label":     sky_label,
            "rain_expected": bool(d["pty_any"]),
            "solar_est_wm2": solar_est,
        }

    return result


def get_forecast_3day(farm_id: str) -> list[dict]:
    """단기예보 3일치 일별 요약 반환 (캐시 3시간).

    Returns:
        List of daily dicts (최대 3일), 오늘 포함:
        [
          {
            "date":          "YYYYMMDD",
            "temp_max":      float,
            "temp_min":      float,
            "temp_avg":      float,
            "humidity_avg":  float,
            "precip_prob":   float,   # 0~100
            "sky_label":     str,     # "맑음" | "구름많음" | "흐림"
            "rain_expected": bool,
            "solar_est_wm2": float,   # W/m² 추정
          }, ...
        ]
        API 키 없거나 오류 시 → 월 계절 평균 기반 fallback 3일 반환.
    """
    with _cache_lock:
        entry = _fcst_cache.get(farm_id)
        if entry:
            age = (datetime.now(tz=timezone.utc) - entry["fetched_at"]).total_seconds()
            if age < _FCST_CACHE_TTL:
                return entry["data"]

    grid = FARM_GRID.get(farm_id)
    days_data: dict[str, dict] = {}

    if grid:
        items = _fetch_village_fcst(nx=grid[0], ny=grid[1])
        if items:
            days_data = _parse_fcst_items(items)

    # fallback: API 실패 시 계절 평균 3일 생성
    if not days_data:
        days_data = _build_seasonal_fallback_3day()

    # 오늘 이후 최대 3일만 선택
    today_str = date.today().strftime("%Y%m%d")
    result = [
        v for k, v in sorted(days_data.items())
        if k >= today_str
    ][:3]

    with _cache_lock:
        _fcst_cache[farm_id] = {
            "data": result,
            "fetched_at": datetime.now(tz=timezone.utc),
        }

    if result:
        logger.info(
            "[kma_service] 단기예보 farm=%s dates=%s",
            farm_id, [d["date"] for d in result],
        )
    return result


def _build_seasonal_fallback_3day() -> dict[str, dict]:
    """API 장애 시 계절 평균 기반 3일 fallback 데이터 생성."""
    _MONTHLY = {
        1:  {"tmx": 3.2,  "tmn": -5.2, "reh": 59.0, "solar": 87.0},
        2:  {"tmx": 6.1,  "tmn": -2.9, "reh": 60.0, "solar": 113.5},
        3:  {"tmx": 12.3, "tmn": 2.4,  "reh": 61.0, "solar": 144.7},
        4:  {"tmx": 19.0, "tmn": 8.5,  "reh": 62.0, "solar": 173.7},
        5:  {"tmx": 24.3, "tmn": 13.9, "reh": 66.0, "solar": 191.2},
        6:  {"tmx": 28.8, "tmn": 19.3, "reh": 72.0, "solar": 183.0},
        7:  {"tmx": 30.5, "tmn": 22.8, "reh": 82.0, "solar": 152.9},
        8:  {"tmx": 31.0, "tmn": 23.0, "reh": 81.0, "solar": 162.1},
        9:  {"tmx": 26.3, "tmn": 17.5, "reh": 74.0, "solar": 150.6},
        10: {"tmx": 20.4, "tmn": 10.1, "reh": 68.0, "solar": 133.2},
        11: {"tmx": 12.2, "tmn": 2.3,  "reh": 66.0, "solar": 98.6},
        12: {"tmx": 5.0,  "tmn": -3.5, "reh": 62.0, "solar": 81.1},
    }
    result = {}
    for i in range(3):
        d = date.today() + timedelta(days=i)
        m = d.month
        s = _MONTHLY.get(m, _MONTHLY[6])
        dstr = d.strftime("%Y%m%d")
        result[dstr] = {
            "date":          dstr,
            "temp_max":      s["tmx"],
            "temp_min":      s["tmn"],
            "temp_avg":      round((s["tmx"] + s["tmn"]) / 2, 1),
            "humidity_avg":  s["reh"],
            "precip_prob":   20.0,   # 계절 평균 강수확률
            "sky_code":      None,
            "sky_label":     "구름많음",
            "rain_expected": False,
            "solar_est_wm2": s["solar"],
            "source":        "seasonal_fallback",
        }
    return result


def get_forecast_summary(farm_id: str) -> dict:
    """단기예보 3일 요약 dict (API 엔드포인트용).

    Returns:
        {
          "days": [day0, day1, day2],   # 오늘~3일 후
          "tomorrow": dict,             # 내일 예보 (편의 필드)
          "avg_temp_3day": float,
          "avg_humidity_3day": float,
          "rain_days": int,
          "source": "kma_vilagefcst" | "seasonal_fallback",
        }
    """
    days = get_forecast_3day(farm_id)
    if not days:
        return {"days": [], "source": "error"}

    source = "seasonal_fallback" if days[0].get("source") == "seasonal_fallback" \
             else "kma_vilagefcst"

    temps = [d["temp_avg"] for d in days if d.get("temp_avg") is not None]
    rhehs = [d["humidity_avg"] for d in days if d.get("humidity_avg") is not None]

    return {
        "days":               days,
        "tomorrow":           days[1] if len(days) > 1 else (days[0] if days else {}),
        "avg_temp_3day":      round(sum(temps) / len(temps), 1) if temps else None,
        "avg_humidity_3day":  round(sum(rhehs) / len(rhehs), 1) if rhehs else None,
        "rain_days":          sum(1 for d in days if d.get("rain_expected")),
        "source":             source,
    }
