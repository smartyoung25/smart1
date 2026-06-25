import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
path = sys.argv[1]
df = pd.read_excel(path, sheet_name='농가', header=None)
# 스마트팜 시설 구축 현황 부분 (42~110행)
print("=== 스마트팜 시설 구축 현황 (42~110행) ===")
for i in range(42, 115):
    row = df.iloc[i]
    row_str = ' '.join([str(v) for v in row.values if str(v) != 'nan'])
    if row_str.strip():
        print(f"행{i+1}: {row_str[:250]}")

print("\n=== 대농구/시설 상각 (530~620행) ===")
for i in range(530, 625):
    row = df.iloc[i]
    row_str = ' '.join([str(v) for v in row.values if str(v) != 'nan'])
    if row_str.strip():
        print(f"행{i+1}: {row_str[:250]}")
