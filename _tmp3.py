import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
path = sys.argv[1]
# 농가 시트 확인
df = pd.read_excel(path, sheet_name='농가', header=None)
print(f"농가 시트: {df.shape}")
# 스마트팜, 장비, 시공 관련 행
for i, row in df.iterrows():
    row_str = ' '.join([str(v) for v in row.values if str(v) != 'nan'])
    if any(kw in row_str for kw in ['스마트','장비','센서','제어','환경','양액','설비','시공','관개','관수','구동','측정','ICT','IoT','자동','SMART']):
        print(f"행{i}: {row_str[:300]}")
