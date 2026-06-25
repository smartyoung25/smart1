import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
path = sys.argv[1]
sheets = pd.read_excel(path, sheet_name=None, header=None)
# 비용 세부 시트 확인
cost_sheets = ['수도광열비','기타재료비','고용노임','위탁영농비','임차료','기타비용','소농구비']
for name in cost_sheets:
    if name not in sheets: continue
    df = sheets[name]
    print(f"\n=== {name} ({df.shape}) ===")
    for i, row in df.iterrows():
        row_str = ' '.join([str(v) for v in row.values if str(v) != 'nan'])
        if row_str.strip() and row_str != '0 0':
            print(f"  행{i+1}: {row_str[:180]}")
