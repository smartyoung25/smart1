"""단일 게이트 정책 — 모델 승격/폴백 판정의 유일 출처(Single Source of Truth).

기존에 코드 곳곳에 흩어져 있던 상충 게이트를 이 모듈로 일원화한다:
  - train/train_m2.py   : MAPE ≤ 25
  - routers/admin.py    : MAPE ≤ 35 (R² 무시)  /  R² ≥ 0.0 AND MAPE ≤ 35
  - model_registry.py   : s2_meta.gate_passed (완화기준 그대로 신뢰)
  - train/train_m1.py   : R² ≥ 0.62   (M1 생육 — 대상 지표가 달라 별도 유지)
  - legacy_model_adapter: R² ≥ 0.70 / 0.50 티어

본 모듈의 판정은 중간보고서 표4(검증적용/조건부/폴백)와 동일한 결과를 산출한다.
임계값 조정은 반드시 이 파일의 상수에서만 수행한다.

판정 규칙(M2 수확량):
  · MAPE > MAPE_FALLBACK            → 폴백(fallback)      : 상위 계층(표준/광역)으로 대체
  · MAPE_SERVE < MAPE ≤ FALLBACK    → 조건부(conditional) : 서비스하되 보완 대상
  · CV R² < CV_R2_MIN               → 조건부              : 설명력 부족
  · |train R² − CV R²| > OVERFIT_GAP → 조건부              : 과적합 의심
  · 그 외(MAPE ≤ SERVE AND R² 충족)  → 검증적용(serve)
  · n_train < N_MIN                 → 소표본 플래그(판정은 유지, LOGO 재검증 권장)

serve_m2 = (검증적용 OR 조건부) → is_active/서비스 대상. 폴백만 서비스 제외.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ── M2(수확량) 게이트 임계 — 조정은 여기 한 곳에서만 ──────────────────────────
MAPE_FALLBACK = 30.0   # MAPE(%)가 이 값 초과 → 폴백
MAPE_SERVE    = 25.0   # 이 값 이하 & R² 충족 → 검증적용
CV_R2_MIN     = 0.20   # 최소 설명력(미만이면 조건부)
N_MIN         = 60     # 소표본 경고 임계
OVERFIT_GAP   = 0.30   # train R² − CV R² 이 값 초과 → 과적합 의심(조건부)

SERVE, CONDITIONAL, FALLBACK = "serve", "conditional", "fallback"
_LABEL_KO = {SERVE: "검증 적용", CONDITIONAL: "조건부", FALLBACK: "폴백"}


def _flags(n_train: Optional[int]) -> list:
    f = []
    if n_train is not None:
        try:
            if int(n_train) < N_MIN:
                f.append(f"소표본 n={int(n_train)}<{N_MIN} (LOGO 재검증 권장)")
        except (TypeError, ValueError):
            pass
    return f


def evaluate_m2_gate(
    mape: Optional[float],
    cv_r2: Optional[float] = None,
    n_train: Optional[int] = None,
    train_r2: Optional[float] = None,
) -> dict:
    """수확량(M2) 모델 판정.

    Returns dict:
      verdict   : 'serve' | 'conditional' | 'fallback'
      label     : 한글 라벨(검증 적용/조건부/폴백)
      serve_m2  : bool — True면 M2 모델을 서비스(is_active), False면 상위 계층 폴백
      gate_passed: bool — serve_m2의 별칭(레지스트리 호환)
      flags     : 소표본 등 경고
      reasons   : 판정 근거
    """
    if mape is None:
        return {"verdict": FALLBACK, "label": _LABEL_KO[FALLBACK], "serve_m2": False,
                "gate_passed": False, "flags": [], "reasons": ["MAPE 없음 — 판정 불가"]}
    mape = float(mape)
    flags = _flags(n_train)

    # 1) 폴백 — 오차 과대
    if mape > MAPE_FALLBACK:
        return {"verdict": FALLBACK, "label": _LABEL_KO[FALLBACK], "serve_m2": False,
                "gate_passed": False, "flags": flags,
                "reasons": [f"MAPE {mape:.1f}% > {MAPE_FALLBACK:.0f}% (폴백)"]}

    # 2) 조건부/검증적용
    verdict = SERVE
    reasons = []
    if mape > MAPE_SERVE:
        verdict = CONDITIONAL
        reasons.append(f"MAPE {mape:.1f}% > {MAPE_SERVE:.0f}%")
    if cv_r2 is not None and float(cv_r2) < CV_R2_MIN:
        verdict = CONDITIONAL
        reasons.append(f"CV R² {float(cv_r2):.3f} < {CV_R2_MIN:.2f} (설명력 부족)")
    if train_r2 is not None and cv_r2 is not None and (float(train_r2) - float(cv_r2)) > OVERFIT_GAP:
        verdict = CONDITIONAL
        reasons.append(f"train R² − CV R² > {OVERFIT_GAP:.2f} (과적합 의심)")
    if not reasons:
        reasons.append("기준 충족(MAPE·R²·표본)")

    return {"verdict": verdict, "label": _LABEL_KO[verdict], "serve_m2": True,
            "gate_passed": verdict == SERVE, "flags": flags, "reasons": reasons}


def passes_gate(mape, cv_r2=None, n_train=None, train_r2=None) -> bool:
    """서비스 대상 여부(검증적용 또는 조건부). 폴백만 False."""
    return evaluate_m2_gate(mape, cv_r2, n_train, train_r2)["serve_m2"]


# ── 지표 로딩 단일 경로 ───────────────────────────────────────────────────────
# ★ stage2_meta.json 이 권위 파일이다. pipeline_meta.json 의 stage2.mape 는
#   "다른 학습 실행 결과일 수 있음"(admin._load_all_meta 주석) — 실제로 참외는
#   pipeline_meta 8.7% vs stage2_meta 63.9% 로 크게 다르다. 게이트 판정은 반드시
#   이 함수로 얻은 권위값을 쓸 것(직접 pipeline_meta 를 읽지 말 것).
_AUTH_KEYS = ("mape", "cv_mape_mean", "cv_r2_mean", "n_train", "train_r2", "gate_passed")


def read_stage2_metrics(artifacts_dir, crop_en: str) -> dict:
    """stage2 지표 로드 — pipeline_meta.stage2 위에 stage2_meta.json(권위)을 덮어씀."""
    base = Path(artifacts_dir) / crop_en
    out: dict = {}
    pm = base / "pipeline_meta.json"
    if pm.exists():
        try:
            out.update((json.loads(pm.read_text(encoding="utf-8")).get("stage2") or {}))
        except Exception:
            pass
    s2 = base / "stage2_meta.json"
    if s2.exists():
        try:
            real = json.loads(s2.read_text(encoding="utf-8"))
            for k in _AUTH_KEYS:
                if real.get(k) is not None:
                    out[k] = real[k]
        except Exception:
            pass
    return out


def evaluate_crop(artifacts_dir, crop_en: str) -> dict:
    """작목 아티팩트에서 권위 지표를 읽어 M2 게이트 판정."""
    m = read_stage2_metrics(artifacts_dir, crop_en)
    return evaluate_m2_gate(m.get("mape"), m.get("cv_r2_mean"),
                            m.get("n_train"), m.get("train_r2"))


def should_serve_m2(artifacts_dir, crop_en: str) -> tuple:
    """서빙 가드 전용 — (서빙여부, 판정dict).

    ★ fail-open: 지표가 없는 구 아티팩트는 판정 불가이므로 기존 동작 유지(서빙).
      evaluate_crop을 서빙 가드에 직접 쓰면 지표 없는 작목이 전부 차단되니 주의.
    """
    m = read_stage2_metrics(artifacts_dir, crop_en)
    if m.get("mape") is None:
        return True, {"verdict": SERVE, "label": "판정불가(지표없음)",
                      "serve_m2": True, "gate_passed": False, "flags": [], "reasons": ["지표 없음 — fail-open"]}
    v = evaluate_m2_gate(m.get("mape"), m.get("cv_r2_mean"),
                         m.get("n_train"), m.get("train_r2"))
    return v["serve_m2"], v


# ── 지표 출처 괴리 감지 ──────────────────────────────────────────────────────
# MAPE가 기록되는 곳이 4군데(권위 stage2_meta / pipeline_meta / registry / pkl 내부)라
# 값이 조용히 어긋나면 게이트·블렌딩·보고서가 동시에 틀어진다(실제로 그랬음).
# 이 함수로 괴리를 드러내고, 테스트가 이를 회귀 감시한다.
def check_consistency(root, crop_en: str, tol: float = 1.0) -> dict:
    """작목별 MAPE 4중 출처 비교. 반환: {authoritative, sources, diverged}."""
    root = Path(root)
    arts = root / "models" / "artifacts"
    auth = read_stage2_metrics(arts, crop_en).get("mape")
    src: dict = {}

    pm = arts / crop_en / "pipeline_meta.json"
    if pm.exists():
        try:
            src["pipeline_meta"] = (json.loads(pm.read_text(encoding="utf-8")).get("stage2") or {}).get("mape")
        except Exception:
            pass

    reg = root / "models" / "registry.json"
    if reg.exists():
        try:
            e = (json.loads(reg.read_text(encoding="utf-8")) or {}).get(crop_en, {})
            act = next((v for v in e.get("versions", []) if v.get("is_active")), None)
            src["registry"] = (act or {}).get("mape_stage2")
        except Exception:
            pass

    for fname in ("m2_yield_model.pkl", "stage2_yield.pkl"):
        p = arts / crop_en / fname
        if p.exists():
            try:
                import pickle
                src["pkl"] = (pickle.loads(p.read_bytes()) or {}).get("mape")
            except Exception:
                pass
            break

    diverged = {k: v for k, v in src.items()
                if v is not None and auth is not None and abs(float(v) - float(auth)) > tol}
    return {"crop_en": crop_en, "authoritative": auth, "sources": src, "diverged": diverged}


# ── 드라이런: 현재 아티팩트 전 작목 판정 출력 ────────────────────────────────
if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    metas = sorted((root / "models" / "artifacts").glob("*/stage2_meta.json"))
    print(f"{'작목':<14}{'MAPE':>7}{'CV_R2':>8}{'n':>7}  {'판정':<8} 근거/플래그")
    print("-" * 78)
    for p in metas:
        crop = p.parent.name
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        r = evaluate_m2_gate(m.get("mape"), m.get("cv_r2_mean"),
                             m.get("n_train"), m.get("train_r2"))
        note = "; ".join(r["reasons"] + r["flags"])
        print(f"{crop:<14}{str(m.get('mape')):>7}{str(m.get('cv_r2_mean')):>8}"
              f"{str(m.get('n_train')):>7}  {r['label']:<8} {note}")
