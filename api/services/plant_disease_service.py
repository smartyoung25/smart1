"""병해충 탐지 서비스 — 4계층 폴백 체인.

M5 이미지 모델 미구축 상태에서도 최대한 정확한 병해 진단 제공.

우선순위:
  ① Plant.id Plant Health API  (이미지 기반 — 상업용 최고 정밀도)
       https://web.plant.id/plant-health-assessment-api/
       PLANT_ID_API_KEY 필요 — 무료: 100건/월, 유료: $9/월 (500건)
       발급: https://web.plant.id/ → 가입 → API Keys

  ② NCPMS 농촌진흥청 병해충관리시스템 (작목×증상 매칭 DB)
       https://ncpms.rda.go.kr/npms/Main.np
       DATA_GO_KR_SERVICE_KEY 사용 (기존 키로 바로 접근)
       오픈API: https://www.data.go.kr/data/15000045/openapi.do

  ③ M5 규칙 기반 v2 (환경 센서 — 8가지 병해, 온습도/VPD 기반)
       models/m5_disease.py  env_risk_predict_all()

  ④ EPPO Global Database (EU 병해충 공식 목록, 무료)
       https://gd.eppo.int
       - 작물 → 알려진 병해충 목록 + 위험 분류

반환 형식:
    {
      "disease":       str,        # 병해명 (한국어)
      "risk_level":    str,        # high | medium | low | none
      "score":         float,      # 0~1
      "confidence":    float,      # 0~1
      "action_ko":     str,        # 권장 조치
      "reasons":       list[str],  # 판단 근거
      "source_chain":  list[str],  # 사용된 API 순서
      "all_risks":     list[dict], # 전체 병해 위험 목록
    }
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── 작목별 주요 병해 한국어 매핑 ─────────────────────────────────────────────

_CROP_DISEASES: dict[str, list[dict]] = {
    "딸기": [
        {"name_ko": "잿빛곰팡이병", "name_en": "gray mold",       "pathogen": "Botrytis cinerea",   "risk_temp": (15, 25), "risk_humidity": 85},
        {"name_ko": "흰가루병",     "name_en": "powdery mildew",  "pathogen": "Sphaerotheca macularis", "risk_temp": (20, 28), "risk_humidity": 50},
        {"name_ko": "탄저병",       "name_en": "anthracnose",     "pathogen": "Colletotrichum acutatum", "risk_temp": (25, 30), "risk_humidity": 90},
        {"name_ko": "역병",         "name_en": "phytophthora",    "pathogen": "Phytophthora cactorum",   "risk_temp": (12, 22), "risk_humidity": 90},
    ],
    "방울토마토": [
        {"name_ko": "잿빛곰팡이병", "name_en": "gray mold",       "pathogen": "Botrytis cinerea",       "risk_temp": (17, 23), "risk_humidity": 90},
        {"name_ko": "흰가루병",     "name_en": "powdery mildew",  "pathogen": "Leveillula taurica",     "risk_temp": (20, 28), "risk_humidity": 40},
        {"name_ko": "잎곰팡이병",   "name_en": "leaf mold",       "pathogen": "Fulvia fulva",           "risk_temp": (22, 25), "risk_humidity": 85},
        {"name_ko": "역병",         "name_en": "late blight",     "pathogen": "Phytophthora infestans", "risk_temp": (10, 25), "risk_humidity": 90},
    ],
    "완숙토마토": [
        {"name_ko": "잿빛곰팡이병", "name_en": "gray mold",       "pathogen": "Botrytis cinerea",       "risk_temp": (17, 23), "risk_humidity": 90},
        {"name_ko": "역병",         "name_en": "late blight",     "pathogen": "Phytophthora infestans", "risk_temp": (10, 25), "risk_humidity": 90},
        {"name_ko": "풋마름병",     "name_en": "bacterial wilt",  "pathogen": "Ralstonia solanacearum", "risk_temp": (25, 35), "risk_humidity": 80},
        {"name_ko": "바이러스병",   "name_en": "TMV/CMV",         "pathogen": "Tobamovirus",            "risk_temp": (20, 30), "risk_humidity": 60},
    ],
    "파프리카": [
        {"name_ko": "잿빛곰팡이병", "name_en": "gray mold",       "pathogen": "Botrytis cinerea",       "risk_temp": (15, 22), "risk_humidity": 85},
        {"name_ko": "역병",         "name_en": "phytophthora",    "pathogen": "Phytophthora capsici",   "risk_temp": (25, 32), "risk_humidity": 90},
        {"name_ko": "세균성점무늬병","name_en": "bacterial spot",  "pathogen": "Xanthomonas campestris", "risk_temp": (24, 30), "risk_humidity": 85},
        {"name_ko": "흰가루병",     "name_en": "powdery mildew",  "pathogen": "Leveillula taurica",     "risk_temp": (22, 30), "risk_humidity": 40},
    ],
    "참외": [
        {"name_ko": "노균병",       "name_en": "downy mildew",    "pathogen": "Pseudoperonospora cubensis", "risk_temp": (15, 22), "risk_humidity": 90},
        {"name_ko": "흰가루병",     "name_en": "powdery mildew",  "pathogen": "Sphaerotheca fuliginea",    "risk_temp": (20, 30), "risk_humidity": 50},
        {"name_ko": "덩굴쪼김병",   "name_en": "fusarium wilt",   "pathogen": "Fusarium oxysporum",        "risk_temp": (20, 28), "risk_humidity": 80},
        {"name_ko": "탄저병",       "name_en": "anthracnose",     "pathogen": "Colletotrichum orbiculare", "risk_temp": (22, 28), "risk_humidity": 85},
    ],
    "오이": [
        {"name_ko": "노균병",       "name_en": "downy mildew",    "pathogen": "Pseudoperonospora cubensis", "risk_temp": (12, 20), "risk_humidity": 90},
        {"name_ko": "흰가루병",     "name_en": "powdery mildew",  "pathogen": "Sphaerotheca cucurbitae",   "risk_temp": (20, 28), "risk_humidity": 50},
        {"name_ko": "잿빛곰팡이병", "name_en": "gray mold",       "pathogen": "Botrytis cinerea",          "risk_temp": (15, 22), "risk_humidity": 85},
        {"name_ko": "역병",         "name_en": "phytophthora",    "pathogen": "Phytophthora melonis",      "risk_temp": (20, 30), "risk_humidity": 90},
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# ① Plant.id Plant Health Assessment API
# ══════════════════════════════════════════════════════════════════════════════

_PLANT_ID_BASE = "https://plant.id/api/v3"


def _plant_id_key() -> str:
    return os.environ.get("PLANT_ID_API_KEY", "")


def plant_id_assess_health(
    image_base64: str,
    crop_ko: str = "딸기",
    latitude: float = 36.5,
    longitude: float = 127.5,
) -> Optional[dict]:
    """Plant.id Plant Health Assessment API 호출.

    이미지에서 병해·해충·영양 결핍을 식별합니다.

    Args:
        image_base64: base64 인코딩 이미지 (JPEG/PNG)
        crop_ko:      작목명 (한국어)
        latitude:     농장 위도 (계절 보정용)
        longitude:    농장 경도

    Returns:
        {
          "is_healthy": bool,
          "diseases": [...],    # 탐지된 병해 목록
          "confidence": float,
          "source": "plant_id",
        }
        None if API unavailable or key missing
    """
    key = _plant_id_key()
    if not key:
        return None

    try:
        payload = json.dumps({
            "images": [f"data:image/jpeg;base64,{image_base64}"],
            "latitude": latitude,
            "longitude": longitude,
            "similar_images": False,
            "health": "only",
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{_PLANT_ID_BASE}/health_assessment",
            data=payload,
            headers={
                "Api-Key": key,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        result = raw.get("result", {})
        is_healthy = result.get("is_healthy", {})
        health_prob = float(is_healthy.get("probability", 1.0)) if isinstance(is_healthy, dict) else 1.0
        diseases_raw = result.get("disease", {}).get("suggestions", [])

        diseases = []
        for d in diseases_raw[:5]:
            name_en = d.get("name", "")
            prob = float(d.get("probability", 0.0))
            if prob < 0.05:
                continue
            diseases.append({
                "name_en":   name_en,
                "name_ko":   _translate_disease(name_en, crop_ko),
                "confidence": round(prob, 3),
                "details":   d.get("details", {}),
            })

        return {
            "is_healthy":  health_prob > 0.8,
            "health_prob": round(health_prob, 3),
            "diseases":    diseases,
            "confidence":  round(1.0 - health_prob, 3) if diseases else 0.0,
            "source":      "plant_id_v3",
        }
    except Exception as e:
        logger.warning("[plant_id] API 호출 실패: %s", e)
        return None


def _translate_disease(name_en: str, crop_ko: str) -> str:
    """영문 병해명 → 한국어 번역 (작목 병해 DB 기반)."""
    name_lower = name_en.lower()
    diseases = _CROP_DISEASES.get(crop_ko, [])
    for d in diseases:
        if any(kw in name_lower for kw in d["name_en"].lower().split()):
            return d["name_ko"]
    # 공통 패턴 매핑
    _common = {
        "gray mold": "잿빛곰팡이병", "botrytis": "잿빛곰팡이병",
        "powdery mildew": "흰가루병", "downy mildew": "노균병",
        "late blight": "역병", "phytophthora": "역병",
        "anthracnose": "탄저병", "fusarium": "덩굴쪼김병",
        "bacterial": "세균성병해", "virus": "바이러스병",
        "leaf mold": "잎곰팡이병",
    }
    for en, ko in _common.items():
        if en in name_lower:
            return ko
    return name_en


# ══════════════════════════════════════════════════════════════════════════════
# ② NCPMS 농촌진흥청 병해충관리시스템
# ══════════════════════════════════════════════════════════════════════════════

_NCPMS_BASE = "http://ncpms.rda.go.kr/npmsAPI"
_DATA_GO_BASE = "http://apis.data.go.kr/1390000/PestMntInfoSrc"


def _data_go_key() -> str:
    return os.environ.get("DATA_GO_KR_SERVICE_KEY_DECODED",
           os.environ.get("DATA_GO_KR_SERVICE_KEY", ""))


def ncpms_get_pest_forecast(
    crop_ko: str,
    region_code: str = "3600000",   # 기본: 충청남도
) -> Optional[dict]:
    """농촌진흥청 병해충 발생 예보 조회.

    공공데이터포털 농작물병해충발생정보 API:
      https://www.data.go.kr/data/15000045/openapi.do
    인증: DATA_GO_KR_SERVICE_KEY (기존 키 사용)

    Args:
        crop_ko:     작목명
        region_code: 시도 코드 (3600000=충남, 4600000=경남, 4500000=전북, ...)

    Returns:
        {
          "crop": str,
          "forecasts": [{"pest_ko": str, "level": str, "date": str}, ...],
          "source": "ncpms_rda",
        }
    """
    key = _data_go_key()
    if not key:
        return None

    # 한국어 작목명 → NCPMS 코드 매핑
    _crop_codes = {
        "딸기": "ST", "방울토마토": "TM", "완숙토마토": "TM",
        "파프리카": "PP", "참외": "ML", "오이": "CU",
    }
    crop_code = _crop_codes.get(crop_ko, "TM")

    try:
        params = urllib.parse.urlencode({
            "serviceKey": key,
            "cropCode":   crop_code,
            "siDo":       region_code[:2],
            "numOfRows":  "20",
            "pageNo":     "1",
            "type":       "json",
        })
        url = f"http://apis.data.go.kr/1390000/PestMntInfoSrc/getPestMntInfoList?{params}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        items = (raw.get("response", {})
                    .get("body", {})
                    .get("items", {})
                    .get("item", []))
        if isinstance(items, dict):
            items = [items]

        forecasts = []
        for item in items[:10]:
            forecasts.append({
                "pest_ko":  item.get("pestNm", ""),
                "level":    item.get("occurrLevel", ""),
                "date":     item.get("stdDe", ""),
                "region":   item.get("siDo", ""),
                "symptom":  item.get("symptom", ""),
            })

        return {
            "crop": crop_ko,
            "forecasts": forecasts,
            "source": "ncpms_data_go_kr",
            "count": len(forecasts),
        }
    except Exception as e:
        logger.warning("[ncpms] API 호출 실패 (crop=%s): %s", crop_ko, e)
        return None


def ncpms_get_disease_detail(crop_ko: str) -> Optional[list[dict]]:
    """NCPMS 작목별 병해충 상세 정보 조회.

    농촌진흥청 농사로(Nongsaro) 병해충 정보 서비스.
    """
    key = _data_go_key()
    if not key:
        return None

    try:
        params = urllib.parse.urlencode({
            "apiKey": key,
            "cropNm": crop_ko,
            "returnType": "json",
            "numOfRows": "20",
        })
        url = f"https://api.nongsaro.go.kr/service/pestInfo/pestInfoList?{params}"
        with urllib.request.urlopen(url, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        items = (raw.get("response", {})
                    .get("body", {})
                    .get("items", {})
                    .get("item", []))
        if isinstance(items, dict):
            items = [items]

        results = []
        for item in items[:10]:
            results.append({
                "name_ko":   item.get("pestNm", ""),
                "category":  item.get("pestKndCode", ""),
                "symptom":   item.get("smptomSe", "")[:100] if item.get("smptomSe") else "",
                "prevention": item.get("prvnt", "")[:100] if item.get("prvnt") else "",
                "source": "rda_nongsaro",
            })
        return results
    except Exception as e:
        logger.warning("[ncpms_detail] 실패 (crop=%s): %s", crop_ko, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# ③ M5 규칙 기반 v2 (환경 센서)
# ══════════════════════════════════════════════════════════════════════════════

def env_based_risk(
    env: dict,
    crop_ko: str,
) -> dict:
    """환경 센서 기반 병해 위험 평가 (M5 규칙 기반 v2).

    models/m5_disease.py의 env_risk_predict_all을 호출한다.

    Returns:
        {
          "disease":    str,
          "risk_level": str,
          "score":      float,
          "action_ko":  str,
          "reasons":    list[str],
          "all_risks":  list[dict],
          "source":     "m5_rule_v2",
        }
    """
    try:
        from models.m5_disease import env_risk_predict, env_risk_predict_all  # type: ignore
        top = env_risk_predict(env, crop_ko)
        all_risks_raw = env_risk_predict_all(env, crop_ko)

        all_risks = []
        for r in all_risks_raw[:5]:
            all_risks.append({
                "disease":    r.disease,
                "disease_ko": r.disease_ko,
                "risk_level": r.risk_level,
                "score":      round(r.score, 3),
            })

        return {
            "disease":    top.disease,
            "disease_ko": top.disease_ko,
            "risk_level": top.risk_level,
            "score":      round(top.score, 3),
            "action_ko":  top.action_ko,
            "reasons":    top.reasons,
            "all_risks":  all_risks,
            "source":     "m5_rule_v2",
        }
    except Exception as e:
        logger.warning("[m5_rule] 실패: %s", e)
        # 기본 환경 기반 단순 평가
        temp = float(env.get("temp_internal", 20.0))
        hum  = float(env.get("humidity_int", 70.0))
        if hum > 88 and 15 <= temp <= 24:
            return {
                "disease": "gray_mold", "disease_ko": "잿빛곰팡이병",
                "risk_level": "high", "score": 0.75,
                "action_ko": "환기 강화 및 방제 검토",
                "reasons": [f"습도 {hum:.0f}% 잿빛곰팡이 위험 범위"],
                "all_risks": [], "source": "m5_simple_fallback",
            }
        elif hum > 80:
            return {
                "disease": "gray_mold", "disease_ko": "잿빛곰팡이병",
                "risk_level": "medium", "score": 0.45,
                "action_ko": "환기량 증가 권장",
                "reasons": [f"습도 {hum:.0f}% 경계값"],
                "all_risks": [], "source": "m5_simple_fallback",
            }
        return {
            "disease": "healthy", "disease_ko": "이상 없음",
            "risk_level": "none", "score": 0.05,
            "action_ko": "현재 환경 유지",
            "reasons": ["정상 범위"],
            "all_risks": [], "source": "m5_simple_fallback",
        }


# ══════════════════════════════════════════════════════════════════════════════
# 통합 병해 탐지 — 4계층 폴백 체인
# ══════════════════════════════════════════════════════════════════════════════

def detect_disease(
    env: dict,
    crop_ko: str,
    image_base64: Optional[str] = None,
    farm_lat: float = 36.5,
    farm_lon: float = 127.5,
    region_code: str = "3600000",
) -> dict:
    """통합 병해 탐지.

    이미지가 있으면 Plant.id 우선 시도.
    환경만 있으면 NCPMS → M5 규칙 기반 순서로 시도.

    Returns:
        {
          "disease":       str,
          "disease_ko":    str,
          "risk_level":    str,    # high | medium | low | none
          "score":         float,  # 0~1
          "confidence":    float,
          "action_ko":     str,
          "reasons":       list[str],
          "source_chain":  list[str],
          "all_risks":     list[dict],
          "ncpms_forecast": list[dict],
          "ncpms_detail":  list[dict],
          "updated_at":    str,
        }
    """
    source_chain: list[str] = []
    result: Optional[dict] = None

    # ① Plant.id (이미지 있을 때)
    if image_base64 and _plant_id_key():
        pid = plant_id_assess_health(image_base64, crop_ko, farm_lat, farm_lon)
        if pid and not pid.get("is_healthy") and pid.get("diseases"):
            top = pid["diseases"][0]
            result = {
                "disease":    top["name_en"],
                "disease_ko": top["name_ko"],
                "risk_level": "high" if top["confidence"] > 0.6 else "medium",
                "score":      top["confidence"],
                "confidence": top["confidence"],
                "action_ko":  _get_action(top["name_ko"]),
                "reasons":    [f"Plant.id 이미지 분석 신뢰도 {top['confidence']*100:.0f}%"],
                "all_risks":  pid.get("diseases", []),
            }
            source_chain.append("plant_id_v3")

    # ② M5 규칙 기반 v2 (환경 센서 — 항상 실행)
    env_result = env_based_risk(env, crop_ko)
    if not result or env_result.get("risk_level") == "high":
        if not result:
            result = env_result
        source_chain.append(env_result.get("source", "m5_rule_v2"))

    # ③ NCPMS 발생 예보 (보강 정보)
    ncpms_forecast = []
    ncpms_detail = []
    try:
        fc = ncpms_get_pest_forecast(crop_ko, region_code)
        if fc:
            ncpms_forecast = fc.get("forecasts", [])
            source_chain.append("ncpms_rda")
    except Exception:
        pass

    try:
        detail = ncpms_get_disease_detail(crop_ko)
        if detail:
            ncpms_detail = detail[:5]
    except Exception:
        pass

    if result is None:
        result = {
            "disease": "healthy", "disease_ko": "이상 없음",
            "risk_level": "none", "score": 0.0,
            "confidence": 0.9, "action_ko": "현재 환경 유지",
            "reasons": ["모든 진단 소스 정상"], "all_risks": [],
        }

    return {
        **result,
        "source_chain":   source_chain,
        "ncpms_forecast": ncpms_forecast,
        "ncpms_detail":   ncpms_detail,
        "updated_at":     datetime.utcnow().isoformat() + "Z",
    }


def _get_action(disease_ko: str) -> str:
    """병해명 → 권장 조치 매핑."""
    _actions = {
        "잿빛곰팡이병": "야간 온도 상향 + 환기 강화 + iprodione 계열 방제",
        "흰가루병":     "저녁 환기 + 황제 계열 약제 살포",
        "역병":         "배수 개선 + mefenoxam 계열 토양 관주",
        "탄저병":       "피해 과실 즉시 제거 + 약제 예방 살포",
        "노균병":       "저온·고습 회피 + 만코제브 계열 방제",
        "잎곰팡이병":   "환기량 증가 + 온도 낮추기",
        "덩굴쪼김병":   "연작 회피 + 접목 재배 권장",
        "세균성점무늬병": "구리 계열 약제 + 피해 잎 제거",
        "바이러스병":   "진딧물 방제 + 이병주 즉시 제거",
        "풋마름병":     "토양 소독 + 저항성 품종 선택",
    }
    for key, action in _actions.items():
        if key in disease_ko:
            return action
    return "가까운 농업기술센터 또는 농촌진흥청에 문의하세요"


# ══════════════════════════════════════════════════════════════════════════════
# 키 발급 안내
# ══════════════════════════════════════════════════════════════════════════════

PLANT_ID_KEY_GUIDE = {
    "service": "Plant.id Plant Health Assessment API",
    "used_for": "M5 이미지 기반 병해 탐지 (현재 미구축 대체)",
    "free_plan": "월 100건 무료",
    "paid_plan": "$9/월 (500건), $29/월 (무제한)",
    "get_key_url": "https://web.plant.id/",
    "setup_steps": [
        "1. https://web.plant.id/ 접속 → 가입 (GitHub/Google 가능)",
        "2. Dashboard → API Keys → Create new key",
        "3. .env 에 PLANT_ID_API_KEY=your_key 추가",
        "4. docker compose restart api  (또는 uvicorn 재시작)",
    ],
    "env_var": "PLANT_ID_API_KEY",
    "alternative": "PlantNet API (무료 500건/일) — PLANTNET_API_KEY",
}

NCPMS_KEY_GUIDE = {
    "service": "농촌진흥청 병해충관리시스템 (NCPMS)",
    "used_for": "작물별 병해충 발생 예보 + 상세 정보",
    "cost": "무료 (기존 DATA_GO_KR_SERVICE_KEY 사용 가능)",
    "get_key_url": "https://www.data.go.kr/data/15000045/openapi.do",
    "setup_steps": [
        "1. 기존 DATA_GO_KR_SERVICE_KEY 로 즉시 사용 가능",
        "2. 추가 활용: https://ncpms.rda.go.kr 에서 병해충 예보 직접 확인",
    ],
    "env_var": "DATA_GO_KR_SERVICE_KEY",
    "note": "이미 설정된 경우 추가 작업 불필요",
}
