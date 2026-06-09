# -*- coding: utf-8 -*-
"""팜맵 농경지전자지도 parquet → 지역 집계 JSON 적재 (실데이터 주입).

입력: data_real/farmmap_2024.parquet (팜맵, 제주 276,491필지)
출력: api/data/real/parcels_jeju.json (시군구·읍면동 필지수·면적·지목 + 샘플 필지)

사용: python scripts/import_real_parcels.py [parquet경로]
→ /field/parcels·/field/cluster 가 제주 농장에 source='farmmap_real' 실 필지 제공.
"""
import sys, json
from pathlib import Path
import pandas as pd

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data_real/farmmap_2024.parquet")
OUT = Path("api/data/real/parcels_jeju.json")


def _parse(addr):
    p = str(addr).split()
    return (p[1] if len(p) > 1 else "", p[2] if len(p) > 2 else "", p[3] if len(p) > 3 else "")


def main():
    df = pd.read_parquet(SRC)
    df["ltlnd_area"] = pd.to_numeric(df["ltlnd_area"], errors="coerce")
    df[["sgg", "emd", "ri"]] = df["stdg_addr"].apply(lambda a: pd.Series(_parse(a)))
    out = {"source": "팜맵 농경지전자지도 2024 (제주)", "rows": int(len(df)),
           "by_sigungu": {}, "by_emd": {}}
    for sgg, g in df.groupby("sgg"):
        if not sgg: continue
        out["by_sigungu"][sgg] = {"count": int(len(g)),
            "total_area_ha": round(g["ltlnd_area"].sum() / 10000, 1),
            "by_clsf": {k: int(v) for k, v in g["clsf_nm"].value_counts().head(6).items()}}
    for (sgg, emd), g in df.groupby(["sgg", "emd"]):
        if not sgg or not emd: continue
        samp = [{"name": f"{r['ri']} {str(r['frmp_id'])[-4:]}".strip(), "jimok": r["clsf_nm"],
                 "area_ha": round((r["ltlnd_area"] or 0) / 10000, 3), "crop": r["fclt_nm"]}
                for _, r in g.head(5).iterrows()]
        out["by_emd"][f"{sgg} {emd}"] = {"count": int(len(g)),
            "total_area_ha": round(g["ltlnd_area"].sum() / 10000, 1), "parcels": samp}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"적재 완료: {len(df)}필지 → 시군구 {len(out['by_sigungu'])}·읍면동 {len(out['by_emd'])} → {OUT}")


if __name__ == "__main__":
    main()
