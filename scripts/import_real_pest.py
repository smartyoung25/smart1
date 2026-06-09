# -*- coding: utf-8 -*-
"""감귤 병해충 예찰조사 parquet → 읍면동/병해별 발병률 JSON 적재.

입력: data_real/pest_citrus_YYYY.parquet (병해충 예찰조사 감귤, 읍면동/연도)
출력: api/data/real/pest_jeju.json (읍면동별 더뎅이병·궤양병·검은점무늬병·진딧물·깍지벌레 발병률)

★ 예찰 parquet은 연도별 소용량이라 Drive MCP가 인라인 반환 → 디스크에 직접 받은 뒤 실행.
사용: python scripts/import_real_pest.py data_real/pest_citrus_2023.parquet [...연도 추가]
→ /field/pest·G5/F6 가 제주 감귤에 source='pest_survey_real' 실 발병률 제공.

확인된 스키마 컬럼(2023):
  emd_nm, exmn_ymd, vrty_nm,
  scab_onst_tree_rt(더뎅이병 발병률), canker_onst_tree_rt(궤양병),
  bksp_onst_frt_rt(검은점무늬병 과실 발병률), ppbt_onst_frt_rt(점무늬낙엽병),
  aphid_onst_tree_rt(진딧물), pyhl_onst_tree_rt(가루이),
  ccacti_onst_tree_rt(곰팡이), dors_onst_tree_rt(깍지벌레)
"""
import sys, json
from pathlib import Path
import pandas as pd

OUT = Path("api/data/real/pest_jeju.json")
# 발병률 컬럼 → 한글 병해명
DISEASE = {
    "scab_onst_tree_rt": "더뎅이병", "canker_onst_tree_rt": "궤양병",
    "bksp_onst_frt_rt": "검은점무늬병", "ppbt_onst_frt_rt": "점무늬낙엽병",
    "aphid_onst_tree_rt": "진딧물", "pyhl_onst_tree_rt": "가루이",
    "ccacti_onst_tree_rt": "곰팡이병", "dors_onst_tree_rt": "깍지벌레",
}


def main():
    srcs = sys.argv[1:] or ["data_real/pest_citrus_2023.parquet"]
    frames = [pd.read_parquet(s) for s in srcs if Path(s).exists()]
    if not frames:
        print("입력 parquet 없음:", srcs); return
    df = pd.concat(frames, ignore_index=True)
    for c in DISEASE:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    emd_col = "emd_nm" if "emd_nm" in df.columns else ("emd" if "emd" in df.columns else None)
    out = {"source": "감귤 병해충 예찰조사 (제주)", "rows": int(len(df)), "by_emd": {}, "overall": {}}
    # 전체 평균 발병률
    for c, nm in DISEASE.items():
        if c in df.columns and df[c].notna().any():
            out["overall"][nm] = round(float(df[c].mean()), 1)
    # 읍면동별
    if emd_col:
        for emd, g in df.groupby(emd_col):
            if not str(emd).strip(): continue
            rec = {}
            for c, nm in DISEASE.items():
                if c in g.columns and g[c].notna().any():
                    rec[nm] = round(float(g[c].mean()), 1)
            if rec:
                out["by_emd"][str(emd)] = {"n": int(len(g)), "disease": rec}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"적재 완료: {len(df)}건 → 읍면동 {len(out['by_emd'])}·병해 {len(out['overall'])} → {OUT}")


if __name__ == "__main__":
    main()
