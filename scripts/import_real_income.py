# -*- coding: utf-8 -*-
"""농진청 소득조사 parquet → 작목별 경영 벤치마크 JSON (개인정보 제외).

입력: data_real/income_frtr_2022.parquet (소득조사 과수, 120농가·396항목)
출력: api/data/real/income_benchmark.json (작목별 소득률·수취가·생산비·출하구조 평균)

★ 개인정보(frm_id·name·srvfrm_no)는 적재하지 않음 — 작목 단위 집계만.
사용: python scripts/import_real_income.py [parquet경로]
→ /benchmark(C9)가 작목 매칭 시 상위농가 실값으로 비교.
"""
import sys, json
from pathlib import Path
import pandas as pd

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data_real/income_frtr_2022.parquet")
OUT = Path("api/data/real/income_benchmark.json")
NMAP = {"노지감귤": "감귤", "참다래(키위)": "키위", "시설감귤": "감귤(시설)"}


def main():
    df = pd.read_parquet(SRC)
    nums = ["prdv_qty_kg_ea", "frmprc_wnpkg", "inc_rt_%", "prdctn_cst_wn",
            "prdctn_rt_%", "ship_whlsmkt_%", "ship_direct_%", "ship_nhcs_%"]
    for c in nums:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    out = {"source": "농진청 소득조사 2022 (과수)", "unit_py": 300, "by_crop": {}}
    for crp, g in df.groupby("crpnm"):
        inc = g["inc_rt_%"].dropna()
        out["by_crop"][NMAP.get(crp, crp)] = {
            "n": int(len(g)), "orig": crp,
            "yield_kg_per_300py": round(g["prdv_qty_kg_ea"].mean(), 0),
            "farmprice_wn_kg": round(g["frmprc_wnpkg"].mean(), 0),
            "income_rate_pct": round(inc.mean(), 1) if len(inc) else None,
            "income_rate_top25_pct": round(inc.quantile(0.75), 1) if len(inc) else None,
            "production_cost_wn": round(g["prdctn_cst_wn"].mean(), 0),
            "marketability_pct": round(g["prdctn_rt_%"].mean(), 1),
            "ship_wholesale_pct": round(g["ship_whlsmkt_%"].mean(), 1),
            "ship_direct_pct": round(g["ship_direct_%"].mean(), 1),
            "ship_nh_pct": round(g["ship_nhcs_%"].mean(), 1),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"적재 완료(PII 제외): {len(df)}농가 → 작목 {len(out['by_crop'])} → {OUT}")


if __name__ == "__main__":
    main()
