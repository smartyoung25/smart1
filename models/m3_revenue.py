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
        self._ridge: Optional[object]        = None
        self._ridge_feature_names: list[str] = []
        self._loaded = False

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

        logger.info("[M3] 가격 통계 로드: %d작목", len(self._price_median))

    def get_price(self, crop_ko: str, percentile: str = "median") -> float:
        """작목별 단가 조회."""
        defaults = {
            "딸기": 9000.0, "방울토마토": 3800.0, "완숙토마토": 2700.0,
            "참외": 5000.0, "파프리카": 6500.0,
        }
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

        price_med = self.get_price(crop_ko, "median")
        price_p25 = self.get_price(crop_ko, "p25")
        price_p75 = self.get_price(crop_ko, "p75")

        # 기본 곱셈
        base_rev = yield_kg_m2 * price_med

        # Ridge 보정 (있으면)
        if self._ridge is not None:
            try:
                X_feat = np.array([[
                    np.log1p(max(0, yield_kg_m2)),
                    np.log1p(price_med),
                    float(month),
                ]])
                rev_corrected = float(np.expm1(self._ridge.predict(X_feat)[0]))
                revenue = max(0.0, rev_corrected)
            except Exception as e:
                logger.warning("[M3] Ridge 예측 실패(%s) — 기본 곱셈 사용", e)
                revenue = base_rev
        else:
            revenue = base_rev

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
