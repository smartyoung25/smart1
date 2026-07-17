"""M3 Revenue — 수확량 × 가격 → 매출 모델.

기본 공식: revenue_per_m2 = yield_per_m2 × price_krw_kg
Ridge 보정: log(revenue) = f(log(yield), log(price), month) — 비선형 관계 포착
불확실성:  price_stats.json의 p25/p75로 80% 예측 구간 제공

Stage 3은 학습보다 '조합'에 가까우므로 pkl보다 계수 JSON으로 저장.
"""
from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DATA_DIR   = Path(__file__).parent.parent / "api" / "data"
_PRICE_FILE = _DATA_DIR / "price_stats.json"


@dataclass
class RevenueResult:
    revenue_per_m2: float   # 중앙 예측값 (원/m²)
    lower_80: float         # 80% 구간 하한
    upper_80: float         # 80% 구간 상한
    price_used: float       # 사용된 단가 (원/kg)
    yield_used: float       # 입력 수확량 (kg/m²)
    confidence: float       # 0~1


class M3RevenueModel:
    """수확량 × 가격 → 매출/m² 계산기."""

    def __init__(self):
        self._price_median: dict[str, float] = {}  # crop_ko → 원/kg
        self._price_p25:    dict[str, float] = {}
        self._price_p75:    dict[str, float] = {}
        self._price_monthly: dict[str, dict] = {}  # crop_ko → {month_str: stats}
        self._ridge: Optional[object]        = None
        self._ridge_feature_names: list[str] = []
        self._loaded = False
        # 작목당 1회만 경고(매 호출 경고는 로그를 덮는다)
        self._warned_crops: set[str] = set()
        # 직전 예측에서 Ridge 보정이 실제로 적용됐는지 — 호출측·테스트가 확인용으로 읽는다
        self._last_ridge_used = False

    def load(self, coef_path: Optional[Path] = None) -> "M3RevenueModel":
        # 가격 통계 로드
        self._load_price_stats()
        # Ridge 보정 계수 로드 (있으면)
        if coef_path and coef_path.exists():
            bundle = pickle.loads(coef_path.read_bytes())
            self._ridge = bundle.get("ridge")
            self._ridge_feature_names = bundle.get("feature_names", [])
            logger.info("[M3] Ridge 보정 로드: %s", coef_path)
        self._loaded = True
        return self

    def _load_price_stats(self) -> None:
        if not _PRICE_FILE.exists():
            logger.warning("[M3] price_stats.json 없음 — 기본값 사용")
            self._price_median = {
                "딸기": 9000.0, "방울토마토": 3800.0, "완숙토마토": 2700.0,
                "참외": 5000.0, "파프리카": 6500.0,
            }
            self._price_p25 = {k: v * 0.7 for k, v in self._price_median.items()}
            self._price_p75 = {k: v * 1.3 for k, v in self._price_median.items()}
            return

        stats = json.loads(_PRICE_FILE.read_text(encoding="utf-8"))
        # price_stats.json은 {"by_crop": {"딸기": {...}}} 구조
        crops_data = stats.get("by_crop", stats) if isinstance(stats, dict) else {}

        for crop_ko, d in crops_data.items():
            if isinstance(d, dict):
                self._price_median[crop_ko] = float(d.get("median_krw_kg", d.get("mean", 5000)))
                self._price_p25[crop_ko]    = float(d.get("p25_krw_kg",    self._price_median[crop_ko] * 0.7))
                self._price_p75[crop_ko]    = float(d.get("p75_krw_kg",    self._price_median[crop_ko] * 1.3))

        # monthly_trend 로드 (있으면)
        self._price_monthly = stats.get("monthly_trend", {})

        logger.info("[M3] 가격 통계 로드: %d작목, 월별분해=%s",
                    len(self._price_median), bool(self._price_monthly))

    def _buildable_features(self, yield_kg_m2: float, crop_ko: str) -> dict:
        """서빙 시점에 **실제로 만들 수 있는** 학습 피처만 반환.

        ★ 여기 없는 피처는 predict(yield, month, crop) 입력만으로 재현이 불가능하다:
          · year_trend          학습 당시 (year-min)/(max-min) 정규화 파라미터가 메타에 없다
          · log_n_harvest_months 농가·연도별 수확 개월수가 필요
          · log_farm_price_hist  농가별 LOO 과거 단가 이력이 필요
          · log_timing_price     농가·연도별 월 출하량 가중치가 필요
          → 이 피처를 쓰는 작목(딸기 5개·참외 3개)은 Ridge 보정을 못 쓴다.
            억지로 채우면 조용히 틀린 값이 나온다. 그 사고를 다시 만들지 않는다.
            해소하려면 predict 시그니처에 farm_id·year 를 받고 메타에 정규화 파라미터를
            저장하도록 stage3 학습·서빙을 함께 손봐야 한다.
        """
        # log_price_annual = 연 단위 시장 중앙 단가(월별 아님) — month 없이 조회하면 그 값이다
        return {
            "log_yield_annual": float(np.log1p(max(0.0, yield_kg_m2))),
            "log_price_annual": float(np.log1p(self.get_price(crop_ko, "median"))),
        }

    def get_price(self, crop_ko: str, percentile: str = "median",
                  month: Optional[int] = None) -> float:
        """작목별 단가 조회. month 지정 시 월별 단가 우선 사용."""
        defaults = {
            "딸기": 9000.0, "방울토마토": 3800.0, "완숙토마토": 2700.0,
            "참외": 5000.0, "파프리카": 6500.0,
        }
        # 월별 단가 (monthly_trend) 우선 사용 — median만 제공
        if month is not None and percentile == "median":
            monthly = self._price_monthly.get(crop_ko, {})
            m_stats = monthly.get(str(month), {})
            if m_stats.get("median_krw_kg", 0) > 0:
                return float(m_stats["median_krw_kg"])

        if percentile == "p25":
            return self._price_p25.get(crop_ko, defaults.get(crop_ko, 5000.0) * 0.7)
        elif percentile == "p75":
            return self._price_p75.get(crop_ko, defaults.get(crop_ko, 5000.0) * 1.3)
        return self._price_median.get(crop_ko, defaults.get(crop_ko, 5000.0))

    def predict(
        self,
        yield_kg_m2: float,
        month: int,
        crop_ko: str,
    ) -> RevenueResult:
        """매출/m² 예측.

        Args:
            yield_kg_m2: 수확량 (kg/m²)
            month:       수확 월 (1~12)
            crop_ko:     작목명

        Returns:
            RevenueResult
        """
        if not self._loaded:
            self.load()

        # 월별 단가 우선(monthly_trend), 없으면 전체 중앙값
        price_med = self.get_price(crop_ko, "median", month=month)
        price_p25 = self.get_price(crop_ko, "p25")
        price_p75 = self.get_price(crop_ko, "p75")

        # 기본 곱셈
        base_rev = yield_kg_m2 * price_med

        # Ridge 보정 (있으면) — ★ 반드시 학습 당시 피처를 '이름으로' 재구성한다.
        #   구: 위치 기반 4개를 만들고 X_feat[:, :n] 로 잘라 넣었다("안전하게 맞춤" 주석).
        #       그 슬라이싱이 오히려 불일치를 숨겨, 개수만 맞으면 **틀린 피처를 조용히**
        #       먹였다. 실측(2026-07-17):
        #         · 딸기(5개)  → 개수 불일치 예외 → 기본곱셈 폴백 (유일하게 안전했음)
        #         · 오이·파프리카·완숙·방울(2개) → log_price_annual(연도별 시장가) 자리에
        #           월별 중앙가를 먹임 → 예외 없이 틀린 매출
        #         · 참외(3개) → year_trend(0~1 정규화) 자리에 float(month)(1~12) → 스케일 붕괴
        #   지금: 만들 수 있는 피처만 이름으로 조립하고, 하나라도 없으면 Ridge 를 쓰지 않는다.
        #        (근거 없는 보정보다 정직한 기본 곱셈이 낫다.)
        revenue = base_rev
        self._last_ridge_used = False
        if self._ridge is not None and self._ridge_feature_names:
            feats = self._buildable_features(yield_kg_m2, crop_ko)
            missing = [n for n in self._ridge_feature_names if n not in feats]
            if missing:
                # 매 호출 경고는 로그를 덮으므로 작목당 1회만 남긴다.
                if crop_ko not in self._warned_crops:
                    self._warned_crops.add(crop_ko)
                    logger.warning(
                        "[M3] %s Ridge 보정 미적용 — 서빙 시점에 만들 수 없는 피처: %s "
                        "(학습 피처=%s). 기본 곱셈(수확량×월별단가) 사용.",
                        crop_ko, missing, self._ridge_feature_names)
            else:
                try:
                    X_feat = np.array([[feats[n] for n in self._ridge_feature_names]])
                    rev_corrected = float(np.expm1(self._ridge.predict(X_feat)[0]))
                    if rev_corrected > 0:
                        revenue = rev_corrected
                        self._last_ridge_used = True
                except Exception as e:
                    logger.warning("[M3] %s Ridge 예측 실패(%s) — 기본 곱셈 사용", crop_ko, e)

        lower_80 = yield_kg_m2 * price_p25
        upper_80 = yield_kg_m2 * price_p75

        # confidence: 가격 IQR이 좁을수록 높음
        price_cv = (price_p75 - price_p25) / (price_med + 1e-9)
        confidence = max(0.3, 1.0 - min(1.0, price_cv))

        return RevenueResult(
            revenue_per_m2=round(revenue, 1),
            lower_80=round(lower_80, 1),
            upper_80=round(upper_80, 1),
            price_used=round(price_med, 1),
            yield_used=round(yield_kg_m2, 4),
            confidence=round(confidence, 3),
        )


# 싱글턴
_models: dict[str, M3RevenueModel] = {}


def get_revenue_model(crop_en: str = "") -> M3RevenueModel:
    key = crop_en or "default"
    if key not in _models:
        from models.crop_config import OUT_DIR
        coef_path = OUT_DIR / crop_en / "stage3_revenue_coef.pkl" if crop_en else None
        _models[key] = M3RevenueModel().load(coef_path)
    return _models[key]
