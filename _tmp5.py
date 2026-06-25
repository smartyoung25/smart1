import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
path = sys.argv[1]
sheets = pd.read_excel(path, sheet_name=None, header=None)
# 매출/비용 관련 시트 집중 분석
target = ['소득분석2','소득분석','농가2','생산 및 판매','부산물']
for name in target:
    if name not in sheets: continue
    df = sheets[name]
    print(f"\n{'='*60}")
    print(f"=== {name} ({df.shape[0]}행 x {df.shape[1]}열) ===")
    for i, row in df.iterrows():
        row_str = ' '.join([str(v) for v in row.values if str(v) != 'nan'])
        if row_str.strip():
            print(f"행{i+1}: {row_str[:200]}")
