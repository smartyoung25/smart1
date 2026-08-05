"""CAPEX 감가상각·유지보수 → 비용모델 연동 (stage4 보조).

CAPEX/OPEX 체계화(scripts/_build_capex_opex_taxonomy.py)를 비용 계산에 연결한다.
자산등록부(api/data/capex/register.json)에 실 취득가가 입력돼 있으면 정액 감가상각을
합산하고, 없으면 농진청 소득조사표 표준 템플릿(영농시설 783,000 + 대농구 675,000 = 1,458,000/년,
900㎡)을 작목별 시설 완비도로 차등해 사용한다.

★ 정직성: 조사표 '소득분석2' 집계 상각비는 4작목 동일한 샘플 템플릿이라 실 취득가가 아니다.
  register.json 에 견적 취득가를 채우기 전까지는 '표준(template)' 값임을 source 로 반환한다.

정액 감가상각 = 취득가액 × (1 − 잔존율) ÷ 내용연수
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "api" / "data" / "capex"
_REGISTER = _DATA / "register.json"

# 조사표 표준 템플릿 (900㎡, 연) — register 미입력 시 기본값
_TEMPLATE_ANNUAL = 1_458_000.0          # 영농시설 783,000 + 대농구 675,000
_TEMPLATE_AREA_M2 = 900.0
_RESIDUAL_DEFAULT = 0.10                 # 잔존율 표준 10%

# 수리유지비(OPEX) ≈ 연 감가상각의 15% 근사 (자산 노후·가동시간 반영, 조사표 수리유지 항목 대응)
_MAINTENANCE_RATE = 0.15

# 작목별 시설 완비도 계수 (작목별 시설 구성 시트 근거: 참외 보온·차광·관수 미설치/고장 → 최소)
_CROP_FACILITY_FACTOR = {
    "딸기": 1.00, "방울토마토": 0.92, "완숙토마토": 0.82, "참외": 0.70,
}


@dataclass
class CapexCost:
    annual_depreciation_krw: float       # 연 감가상각 총액 (원)
    depreciation_per_m2_month: float     # 월 감가상각 (원/m²)
    maintenance_per_m2_month: float      # 월 수리유지비 (원/m²)
    source: str                          # "register"(견적입력) | "template"(조사표 표준)
    n_assets: int                        # 등록 자산 수 (template 이면 0)


def _load_register() -> list[dict]:
    if _REGISTER.exists():
        try:
            data = json.loads(_REGISTER.read_text(encoding="utf-8"))
            return data.get("assets", []) if isinstance(data, dict) else (data or [])
        except Exception:
            return []
    return []


def compute(crop_ko: str, area_m2: float = _TEMPLATE_AREA_M2) -> CapexCost:
    """작목·면적 기준 감가상각·유지보수 비용 산출.

    register.json 에 취득가(acquisition_krw)>0 자산이 있으면 그 합으로,
    없으면 조사표 표준 템플릿을 작목 시설완비도로 차등해 사용.
    """
    area = max(float(area_m2 or _TEMPLATE_AREA_M2), 1.0)
    assets = _load_register()
    real = [a for a in assets if float(a.get("acquisition_krw", 0) or 0) > 0
            and int(a.get("life_years", 0) or 0) >= 2]

    if real:
        annual = 0.0
        for a in real:
            cost = float(a["acquisition_krw"])
            life = int(a["life_years"])
            resid = float(a.get("residual_rate", _RESIDUAL_DEFAULT))
            annual += cost * (1.0 - resid) / life
        source, n = "register", len(real)
    else:
        factor = _CROP_FACILITY_FACTOR.get(crop_ko, 0.85)
        # 템플릿은 900㎡ 기준 → 대상 면적으로 스케일
        annual = _TEMPLATE_ANNUAL * factor * (area / _TEMPLATE_AREA_M2)
        source, n = "template", 0

    dep_pm2_month = annual / area / 12.0
    maint_pm2_month = dep_pm2_month * _MAINTENANCE_RATE
    return CapexCost(
        annual_depreciation_krw=round(annual, 0),
        depreciation_per_m2_month=round(dep_pm2_month, 2),
        maintenance_per_m2_month=round(maint_pm2_month, 2),
        source=source,
        n_assets=n,
    )
