"""
Section D: 예측 파이프라인 추적 + 단위 검증
- 동일 입력에 대해 Format A/C/4stage 결과 비교
- 연간 vs 월별 단위 불일치 탐지
- 작물별 예측값 vs RDA 기준 비율 계산
실행: python analysis/pipeline_trace.py
"""
import sys, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT    = Path(__file__).parent.parent
log_d   = [
    "# Section D: 예측 파이프라인 추적",
    f"- 분석 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    "",
]

# RDA 정상 연간 yield (kg/m²/시즌) 기대값 중앙
RDA_MEDIAN = {
    "딸기":       5.0,
    "방울토마토": 12.0,
    "완숙토마토": 18.0,
    "참외":       7.0,
    "파프리카":   14.0,
}

# 작기 개월수
SEASON_MONTHS = {
    "딸기": 6, "방울토마토": 8, "완숙토마토": 8,
    "참외": 4, "파프리카": 10,
}

# 테스트 환경값 (일반적 온실 조건)
TEST_ENV = {
    "temp_internal_mean": 18.0,
    "temp_internal_max":  24.0,
    "temp_internal_min":  12.0,
    "humidity_int_mean":  72.0,
    "co2_ppm_mean":       800.0,
    "solar_rad_mean":     150.0,
    "solar_rad_sum":      4500.0,
    "temp_external_mean": 10.0,
    "soil_temp_mean":     17.0,
    "gdd_monthly":        370.0,
    "gdd_cumsum":         1200.0,
}

TEST_AREA_M2 = 1200.0
TEST_FARM_ID = "farm_003"


def try_format_a(crop_ko: str) -> dict:
    """m2_yield.py Format A/C predict_yield 호출."""
    try:
        from models.m2_yield import predict_yield
        result = predict_yield(crop_ko, TEST_ENV, area_m2=TEST_AREA_M2, farm_id=TEST_FARM_ID)
        return result
    except Exception as e:
        return {"error": str(e), "yield_kg_m2": None}


def try_4stage(crop_ko: str) -> dict:
    """model_loader.py 4-stage 경로 호출."""
    try:
        from api.services.model_loader import load_4stage_model, _predict_4stage
        bundle = load_4stage_model(crop_ko)
        if bundle is None:
            return {"error": "4-stage 모델 없음", "revenue_monthly_m2": None}
        rev_monthly = _predict_4stage(bundle, TEST_ENV, crop_ko)
        return {"revenue_monthly_m2": round(rev_monthly, 2), "source": "4stage"}
    except Exception as e:
        return {"error": str(e), "revenue_monthly_m2": None}


def main():
    log_d.append("## 1. Format A/C vs 4-stage 결과 비교")
    log_d.append("")
    log_d.append(f"테스트 환경: temp={TEST_ENV['temp_internal_mean']}°C, humidity={TEST_ENV['humidity_int_mean']}%, CO₂={TEST_ENV['co2_ppm_mean']}ppm")
    log_d.append(f"테스트 면적: {TEST_AREA_M2} m², farm_id={TEST_FARM_ID}")
    log_d.append("")
    log_d.append("| 작물 | Format-A/C yield_kg_m² | RDA기대값 | 비율(예측/기대) | source | 4stage revenue(원/m²/월) |")
    log_d.append("|------|----------------------|---------|--------------|-------|------------------------|")

    comparison_results = []

    for crop_ko, expected_annual in RDA_MEDIAN.items():
        r_a = try_format_a(crop_ko)
        r_4 = try_4stage(crop_ko)

        ym = r_a.get("yield_kg_m2")
        src = r_a.get("source", "?")
        rev = r_4.get("revenue_monthly_m2", "—")
        err_a = r_a.get("error", "")
        err_4 = r_4.get("error", "")

        if ym is not None:
            ratio = ym / expected_annual
            ratio_str = f"{ratio:.1f}×"
            if ratio > 5 or ratio < 0.1:
                flag = f"⚠ 10배 이상 이상"
            elif ratio > 2 or ratio < 0.5:
                flag = f"⚠ 2배 이상 이상"
            else:
                flag = "정상"
        else:
            ratio_str = "—"
            flag = f"오류: {err_a}"

        rev_str = f"{rev:.0f}" if isinstance(rev, float) else str(rev)
        log_d.append(f"| {crop_ko} | {ym if ym else '오류'} | {expected_annual} | {ratio_str} {flag} | {src} | {rev_str} |")

        comparison_results.append({
            "crop": crop_ko,
            "predicted_yield_m2": ym,
            "expected_annual_m2": expected_annual,
            "ratio": (ym / expected_annual) if ym else None,
            "source": src,
            "revenue_monthly": rev,
            "error_a": err_a,
            "error_4": err_4,
        })

    # ── annual vs monthly 혼용 시뮬레이션 ─────────────────────────────────────
    log_d.append("")
    log_d.append("## 2. Annual vs Monthly 혼용 시 예상 오차")
    log_d.append("")
    log_d.append("| 작물 | 연간 예측(kg/m²) | 월별 환산(÷개월) | 실측 월별 기대값 | 비율 |")
    log_d.append("|------|--------------|-------------|-------------|-----|")

    for r in comparison_results:
        crop = r["crop"]
        ann = r.get("predicted_yield_m2")
        if ann is None:
            log_d.append(f"| {crop} | — | — | — | — |")
            continue
        sm = SEASON_MONTHS.get(crop, 8)
        monthly_pred = ann / sm
        monthly_actual = RDA_MEDIAN.get(crop, 10) / sm
        ratio = monthly_pred / monthly_actual if monthly_actual > 0 else 0
        log_d.append(f"| {crop} | {ann:.2f} | {monthly_pred:.3f} (÷{sm}) | {monthly_actual:.3f} | {ratio:.1f}× |")

    log_d.append("")
    log_d.append("> 예측이 연간, 실측 비교가 월별이면 위 비율만큼 차이 발생")

    # ── 역변환 경로 코드 추적 ─────────────────────────────────────────────────
    log_d.append("")
    log_d.append("## 3. 역변환 경로 코드 추적 요약")
    log_d.append("")
    log_d.append("### Format A (m2_yield_model.pkl, target=log_yield_ratio)")
    log_d.append("```python")
    log_d.append("# models/m2_yield.py L84-88")
    log_d.append("if tgt == 'log_yield_ratio':")
    log_d.append("    farm_mean = row.get('farm_yield_mean', 5000.0)  # ← 단위 불명확!")
    log_d.append("    yield_total = float(np.expm1(log_pred) * farm_mean)")
    log_d.append("    # farm_mean이 kg이면 yield_total = 연간 총 kg ✓")
    log_d.append("    # farm_mean이 kg/m²이면 yield_total = 매우 작은 값 ✗")
    log_d.append("```")

    log_d.append("")
    log_d.append("### Format C (stage2_yield.pkl, target=log1p(yield_per_m2_annual))")
    log_d.append("```python")
    log_d.append("# models/m2_yield.py L149-151")
    log_d.append("elif log_transform:")
    log_d.append("    yield_total = float(np.expm1(max(log_pred, 0))) * max(area_m2, 1)")
    log_d.append("    # → yield_total = 연간 총 kg")
    log_d.append("    # → yield_m2 = yield_total / area_m2 = 연간 kg/m² ← 이것이 사용자가 보는 값")
    log_d.append("```")

    log_d.append("")
    log_d.append("### 4-stage (stage2_yield.pkl + stage3_revenue_coef.pkl)")
    log_d.append("```python")
    log_d.append("# api/services/model_loader.py L180-240")
    log_d.append("yield_per_m2 = float(np.expm1(raw))           # 연간 kg/m²")
    log_d.append("revenue_annual = float(np.expm1(ridge.predict(...)[0]))  # 연간 원/m²")
    log_d.append("revenue_monthly = revenue_annual / season_months  # ← 월별 원/m² 반환")
    log_d.append("```")

    log_d.append("")
    log_d.append("## 4. 액션 아이템")
    log_d.append("")
    log_d.append("- [ ] Format A `farm_yield_mean` 단위 확인 — 연간 총 kg인지 kg/m²인지")
    log_d.append("- [ ] 예측값 반환 시 단위 명시 (`unit: 'kg/m2/annual'`) 추가")
    log_d.append("- [ ] 프론트엔드/API 비교 시 동일 단위(연간 or 월별) 통일 확인")
    log_d.append("- [ ] m2_yield.py Format A/B/C 단일 경로로 통합")

    (Path(__file__).parent / "04_prediction_pipeline.md").write_text("\n".join(log_d), encoding="utf-8")
    print("[완료] 04_prediction_pipeline.md")


if __name__ == "__main__":
    main()
