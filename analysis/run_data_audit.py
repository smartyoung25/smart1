"""
Section A: 원시 데이터 단위 감사
- 식부면적 실제 값 범위 → 10a 단위 오류 여부 확인
- 총출하량 실제 값 범위 → 박스 단위 여부 확인
- yield_per_m2 학습 타겟 분포 vs RDA 기준 비교
실행: python analysis/run_data_audit.py
"""
import sys, os, json, glob
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_BASE = ROOT / "기초자료"

# RDA 작목별 정상 연간 수확량 범위 (kg/m²/시즌)
RDA_BOUNDS = {
    "딸기":       (2.0,  12.0),
    "방울토마토": (5.0,  25.0),
    "완숙토마토": (8.0,  30.0),
    "참외":       (3.0,  12.0),
    "파프리카":   (8.0,  20.0),
}

CROP_ALIASES = {
    "딸기": ["딸기", "strawberry"],
    "방울토마토": ["방울토마토", "cherry tomato", "방울"],
    "완숙토마토": ["완숙토마토", "토마토", "tomato"],
    "참외": ["참외", "melon"],
    "파프리카": ["파프리카", "paprika"],
}

YEARS = [2020, 2021, 2022, 2023, 2024]

log_lines = [
    "# Section A: 원시 데이터 단위 감사",
    f"- 분석 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    f"- 기초자료 경로: {DATA_BASE}",
    "",
]


def find_csv_files(keyword: str) -> list:
    """기초자료 디렉터리에서 keyword 포함 CSV 파일 검색."""
    patterns = [
        str(DATA_BASE / "**" / f"*{keyword}*.csv"),
        str(DATA_BASE / "**" / f"*{keyword}*" / "*.csv"),
    ]
    files = []
    for p in patterns:
        files.extend(glob.glob(p, recursive=True))
    return list(set(files))


def audit_area_column(df: pd.DataFrame, crop_name: str) -> dict:
    """식부면적 컬럼 단위 판별."""
    area_cols = [c for c in df.columns if "면적" in c or "area" in c.lower()]
    result = {"cols_found": area_cols, "stats": {}}
    for col in area_cols:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) == 0:
            continue
        stats = {
            "count": int(len(s)),
            "min": float(s.min()),
            "q25": float(s.quantile(0.25)),
            "median": float(s.median()),
            "q75": float(s.quantile(0.75)),
            "max": float(s.max()),
        }
        result["stats"][col] = stats
        # 단위 판별
        med = stats["median"]
        if med < 50:
            unit_guess = "10a 단위 의심 (×1000 필요)"
        elif med < 500:
            unit_guess = "아르(a) 단위 의심 (×100 필요)"
        elif 500 <= med <= 5000:
            unit_guess = "m² 단위 정상"
        else:
            unit_guess = "ha 단위 의심 (×10000 필요)"
        result["stats"][col]["unit_guess"] = unit_guess
    return result


def audit_yield_column(df: pd.DataFrame) -> dict:
    """총출하량 컬럼 단위 판별."""
    yield_cols = [c for c in df.columns if "출하량" in c or "yield" in c.lower() or "수확" in c]
    result = {"cols_found": yield_cols, "stats": {}}
    for col in yield_cols:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        s = s[s > 0]
        if len(s) == 0:
            continue
        stats = {
            "count": int(len(s)),
            "min": float(s.min()),
            "q25": float(s.quantile(0.25)),
            "median": float(s.median()),
            "q75": float(s.quantile(0.75)),
            "max": float(s.max()),
        }
        med = stats["median"]
        if med < 100:
            unit_guess = "박스/상자 단위 의심 (중앙값이 너무 작음)"
        elif med < 1000:
            unit_guess = "10kg 묶음 단위 의심"
        elif 1000 <= med <= 100000:
            unit_guess = "kg 단위 정상"
        else:
            unit_guess = "g 단위 의심"
        stats["unit_guess"] = unit_guess
        result["stats"][col] = stats
    return result


def compute_yield_per_m2(df: pd.DataFrame, crop: str, default_area: float) -> dict:
    """yield_per_m2 분포 계산 및 RDA 기준 비교."""
    area_col = next((c for c in df.columns if "면적" in c), None)
    yield_col = next((c for c in df.columns if "출하량" in c), None)
    if not area_col or not yield_col:
        return {"error": "컬럼 없음", "area_col": area_col, "yield_col": yield_col}

    area = pd.to_numeric(df[area_col], errors="coerce").fillna(default_area).replace(0, default_area)
    yld  = pd.to_numeric(df[yield_col], errors="coerce").fillna(0).clip(lower=0)

    yield_per_m2 = yld / area
    yield_per_m2 = yield_per_m2[yield_per_m2 > 0]

    lo, hi = RDA_BOUNDS.get(crop, (0, 999))
    n_above = int((yield_per_m2 > hi * 10).sum())
    n_below = int((yield_per_m2 < lo / 10).sum())

    return {
        "count": int(len(yield_per_m2)),
        "min":  float(yield_per_m2.min()) if len(yield_per_m2) > 0 else 0,
        "q25":  float(yield_per_m2.quantile(0.25)) if len(yield_per_m2) > 0 else 0,
        "median": float(yield_per_m2.median()) if len(yield_per_m2) > 0 else 0,
        "q75":  float(yield_per_m2.quantile(0.75)) if len(yield_per_m2) > 0 else 0,
        "max":  float(yield_per_m2.max()) if len(yield_per_m2) > 0 else 0,
        "rda_lo": lo, "rda_hi": hi,
        "n_above_10x_rda": n_above,
        "n_below_tenth_rda": n_below,
        "flag_10x_over": n_above > 5,
    }


def main():
    audit_results = {}

    # ── 생산 데이터 감사 ───────────────────────────────────────────────────────
    log_lines.append("## 1. 생산 CSV 감사 (총출하량 + 식부면적)")
    log_lines.append("")

    prod_files = find_csv_files("생산")
    rebs_files = find_csv_files("재배정보")
    all_prod_files = prod_files + rebs_files

    if not all_prod_files:
        # 대안: data/ 디렉터리 검색
        data_dir = ROOT / "data"
        all_prod_files = list(data_dir.glob("**/*.csv")) if data_dir.exists() else []

    log_lines.append(f"- 발견된 생산/재배 CSV 파일: {len(all_prod_files)}개")

    encodings = ["utf-8", "euc-kr", "cp949", "utf-8-sig"]
    loaded_frames = []

    for fpath in all_prod_files[:20]:  # 최대 20개 파일 처리
        for enc in encodings:
            try:
                df = pd.read_csv(fpath, encoding=enc, low_memory=False)
                df["_source_file"] = os.path.basename(fpath)
                loaded_frames.append(df)
                break
            except Exception:
                continue

    if not loaded_frames:
        log_lines.append("- **경고**: CSV 파일 로드 실패 — parquet 캐시로 대체 시도")
        # parquet 캐시 확인
        cache_dir = ROOT / ".cache" / "training"
        if cache_dir.exists():
            parquet_files = list(cache_dir.glob("*.parquet"))
            log_lines.append(f"  - parquet 캐시 발견: {len(parquet_files)}개")
            for pf in parquet_files[:10]:
                try:
                    df = pd.read_parquet(pf)
                    df["_source_file"] = pf.name
                    loaded_frames.append(df)
                except Exception:
                    pass

    if loaded_frames:
        combined = pd.concat(loaded_frames, ignore_index=True)
        log_lines.append(f"- 전체 로드 행: {len(combined):,}")
        log_lines.append(f"- 컬럼 목록: {list(combined.columns[:15])}")
        log_lines.append("")

        area_audit = audit_area_column(combined, "전체")
        log_lines.append("### 식부면적 컬럼 감사")
        for col, st in area_audit["stats"].items():
            log_lines.append(f"- 컬럼 `{col}`: min={st['min']:.1f}, 중앙={st['median']:.1f}, max={st['max']:.1f}")
            log_lines.append(f"  → **단위 판정**: {st['unit_guess']}")
        log_lines.append("")

        yield_audit = audit_yield_column(combined)
        log_lines.append("### 총출하량 컬럼 감사")
        for col, st in yield_audit["stats"].items():
            log_lines.append(f"- 컬럼 `{col}`: min={st['min']:.1f}, 중앙={st['median']:.1f}, max={st['max']:.1f}")
            log_lines.append(f"  → **단위 판정**: {st['unit_guess']}")
        log_lines.append("")

        # 작물별 yield_per_m2 분포
        log_lines.append("### yield_per_m2 분포 vs RDA 기준 (작물별)")
        log_lines.append("")

        crop_col = next((c for c in combined.columns if "품목" in c or "작물" in c or "crop" in c.lower()), None)
        default_areas = {"딸기": 1200, "방울토마토": 1600, "완숙토마토": 1400, "참외": 3800, "파프리카": 2500}

        for crop, (lo, hi) in RDA_BOUNDS.items():
            if crop_col:
                mask = combined[crop_col].astype(str).str.contains(crop[:2], na=False)
                sub = combined[mask]
            else:
                sub = combined
            if len(sub) == 0:
                continue
            ypm = compute_yield_per_m2(sub, crop, default_areas.get(crop, 1200))
            audit_results[crop] = ypm
            flag = "⚠ 10배 이상 이상값 다수" if ypm.get("flag_10x_over") else "정상 범위"
            log_lines.append(f"**{crop}**: 중앙={ypm.get('median', 0):.2f} kg/m², RDA기준 [{lo}~{hi}], {flag}")
            if ypm.get("flag_10x_over"):
                log_lines.append(f"  → RDA 10배 초과 행: {ypm['n_above_10x_rda']}개 — **식부면적 단위 오류 강하게 의심**")
    else:
        log_lines.append("- **경고**: 분석할 CSV/parquet 없음 — 직접 면적 데이터 확인 필요")

    # ── stage2 메타에서 학습 타겟 추론 ────────────────────────────────────────
    log_lines.append("")
    log_lines.append("## 2. stage2_meta에서 역추론된 학습 타겟 분포")
    log_lines.append("")

    EXPECTED_ANNUAL_RANGE = {
        "strawberry":    (2.0,  12.0),
        "cherry_tomato": (5.0,  25.0),
        "tomato":        (8.0,  30.0),
        "melon":         (3.0,  12.0),
        "paprika":       (8.0,  20.0),
    }

    log_lines.append("| 작물 | train_rmse | 기대 범위 | RMSE/범위 | 단위 이상 여부 |")
    log_lines.append("|------|-----------|---------|----------|--------------|")

    for crop_en, (lo, hi) in EXPECTED_ANNUAL_RANGE.items():
        meta_path = ROOT / "models" / "artifacts" / crop_en / "stage2_meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rmse = meta.get("train_rmse", 0)
        expected_range = hi - lo
        ratio = rmse / expected_range if expected_range > 0 else 0
        flag = "⚠ 단위 오류 의심" if ratio > 0.5 else "정상"
        log_lines.append(f"| {meta.get('crop_ko')} | {rmse:.2f} | [{lo}~{hi}] | {ratio:.1%} | {flag} |")

    log_lines.append("")
    log_lines.append("> RMSE/기대범위 > 50%이면 학습 타겟이 정상 단위가 아님을 강하게 의심")

    # ── 결론 ─────────────────────────────────────────────────────────────────
    log_lines.append("")
    log_lines.append("## 3. 결론 및 액션 아이템")
    log_lines.append("")
    log_lines.append("- [ ] 식부면적 컬럼 단위 공식 확인 (10a → ×1000 변환 필요 여부)")
    log_lines.append("- [ ] 총출하량 단위 확인 (kg vs 상자)")
    log_lines.append("- [ ] 단위 변환 후 yield_per_m2 범위가 RDA 기준 내에 드는지 재검증")
    log_lines.append("- [ ] 단위 수정 후 전 작물 재학습")

    # 로그 파일 저장
    out_path = Path(__file__).parent / "01_data_unit_audit.md"
    out_path.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"[완료] {out_path}")

    # 결과 JSON 저장 (후속 스크립트에서 활용)
    json_path = Path(__file__).parent / "audit_results.json"
    json_path.write_text(json.dumps(audit_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[완료] {json_path}")


if __name__ == "__main__":
    main()
