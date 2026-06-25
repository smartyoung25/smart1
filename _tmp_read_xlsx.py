import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
path = sys.argv[1]
sheets = pd.read_excel(path, sheet_name=None, header=None)
print("시트 목록:", list(sheets.keys()))
for name, df in sheets.items():
    print(f"\n=== {name} ({df.shape[0]}행 x {df.shape[1]}열) ===")
    print(df.iloc[:40].to_string())
