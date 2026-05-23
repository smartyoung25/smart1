"""
Section B+C: 학습 파이프라인 감사 + 5개 작물 성능 지표 정리
- stage2_meta.json 전수 분석
- m1_meta.json 전수 분석
- 모델 포맷 감지 (A/B/C)
- 이상 지표 플래그
실행: python analysis/model_audit.py
"""
import sys, os, json, pickle
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT      = Path(__file__).parent.parent
ARTS_DIR  = ROOT / "models" / "artifacts"

CROPS = [
    ("딸기",       "strawberry"),
    ("방울토마토", "cherry_tomato"),
    ("완숙토마토", "tomato"),
    ("참외",       "melon"),
    ("파프리카",   "paprika"),
]

RDA_BOUNDS = {
    "strawberry":    (2.0,  12.0),
    "cherry_tomato": (5.0,  25.0),
    "tomato":        (8.0,  30.0),
    "melon":         (3.0,  12.0),
    "paprika":       (8.0,  20.0),
}

GATE_STRICT = {"mape_threshold": 30.0, "r2_threshold": 0.10}

log_b = [
    "# Section B: 학습 파이프라인 감사",
    f"- 분석 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    "",
]
log_c = [
    "# Section C: 5개 작물 성능 지표 정리",
    f"- 분석 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    "",
]


def detect_format(crop_en: str) -> dict:
    """pkl 파일 존재 여부로 모델 포맷 감지."""
    art = ARTS_DIR / crop_en
    formats = {
        "format_A": (art / "m2_yield_model.pkl").exists(),
        "format_C": (art / "stage2_yield.pkl").exists(),
        "format_4stage": (art / "stage3_revenue_coef.pkl").exists(),
        "stage1": (art / "stage1_growth.pkl").exists() or (art / "m1_growth_model.pkl").exists(),
    }
    return formats


def load_pkl_meta(crop_en: str, filename: str) -> dict:
    """pkl에서 직접 메타 추출 (키 목록 + 타겟 정보)."""
    path = ARTS_DIR / crop_en / filename
    if not path.exists():
        return {"error": "파일 없음"}
    try:
        pkg = pickle.loads(path.read_bytes())
        return {
            "keys": list(pkg.keys()) if isinstance(pkg, dict) else str(type(pkg)),
            "target": pkg.get("target", pkg.get("agg_mode", "unknown")),
            "log_transform": pkg.get("log_transform", None),
            "feature_count": len(pkg.get("feature_cols", pkg.get("feat_cols", pkg.get("features", [])))),
            "has_xgb": ("xgb" in pkg or "model" in pkg),
            "has_lgb": ("lgb" in pkg or "model_lgb" in pkg),
            "has_ridge": any("ridge" in k for k in (pkg.keys() if isinstance(pkg, dict) else [])),
            "farm_yield_mean_sample": list(pkg.get("farm_yield_mean", {}).values())[:3]
                if isinstance(pkg.get("farm_yield_mean"), dict) else None,
            "farm_encoding_global_mean": pkg.get("farm_encoding", {}).get("global_mean"),
        }
    except Exception as e:
        return {"error": str(e)}


def flag_anomalies(meta: dict, crop_en: str) -> list:
    """성능 지표 기반 이상 플래그 생성."""
    flags = []
    lo, hi = RDA_BOUNDS.get(crop_en, (0, 999))
    rmse = meta.get("train_rmse", 0)
    cv_r2 = meta.get("cv_r2_mean", 0)
    cv_mape = meta.get("cv_mape_mean") or 0
    mape = meta.get("mape", 0)
    n_train = meta.get("n_train", 0)
    gate = meta.get("gate_passed", False)

    if cv_r2 < 0:
        flags.append(f"CV R²={cv_r2:.3f} < 0 → 단순 평균보다 나쁜 모델")
    if cv_mape > 50:
        flags.append(f"CV MAPE={cv_mape:.1f}% > 50% → 예측 신뢰성 없음")
    if mape > GATE_STRICT["mape_threshold"] and gate:
        flags.append(f"MAPE={mape:.1f}% > {GATE_STRICT['mape_threshold']}% 인데 gate_pass=True → 게이트 기준 과도하게 관대")
    if rmse > (hi - lo) * 0.5:
        flags.append(f"train_rmse={rmse:.2f} > 기대범위 [{lo}~{hi}] 의 50% → 학습 타겟 단위 오류 의심")
    if n_train < 100:
        flags.append(f"n_train={n_train} < 100 → 표본 부족, Ridge fallback 가능")
    if meta.get("model_type") == "ridge_fallback":
        flags.append("모델 유형=ridge_fallback → XGB/LGB 학습 불가 수준의 표본 수")
    return flags


def main():
    # ── Section B: 학습 파이프라인 감사 ────────────────────────────────────────
    log_b.append("## 1. 모델 포맷 공존 현황")
    log_b.append("")
    log_b.append("| 작물 | Format A (m2_yield_model.pkl) | Format C (stage2_yield.pkl) | 4-stage | Stage1 |")
    log_b.append("|------|-------------------------------|-----------------------------|---------|----|")

    for crop_ko, crop_en in CROPS:
        fmt = detect_format(crop_en)
        row = f"| {crop_ko} | {'✓' if fmt['format_A'] else '✗'} | {'✓' if fmt['format_C'] else '✗'} | {'✓' if fmt['format_4stage'] else '✗'} | {'✓' if fmt['stage1'] else '✗'} |"
        log_b.append(row)

    log_b.append("")
    log_b.append("### Format A 역변환 감사 (m2_yield_model.pkl)")
    log_b.append("")
    for crop_ko, crop_en in CROPS:
        meta = load_pkl_meta(crop_en, "m2_yield_model.pkl")
        if "error" in meta:
            log_b.append(f"- **{crop_ko}**: {meta['error']}")
            continue
        fym_sample = meta.get("farm_yield_mean_sample")
        log_b.append(f"**{crop_ko}**:")
        log_b.append(f"  - target={meta['target']}, log_transform={meta['log_transform']}")
        log_b.append(f"  - feature_count={meta['feature_count']}")
        if fym_sample:
            median_fym = sorted(fym_sample)[len(fym_sample)//2]
            if median_fym < 100:
                unit_guess = "kg/m² 단위 의심 (너무 작음)"
            elif median_fym < 10000:
                unit_guess = "연간 총 kg 단위 정상"
            else:
                unit_guess = "총 kg이나 값이 매우 큼"
            log_b.append(f"  - farm_yield_mean 샘플={fym_sample} → **{unit_guess}**")

    log_b.append("")
    log_b.append("### Format C 역변환 감사 (stage2_yield.pkl)")
    log_b.append("")
    for crop_ko, crop_en in CROPS:
        meta = load_pkl_meta(crop_en, "stage2_yield.pkl")
        if "error" in meta:
            log_b.append(f"- **{crop_ko}**: {meta['error']}")
            continue
        fe_mean = meta.get("farm_encoding_global_mean")
        log_b.append(f"**{crop_ko}**:")
        log_b.append(f"  - target={meta['target']}, log_transform={meta['log_transform']}")
        log_b.append(f"  - feature_count={meta['feature_count']}")
        if fe_mean is not None:
            lo, hi = RDA_BOUNDS.get(crop_en, (0, 999))
            if lo <= fe_mean <= hi * 3:
                unit_flag = f"kg/m² 단위 정상 범위"
            elif fe_mean > hi * 3:
                unit_flag = f"⚠ 값이 RDA 기준({hi}) 대비 너무 큼 → 단위 오류 가능"
            else:
                unit_flag = f"⚠ 값이 너무 작음 → 단위 확인 필요"
            log_b.append(f"  - farm_encoding.global_mean={fe_mean:.3f} → **{unit_flag}**")

    # annual vs monthly 혼용
    log_b.append("")
    log_b.append("## 2. Annual vs Monthly 단위 혼용 추적")
    log_b.append("")
    log_b.append("| 코드 경로 | 파일 | 반환 단위 | season_months 나눔 |")
    log_b.append("|---------|------|---------|-----------------|")
    log_b.append("| m2_yield.predict_yield() | models/m2_yield.py L228 | 연간 kg/m² | ✗ — 연간값 그대로 반환 |")
    log_b.append("| model_loader._predict_4stage() | api/services/model_loader.py L240 | 연간÷작기개월수 | ✓ — 월간으로 변환 |")
    log_b.append("| model_loader.predict_season_revenue() | L366 | 총 매출(원) | 월×개월×면적 |")
    log_b.append("")
    log_b.append("> **결론**: m2_yield.py가 연간값을 반환하는데, 이를 월별 실측과 직접 비교하면 6~10배 차이 발생")

    # ── Section C: 성능 지표 ───────────────────────────────────────────────────
    log_c.append("## M2 수확량 예측 성능 현황 (stage2_meta.json 기반)")
    log_c.append("")
    log_c.append("| 작물 | 모델 유형 | n_train | CV R² | CV MAPE | Train RMSE | Train MAE | gate_pass | agg_mode |")
    log_c.append("|------|-----------|---------|-------|---------|------------|-----------|-----------|----------|")

    all_flags = {}
    for crop_ko, crop_en in CROPS:
        meta_path = ARTS_DIR / crop_en / "stage2_meta.json"
        if not meta_path.exists():
            log_c.append(f"| {crop_ko} | — | — | — | — | — | — | — | — |")
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        cv_r2   = meta.get("cv_r2_mean", "—")
        cv_mape = meta.get("cv_mape_mean") or "—"
        rmse    = meta.get("train_rmse", "—")
        mae     = meta.get("train_mae", "—")
        gate    = "✓" if meta.get("gate_passed") else "✗"
        r2_str  = f"{cv_r2:.3f}" if isinstance(cv_r2, float) else str(cv_r2)
        mp_str  = f"{cv_mape:.1f}%" if isinstance(cv_mape, float) else str(cv_mape)
        rm_str  = f"{rmse:.2f}" if isinstance(rmse, float) else str(rmse)
        ma_str  = f"{mae:.2f}"  if isinstance(mae, float)  else str(mae)
        log_c.append(f"| {crop_ko} | {meta.get('model_type','—')} | {meta.get('n_train','—')} | {r2_str} | {mp_str} | {rm_str} | {ma_str} | {gate} | {meta.get('agg_mode','—')} |")
        flags = flag_anomalies(meta, crop_en)
        all_flags[crop_ko] = flags

    log_c.append("")
    log_c.append("## 이상 지표 플래그")
    log_c.append("")
    for crop_ko, flags in all_flags.items():
        if flags:
            log_c.append(f"### {crop_ko}")
            for f in flags:
                log_c.append(f"- ⚠ {f}")
            log_c.append("")

    # M1 성능
    log_c.append("## M1 생육 예측 성능 현황 (stage1_meta.json 기반)")
    log_c.append("")
    log_c.append("| 작물 | n_train | CV R² | CV MAPE | gate_pass |")
    log_c.append("|------|---------|-------|---------|-----------|")
    for crop_ko, crop_en in CROPS:
        meta_path = ARTS_DIR / crop_en / "stage1_meta.json"
        if not meta_path.exists():
            meta_path = ARTS_DIR / crop_en / "m1_meta.json"
        if not meta_path.exists():
            log_c.append(f"| {crop_ko} | — | — | — | — |")
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        log_c.append(
            f"| {crop_ko} | {meta.get('n_train','—')} | "
            f"{meta.get('cv_r2_mean', meta.get('r2','—'))} | "
            f"{meta.get('cv_mape_mean', meta.get('mape','—'))} | "
            f"{'✓' if meta.get('gate_passed', meta.get('gate_pass', False)) else '✗'} |"
        )

    log_c.append("")
    log_c.append("## 엄격한 게이트 기준 재평가 (MAPE ≤ 30% AND R² ≥ 0.10)")
    log_c.append("")
    log_c.append("| 작물 | 현재 gate | 엄격 기준 gate | 차이 |")
    log_c.append("|------|---------|--------------|-----|")
    for crop_ko, crop_en in CROPS:
        meta_path = ARTS_DIR / crop_en / "stage2_meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        current = "✓" if meta.get("gate_passed") else "✗"
        strict_ok = (
            (meta.get("mape", 99) <= 30.0) and
            (meta.get("cv_r2_mean", -999) >= 0.10)
        )
        strict = "✓" if strict_ok else "✗"
        diff = "기준 강화 시 탈락" if (meta.get("gate_passed") and not strict_ok) else ("동일" if meta.get("gate_passed") == strict_ok else "—")
        log_c.append(f"| {crop_ko} | {current} | {strict} | {diff} |")

    # 파일 저장
    (Path(__file__).parent / "02_training_pipeline.md").write_text("\n".join(log_b), encoding="utf-8")
    (Path(__file__).parent / "03_model_performance.md").write_text("\n".join(log_c), encoding="utf-8")
    print("[완료] 02_training_pipeline.md")
    print("[완료] 03_model_performance.md")


if __name__ == "__main__":
    main()
