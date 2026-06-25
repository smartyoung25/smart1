import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
path = sys.argv[1]
# 농가2 시트에서 장비 관련 섹션 찾기
df = pd.read_excel(path, sheet_name='농가2', header=None)
# 장비, 스마트팜, 설비, 기계 키워드 포함 행 찾기
for i, row in df.iterrows():
    row_str = ' '.join([str(v) for v in row.values if str(v) != 'nan'])
    if any(kw in row_str for kw in ['장비','스마트팜','센서','제어','환경','양액','설비','기계','구동','측정','모니터']):
        print(f"행{i}: {row_str[:200]}")
