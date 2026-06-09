# -*- coding: utf-8 -*-
"""흙토람 토양검정 parquet → 지역 집계 JSON 적재 (실데이터 주입).

입력: data_real/soil_2024.parquet (흙토람 토양검정, 제주 13,842필지)
출력: api/data/real/soil_jeju.json (시군구·읍면동 ph·EC·유기물·인산·칼륨 평균)

사용: python scripts/import_real_soil.py [parquet경로]
→ /field/soil 이 제주 농장(sido='제주…')에 source='naas_soil_real'로 실값 제공.
"""
import sys, json
from pathlib import Path
import pandas as pd

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data_real/soil_2024.parquet")
OUT = Path("api/data/real/soil_jeju.json")


def _agg(g):
    def m(c, d=2):
        v = pd.to_numeric(g[c], errors="coerce")
        return round(float(v.mean()), d) if v.notna().any() else None
    return {"n": int(len(g)), "ph": m("ph"), "ec": m("elcndctvty", 3),
            "organic": m("orgnc_mttr_cntt", 1), "phosphate": m("phsphrs", 1),
            "potassium": m("ptssm", 3)}


def main():
    df = pd.read_parquet(SRC)
    out = {"source": "흙토람 토양검정 2024 (제주)", "rows": int(len(df)),
           "by_sigungu": {}, "by_emd": {}}
    for sgg, g in df.groupby("sgg"):
        if pd.isna(sgg): continue
        out["by_sigungu"][str(sgg)] = _agg(g)
    for (sgg, emd), g in df.groupby(["sgg", "emd"]):
        if pd.isna(sgg) or pd.isna(emd): continue
        out["by_emd"][f"{sgg} {emd}"] = _agg(g)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"적재 완료: {len(df)}필지 → 시군구 {len(out['by_sigungu'])}·읍면동 {len(out['by_emd'])} → {OUT}")


if __name__ == "__main__":
    main()
