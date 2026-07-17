"""단일 게이트 정책 — 모델 승격/폴백 판정의 유일 출처(Single Source of Truth).

기존에 코드 곳곳에 흩어져 있던 상충 게이트를 이 모듈로 일원화한다:
  - train/train_m2.py   : MAPE ≤ 25
  - routers/admin.py    : MAPE ≤ 35 (R² 무시)  /  R² ≥ 0.0 AND MAPE ≤ 35
  - model_registry.py   : s2_meta.gate_passed (완화기준 그대로 신뢰)
  - train/train_m1.py   : R² ≥ 0.62   (M1 생육 — 대상 지표가 달라 별도 유지)
  - legacy_model_adapter: R² ≥ 0.70 / 0.50 티어

본 모듈의 판정은 중간보고서 표4(검증적용/조건부/폴백)와 동일한 결과를 산출한다.
임계값 조정은 반드시 이 파일의 상수에서만 수행한다.

★ 판정은 **교차검증 CV R² 중심**이다 (2026-07-17 재편).

  왜 MAPE 를 주 게이트에서 내렸나:
    ① 지표가 거짓이었다 — stage2_meta 의 `mape` 는 학습(in-sample) MAPE 다.
       실측: 딸기 학습 17.8% vs CV 107.3%(6배) · 완숙토마토 28.1% vs 85.4%(3배).
       구 임계(≤25%)는 이 학습값에 맞춰져 있었다.
    ② MAPE 는 monthly 모드에서 구조적으로 폭발한다 — 수확 초·말기 수확량이 0 에
       가까워 작은 값으로 나눈다. 딸기 CV MAPE 107% 는 모델 부실이 아니라 지표 특성이며,
       같은 모델의 CV R² 는 0.295 로 멀쩡하다.
    ③ 그래서 monthly(딸기·파프리카)와 annual(나머지)을 MAPE 로 비교하는 것 자체가
       성립하지 않았다. R² 는 두 모드에서 해석이 안정적이다.
  → CV MAPE 는 참고·경보(flags)로 남기고 판정에서 제외한다.
     0 근처에 견디는 지표(WAPE/sMAPE) 도입 시 재검토할 것.

판정 규칙(M2 수확량):
  · CV R² 없음                       → 폴백 : 판정 불가(학습값으로 대신 판정하지 않는다)
  · CV R² ≤ CV_R2_FALLBACK(0.0)      → 폴백 : 평균 예측보다 나쁨 = 모델이 무의미
  · CV R² < CV_R2_MIN                → 조건부 : 설명력 부족(서비스하되 보완 대상)
  · |train R² − CV R²| > OVERFIT_GAP → 조건부 : 과적합 의심
  · 그 외(CV R² ≥ CV_R2_MIN)          → 검증적용(serve)
  · n_train < N_MIN                  → 소표본 플래그(판정은 유지, LOGO 재검증 권장)
  · CV MAPE > MAPE_ADVISORY          → 경보 플래그(판정에 영향 없음)

serve_m2 = (검증적용 OR 조건부) → is_active/서비스 대상. 폴백만 서비스 제외.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ── M2(수확량) 게이트 임계 — 조정은 여기 한 곳에서만 ──────────────────────────
# 주 게이트: 교차검증 설명력
CV_R2_MIN      = 0.20   # 이상이면 검증적용, 미만이면 조건부
CV_R2_FALLBACK = 0.0    # 이하면 폴백 — 평균으로 찍는 것보다 나쁨
N_MIN          = 60     # 소표본 경고 임계
OVERFIT_GAP    = 0.30   # train R² − CV R² 이 값 초과 → 과적합 의심(조건부)
# 참고 지표: CV MAPE — 판정하지 않고 경보만(위 ①②③ 참조)
MAPE_ADVISORY  = 50.0   # CV MAPE 가 이 값 초과 → 경보 플래그

SERVE, CONDITIONAL, FALLBACK = "serve", "conditional", "fallback"
_LABEL_KO = {SERVE: "검증 적용", CONDITIONAL: "조건부", FALLBACK: "폴백"}


def _flags(n_train: Optional[int], cv_mape: Optional[float] = None) -> list:
    f = []
    if n_train is not None:
        try:
            if int(n_train) < N_MIN:
                f.append(f"소표본 n={int(n_train)}<{N_MIN} (LOGO 재검증 권장)")
        except (TypeError, ValueError):
            pass
    # CV MAPE 는 경보만 — 판정하지 않는다(모듈 헤더 ①②③ 참조)
    if cv_mape is not None:
        try:
            if float(cv_mape) > MAPE_ADVISORY:
                f.append(f"CV MAPE {float(cv_mape):.1f}% > {MAPE_ADVISORY:.0f}% "
                         f"(참고 — monthly 는 0 근처 표본으로 과대 산출됨)")
        except (TypeError, ValueError):
            pass
    return f


def evaluate_m2_gate(
    cv_mape: Optional[float],
    cv_r2: Optional[float] = None,
    n_train: Optional[int] = None,
    train_r2: Optional[float] = None,
) -> dict:
    """수확량(M2) 모델 판정 — 교차검증 CV R² 중심.

    ★ 첫 인자는 **CV MAPE**(참고 지표)다. 학습 MAPE 를 넘기지 말 것 — 판정에는
      쓰이지 않지만 경보 플래그가 거짓이 된다. 호출은 gate_mape() 를 거칠 것.

    Returns dict:
      verdict   : 'serve' | 'conditional' | 'fallback'
      label     : 한글 라벨(검증 적용/조건부/폴백)
      serve_m2  : bool — True면 M2 모델을 서비스(is_active), False면 상위 계층 폴백
      gate_passed: bool — serve_m2의 별칭(레지스트리 호환)
      flags     : 소표본·CV MAPE 과대 등 경고(판정에 영향 없음)
      reasons   : 판정 근거
    """
    flags = _flags(n_train, cv_mape)

    # 0) 판정 불가 — 검증 지표 없음. 학습값으로 대신 판정하지 않는다(그게 사고 원인이었다).
    if cv_r2 is None:
        return {"verdict": FALLBACK, "label": _LABEL_KO[FALLBACK], "serve_m2": False,
                "gate_passed": False, "flags": flags,
                "reasons": ["CV R² 없음 — 판정 불가(재학습 필요)"]}
    cv_r2 = float(cv_r2)

    # 1) 폴백 — 평균 예측보다 나쁨. 모델을 쓸 이유가 없다.
    if cv_r2 <= CV_R2_FALLBACK:
        return {"verdict": FALLBACK, "label": _LABEL_KO[FALLBACK], "serve_m2": False,
                "gate_passed": False, "flags": flags,
                "reasons": [f"CV R² {cv_r2:.3f} ≤ {CV_R2_FALLBACK:.2f} "
                            f"(평균 예측보다 나쁨 — 폴백)"]}

    # 2) 조건부/검증적용
    verdict = SERVE
    reasons = []
    if cv_r2 < CV_R2_MIN:
        verdict = CONDITIONAL
        reasons.append(f"CV R² {cv_r2:.3f} < {CV_R2_MIN:.2f} (설명력 부족)")
    if train_r2 is not None and (float(train_r2) - cv_r2) > OVERFIT_GAP:
        verdict = CONDITIONAL
        reasons.append(f"train R² − CV R² > {OVERFIT_GAP:.2f} (과적합 의심)")
    if not reasons:
        reasons.append(f"기준 충족(CV R² {cv_r2:.3f} ≥ {CV_R2_MIN:.2f})")

    return {"verdict": verdict, "label": _LABEL_KO[verdict], "serve_m2": True,
            "gate_passed": verdict == SERVE, "flags": flags, "reasons": reasons}


def passes_gate(cv_mape, cv_r2=None, n_train=None, train_r2=None) -> bool:
    """서비스 대상 여부(검증적용 또는 조건부). 폴백만 False.

    첫 인자는 CV MAPE(참고 지표) — 판정은 cv_r2 가 한다.
    """
    return evaluate_m2_gate(cv_mape, cv_r2, n_train, train_r2)["serve_m2"]


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


def gate_mape(m: dict):
    """게이트가 쓸 MAPE — 반드시 교차검증 MAPE.

    ★ stage2_meta 의 `mape` 는 학습(in-sample) MAPE 다. 게이트에 쓰면 안 된다.
      실측: 딸기 학습 17.8% vs CV 107.3%(6배) · 완숙토마토 28.1% vs 85.4%(3배).
      게이트가 학습 오차로 판정하면 '검증 적용'이 검증이 아니게 된다.
      (구 학습 스크립트는 Ridge 폴백 경로에서 `mape` 에 CV 값을 넣어, 작목마다 의미가
       달랐다 — 딸기 17.8(학습) vs 오이 22.8(CV) 를 나란히 비교하던 상태.
       2026-07-17 스크립트 수정으로 cv_mape_mean 을 단일 검증 지표로 통일.)
    """
    return m.get("cv_mape_mean")


def evaluate_crop(artifacts_dir, crop_en: str) -> dict:
    """작목 아티팩트에서 권위 지표를 읽어 M2 게이트 판정.

    판정은 교차검증 지표(cv_mape_mean·cv_r2_mean)로만 한다.
    구 아티팩트라 cv_mape_mean 이 없으면 mape 가 None 인 것과 같이 '판정 불가'(폴백)로
    떨어진다 — 학습값으로 대신 판정하지 않는다(그게 이 사고의 원인이었다).
    """
    m = read_stage2_metrics(artifacts_dir, crop_en)
    return evaluate_m2_gate(gate_mape(m), m.get("cv_r2_mean"),
                            m.get("n_train"), m.get("train_r2"))


def should_serve_m2(artifacts_dir, crop_en: str) -> tuple:
    """서빙 가드 전용 — (서빙여부, 판정dict).

    ★ fail-open: 지표가 없는 구 아티팩트는 판정 불가이므로 기존 동작 유지(서빙).
      evaluate_crop을 서빙 가드에 직접 쓰면 지표 없는 작목이 전부 차단되니 주의.
      ※ 판정은 검증 지표(cv_mape_mean)로 한다 — 학습 MAPE 로 판정하지 않는다(gate_mape 참조).
        재학습 전 구 아티팩트는 cv_mape_mean 이 없어 fail-open 으로 서빙이 유지된다.
        차단하려면 재학습으로 검증 지표를 채운 뒤 판정할 것(서빙 중단은 별도 결정 사항).
    """
    m = read_stage2_metrics(artifacts_dir, crop_en)
    if m.get("cv_r2_mean") is None:
        return True, {"verdict": SERVE, "label": "판정불가(검증지표없음)",
                      "serve_m2": True, "gate_passed": False, "flags": [],
                      "reasons": ["CV R² 없음 — fail-open(재학습 필요)"]}
    v = evaluate_m2_gate(gate_mape(m), m.get("cv_r2_mean"),
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
