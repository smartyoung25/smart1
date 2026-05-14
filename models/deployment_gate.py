"""배포 게이트 — 각 모듈의 성능 기준 통과 여부를 검사.

게이트 기준:
  M1: R²   ≥ 0.62
  M2: MAPE ≤ 25%
  M3: 일 오차 ≤ 5일 (별도 평가 필요)
  M4: 오차  ≤ 20%
  M5: F1   ≥ 0.88

통과 → MLflow 모델 등록 + 서빙 교체
미통과 → 관리자 알림 + 재학습 대기
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ── 기준값 ──────────────────────────────────────────────────────────────────

GATES: dict[str, dict] = {
    # 기존 단일 모델 게이트 (하위호환 유지)
    "M1": {"metric": "r2",        "threshold": 0.62, "op": "gte",  "display": "R² ≥ 0.62"},
    "M2": {"metric": "mape",      "threshold": 25.0, "op": "lte",  "display": "MAPE ≤ 25%"},
    "M3": {"metric": "day_error", "threshold": 5.0,  "op": "lte",  "display": "±5일"},
    "M4": {"metric": "error_pct", "threshold": 20.0, "op": "lte",  "display": "오차 ≤ 20%"},
    "M5": {"metric": "f1",        "threshold": 0.88, "op": "gte",  "display": "F1 ≥ 0.88"},
    # 4-Stage 파이프라인 게이트
    "STAGE1_CV_R2":      {"metric": "cv_r2_mean",  "threshold": 0.55, "op": "gte",
                          "display": "생육예측 CV R² ≥ 0.55"},
    "STAGE1_NO_NEG":     {"metric": "cv_r2_min",   "threshold": -0.2, "op": "gte",
                          "display": "생육예측 최악 fold R² ≥ -0.2"},
    "STAGE2_MAPE":       {"metric": "mape",         "threshold": 25.0, "op": "lte",
                          "display": "수확량 MAPE ≤ 25%"},
    "STAGE2_R2":         {"metric": "r2",           "threshold": 0.30, "op": "gte",
                          "display": "수확량 CV R² ≥ 0.30"},
    "STAGE3_MAPE":       {"metric": "mape",         "threshold": 20.0, "op": "lte",
                          "display": "매출 MAPE ≤ 20%"},
    "STAGE4_COST_VALID": {"metric": "cost_ratio",   "threshold": 0.5,  "op": "lte",
                          "display": "비용/매출 ≤ 50%"},
}


@dataclass
class GateResult:
    module_id: str
    metric_name: str
    metric_value: float
    threshold: float
    passed: bool
    display: str
    evaluated_at: datetime


@dataclass
class GateSummary:
    results: list[GateResult]
    all_passed: bool
    evaluated_at: datetime

    def failed_modules(self) -> list[str]:
        return [r.module_id for r in self.results if not r.passed]

    def to_dict(self) -> dict:
        return {
            "all_passed": self.all_passed,
            "evaluated_at": self.evaluated_at.isoformat(),
            "results": [
                {
                    "module_id": r.module_id,
                    "metric":    r.metric_name,
                    "value":     r.metric_value,
                    "threshold": r.threshold,
                    "passed":    r.passed,
                    "display":   r.display,
                }
                for r in self.results
            ],
        }


def _check(module_id: str, metric_value: float) -> GateResult:
    gate = GATES[module_id]
    op   = gate["op"]
    thr  = gate["threshold"]
    passed = (metric_value >= thr) if op == "gte" else (metric_value <= thr)
    return GateResult(
        module_id=module_id,
        metric_name=gate["metric"],
        metric_value=round(metric_value, 4),
        threshold=thr,
        passed=passed,
        display=gate["display"],
        evaluated_at=datetime.now(tz=timezone.utc),
    )


def evaluate(metrics: dict[str, float]) -> GateSummary:
    """Evaluate deployment gates for all provided metrics.

    Args:
        metrics: dict of {module_id: metric_value}
                 e.g. {"M1": 0.71, "M2": 18.4, "M5": 0.85}
    """
    results = []
    for module_id, value in metrics.items():
        if module_id not in GATES:
            logger.warning("[deployment_gate] unknown module '%s' — skipped", module_id)
            continue
        result = _check(module_id, value)
        status = "✅ PASS" if result.passed else "❌ FAIL"
        logger.info(
            "[deployment_gate] %s %s=%s (threshold %s) → %s",
            module_id, result.metric_name, result.metric_value, result.threshold, status,
        )
        results.append(result)

    all_passed = all(r.passed for r in results) if results else False
    summary = GateSummary(
        results=results,
        all_passed=all_passed,
        evaluated_at=datetime.now(tz=timezone.utc),
    )

    if not all_passed:
        failed = summary.failed_modules()
        logger.warning("[deployment_gate] GATE FAILED for modules: %s", failed)
    else:
        logger.info("[deployment_gate] ALL GATES PASSED — ready for deployment")

    return summary


def register_with_mlflow(
    summary: GateSummary,
    run_id: str,
    model_name_prefix: str = "SmartFarm",
    mlflow_uri: Optional[str] = None,
) -> bool:
    """Register passing models in MLflow Model Registry.

    Returns True if registration succeeded.
    """
    if not summary.all_passed:
        logger.warning("[deployment_gate] Skipping MLflow registration — gate not passed")
        return False

    try:
        import mlflow
        if mlflow_uri:
            mlflow.set_tracking_uri(mlflow_uri)

        for result in summary.results:
            if result.passed:
                model_uri  = f"runs:/{run_id}/{result.module_id.lower()}_model"
                model_name = f"{model_name_prefix}_{result.module_id}"
                mlflow.register_model(model_uri, model_name)
                logger.info("[deployment_gate] Registered %s → %s", result.module_id, model_name)

        return True
    except Exception as exc:
        logger.error("[deployment_gate] MLflow registration failed: %s", exc)
        return False
