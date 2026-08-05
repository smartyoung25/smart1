# -*- coding: utf-8 -*-
"""딸기 스마트팜 CAPEX/OPEX 체계화·계층화 (.xlsx)

근거: 농진청 소득조사표(딸기 류창영·900㎡) — 상각비 대농구 675,000 + 영농시설 783,000,
      환경관리시설 제어현황(복합환경제어·관수관비·보온/차광스크린·환기·CO2·난방),
      OPEX 시트(수리유지비=대농기구/영농시설 분리, 수도광열=전기/경유/물, 임차료=토지/대농기구/영농시설).

산출: CAPEX 3계층(대분류>중분류>세부품목) + 업체·성능·취득가·내용연수·잔존율·정액감가상각(수식)
      + 연동 OPEX. 조사표는 집계 상각비만 있어 per-asset 취득가는 「입력」(견적서 연동)·내용연수는
      법인세법 시행규칙 별표·농진청 농기계 내용연수 표준을 적용(비고에 명시).

사용: PYTHONPATH=C:/smart_farm python scripts/_build_capex_opex_taxonomy.py
"""
from __future__ import annotations
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "스마트팜_CAPEX_OPEX_체계화_4작목.xlsx"
FONT = "맑은 고딕"

# ── 작목별 실 시설 구성 (농진청 소득조사표 '농가' 시트 제어현황 설치유무) ────────
# ○ 설치 · × 미설치 · '고장' 원문. 소득분석2 의 집계 상각비(675k/783k·홍길동)는
# 샘플 템플릿이라 작목 공통이며 실 취득가가 아니다 — 실 차이는 아래 시설 구성이다.
CROP_FACILITY = {
    "항목": ["일중천장", "이중천장", "측창(환기)", "천정 보온스크린", "측면 보온스크린", "차광스크린", "관수·관비장치"],
    "딸기 (류창영)":     ["○", "×", "○", "○", "○", "○", "○"],
    "방울토마토 (박경종)": ["○", "×", "○", "○", "×", "○", "○"],
    "완숙토마토 (김선환)": ["○", "×", "×", "○", "×", "○", "×"],
    "참외 (강석구)":     ["○", "×", "○", "×", "×", "×", "고장"],
}
CROP_META = {  # (재배유형, 난방에너지원, 생산량kg)
    "딸기 (류창영)":     ("촉성(1)", "전기+기타(2,10)", "23,516"),
    "방울토마토 (박경종)": ("촉성(1)", "기타(10)", "65,464"),
    "완숙토마토 (김선환)": ("촉성(1)", "등유+제습기(2,10)", "198,797"),
    "참외 (강석구)":     ("반촉성(2)", "심야전기(9)", "50,000"),
}

# 색
C_TITLE = "1C5A3A"; C_HDR = "2F9A62"; C_L1 = "DCE6F1"; C_SOFT = "F4F7F4"; C_INK = "16211B"
thin = Side(style="thin", color="CCCCCC")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)

def _f(sz=10, b=False, color=C_INK): return Font(name=FONT, size=sz, bold=b, color=color)
def _fill(c): return PatternFill("solid", fgColor=c)
CEN = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEF = Alignment(horizontal="left", vertical="center", wrap_text=True)
RIG = Alignment(horizontal="right", vertical="center")

# ── CAPEX 계층 데이터 ────────────────────────────────────────────────────────
# (중분류, 세부품목, 업체예시, 성능·사양예시, 취득가액, 내용연수, 잔존율, 연동OPEX, 비고)
# 취득가액 0 = 「견적서 입력」. 내용연수=표준(법인세법 별표·농진청 농기계 기준).
CAPEX = {
    "① 영농시설 (구조·피복·보온·차광)": [
        ("온실 구조체", "철골 골조·기초", "(예) 그린플러스·명성GT", "단동/연동 비닐온실, 내재해형", 0, 12, 10, "수리유지비(영농시설)·임차료(영농시설)", "비닐온실 철골 10~15년"),
        ("온실 구조체", "유리/경질판 온실", "(예) 대한하우스", "벤로형 유리온실", 0, 20, 10, "수리유지비(영농시설)", "유리온실 15~20년"),
        ("피복", "피복필름(장기성 PO)", "(예) 일신화학", "PO 0.15mm, 광투과 90%+", 0, 3, 0, "당해 자재비(소모성)", "★소모성 1~3년 — 자산화 여부 확인"),
        ("보온", "천정 보온스크린", "(예) 룩스퍼스", "다겹 보온커튼, 보온율 60%+", 0, 6, 10, "수리유지비(영농시설)·전기(개폐)", "스크린 5~7년"),
        ("보온", "측면 보온스크린", "(예) 룩스퍼스", "다겹, 자동개폐", 0, 6, 10, "수리유지비(영농시설)·전기", "스크린 5~7년"),
        ("차광", "차광 스크린", "(예) 스벤손", "알루미늄 차광 50~70%", 0, 6, 10, "수리유지비(영농시설)", "스크린 5~7년"),
        ("재배베드", "재배베드(거터)·배지받침", "(예) 그로단·리코", "고설 벤치·NFT 거터", 0, 8, 10, "수리유지비(영농시설)·배지 교체비", "설비 8~10년, 배지는 소모성"),
    ],
    "② 환경관리 기자재 (제어·설비)": [
        ("복합환경제어", "복합환경제어 시스템", "(예) 프리바·나래트렌드", "제어반+SW, 온·습·CO2·관수 통합", 0, 8, 10, "전기·SW 구독료·수리유지비", "제어설비 7~10년"),
        ("관수·관비", "양액기(관비장치)·펌프", "(예) 네타핌·프리바", "EC/pH 자동제어, 다구역", 0, 8, 10, "전기·물·양액소재비·수리유지비", "관수설비 7~10년"),
        ("난방", "난방기(온풍/온수)", "(예) 대성하이텍", "경유/가스/히트펌프", 0, 9, 10, "수도광열비(경유·가스·전기)·수리유지비", "난방기 8~10년"),
        ("CO2 시비", "CO2 발생·공급 설비", "(예) 코비시스템", "액화CO2/연소식 시비", 0, 8, 10, "CO2 원료비·전기", "8~10년"),
        ("환기", "측창/천창 개폐 모터", "(예) 리코엔지니어링", "감속모터·랙피니언", 0, 8, 10, "전기·수리유지비", "8~10년"),
        ("계측·센서", "환경센서(온습도·일사·CO2·EC/pH)", "(예) 센서웨이", "무선/유선 다지점", 0, 5, 10, "전기·교정비·소모품(전극)", "센서 5년"),
    ],
    "③ 대농기구 (운반·방제·관리)": [
        ("운반", "전동 운반차·모노레일", "(예) 아그로텍", "적재 300kg급", 0, 7, 10, "수리유지비(대농기구)·전기/유류·임차료(대안)", "운반기구 5~8년"),
        ("방제", "방제기(동력분무·연무기)", "(예) 아세아텍", "동력 SS/연무", 0, 6, 10, "수리유지비(대농기구)·유류·약제비", "방제기 5~7년"),
        ("관리", "예초기·기타 관리기구", "(예) 계양", "휴대형", 0, 5, 10, "수리유지비(대농기구)·유류", "5~7년"),
    ],
    "④ 소모성 자재 (당해비용 · 감가상각 대상 아님)": [
        ("소모성", "배지(코코피트·암면)", "(예) 그로단", "슬라브/포트", 0, 1, 0, "→ OPEX(기타재료비)", "★자산 아님 — 당해 비용처리"),
        ("소모성", "양액 원소재·소독제", "-", "-", 0, 1, 0, "→ OPEX(기타재료비)", "★당해 비용처리"),
        ("소모성", "소농구(호미·낫·전정가위 등)", "-", "-", 0, 1, 0, "→ OPEX(소농구비)", "★조사표 소농구비 항목"),
    ],
}

wb = Workbook()

# ══ Sheet1: CAPEX 자산 계층 등록부 ══════════════════════════════════════════
ws = wb.active; ws.title = "CAPEX 계층 등록부"
COLS = ["대분류", "중분류", "세부품목", "업체(제조사)", "성능·사양", "취득가액(원)",
        "내용연수(년)", "잔존율(%)", "연 감가상각(정액,원)", "연동 OPEX", "비고"]
W = [17, 13, 20, 18, 22, 13, 9, 8, 15, 24, 20]
for i, w in enumerate(W): ws.column_dimensions[get_column_letter(i+1)].width = w

ws.merge_cells("A1:K1")
ws["A1"] = "스마트팜 CAPEX 자산 계층 등록부 (3계층 · 정액 감가상각 · 시설작목 공통 프레임)"
ws["A1"].font = _f(14, True, "FFFFFF"); ws["A1"].fill = _fill(C_TITLE); ws["A1"].alignment = CEN
ws.row_dimensions[1].height = 26
ws.merge_cells("A2:K2")
ws["A2"] = ("근거: 농진청 스마트팜 소득조사표(딸기·방울·완숙토마토·참외 4작목, 각 900㎡). "
            "★ 조사표 '소득분석2'의 집계 상각비(대농구675,000+영농시설783,000·이름'홍길동')는 샘플 템플릿이라 4작목 동일 → 실 취득가 아님. "
            "취득가액은 견적서 「입력」, 내용연수는 법인세법 시행규칙 별표·농진청 농기계 표준. 연 감가상각 = 취득가액×(1−잔존율)÷내용연수(수식). "
            "작목별 실 차이는 '작목별 시설 구성' 시트 참조.")
ws["A2"].font = _f(8, False, "595959"); ws["A2"].alignment = LEF
ws.row_dimensions[2].height = 30

hr = 3
for i, c in enumerate(COLS):
    cell = ws.cell(hr, i+1, c); cell.font = _f(9, True, "FFFFFF"); cell.fill = _fill(C_HDR)
    cell.alignment = CEN; cell.border = BORDER

r = hr + 1
for l1, items in CAPEX.items():
    l1_start = r
    for it in items:
        mid, item, maker, spec, cost, life, resid, opex, note = it
        vals = [l1, mid, item, maker, spec, cost, life, resid, None, opex, note]
        for ci, v in enumerate(vals):
            cell = ws.cell(r, ci+1, v); cell.border = BORDER; cell.font = _f(9)
            if ci in (5, 8): cell.alignment = RIG; cell.number_format = '#,##0'
            elif ci in (6, 7): cell.alignment = CEN
            else: cell.alignment = LEF
        # 연 감가상각 수식 (소모성=0년이면 상각 없음)
        fcell = ws.cell(r, 9)
        if life and int(life) >= 2:
            fcell.value = f"=F{r}*(1-H{r}/100)/G{r}"
        else:
            fcell.value = 0
        fcell.number_format = '#,##0'
        r += 1
    # 대분류 셀 병합
    ws.merge_cells(start_row=l1_start, start_column=1, end_row=r-1, end_column=1)
    c = ws.cell(l1_start, 1); c.fill = _fill(C_L1); c.font = _f(10, True, C_TITLE)
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

# 합계행
ws.cell(r, 3, "① ~ ③ 감가상각 합계 (소모성 제외)").font = _f(9, True)
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
tot = ws.cell(r, 9)
# 소모성(④) 행 제외: ④는 마지막 3행 → 상각합계는 그 위까지
last_asset = r - 1 - len(CAPEX["④ 소모성 자재 (당해비용 · 감가상각 대상 아님)"])
tot.value = f"=SUM(I{hr+1}:I{last_asset})"; tot.number_format = '#,##0'; tot.font = _f(10, True, C_TITLE)
tot.fill = _fill(C_L1); tot.alignment = RIG; tot.border = BORDER
for cc in range(1, 12): ws.cell(r, cc).border = BORDER; ws.cell(r, cc).fill = _fill(C_L1)
sumrow = r

# 조사표 대조행
r += 1
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
ws.cell(r, 1, "▶ 조사표 템플릿 상각비(대농구 675,000 + 영농시설 783,000 = 1,458,000·샘플값) — 실 취득가 입력 시 위 합계로 대체·대조").font = _f(9, False, "A6431E")
ws.cell(r, 9, 1458000).number_format = '#,##0'; ws.cell(r, 9).font = _f(9, True, "A6431E"); ws.cell(r, 9).alignment = RIG
ws.freeze_panes = "A4"

# ══ Sheet2: OPEX ↔ CAPEX 연동 매트릭스 ═════════════════════════════════════
ws2 = wb.create_sheet("OPEX-CAPEX 연동")
for i, w in enumerate([20, 22, 26, 30]): ws2.column_dimensions[get_column_letter(i+1)].width = w
ws2.merge_cells("A1:D1")
ws2["A1"] = "OPEX ↔ CAPEX 연동 매트릭스 (투자비가 유발하는 운영비)"
ws2["A1"].font = _f(13, True, "FFFFFF"); ws2["A1"].fill = _fill(C_TITLE); ws2["A1"].alignment = CEN
ws2.row_dimensions[1].height = 24
OP = [
    ["OPEX 항목 (조사표)", "성격", "연동 CAPEX (유발 자산)", "산정·비고"],
    ["수리유지비 — 영농시설", "유지보수", "① 영농시설 전체(구조·피복·보온·차광·베드)", "취득가 대비 연 1~3% 경험식, 노후시 증가"],
    ["수리유지비 — 대농기구", "유지보수", "③ 대농기구(운반·방제·관리)", "가동시간 비례, 소모부품 포함"],
    ["수도광열비 — 전기", "에너지", "② 복합환경제어·관수펌프·환기모터·센서·보광", "제어·양액·환기 가동 전력"],
    ["수도광열비 — 경유/가스", "에너지", "② 난방기", "난방부하(외기−목표온도)×효율, 계절 편중"],
    ["수도광열비 — 물", "에너지", "② 관수·관비장치", "관수량(급액−배액) 기반"],
    ["기타재료비", "소모성 자재", "④ 배지·양액원소재·피복필름", "당해 비용처리(감가상각 아님)"],
    ["소농구비", "소모성 기구", "④ 소농구", "1년 미만·소액 → 당해 비용"],
    ["임차료 — 대농기구/영농시설", "임차(소유 대안)", "①③ 자가 소유의 대체", "자가면 감가상각, 임차면 임차료 — 택1"],
    ["위탁영농비·고용노임", "노무", "(자산 무관 · 참고)", "CAPEX 자동화 수준↑ → 노무비↓ 상충관계"],
]
for ri, row in enumerate(OP):
    for ci, v in enumerate(row):
        cell = ws2.cell(ri+2, ci+1, v); cell.border = BORDER; cell.font = _f(9, ri == 0, "FFFFFF" if ri == 0 else C_INK)
        cell.alignment = LEF
        if ri == 0: cell.fill = _fill(C_HDR); cell.alignment = CEN
        elif ri % 2 == 0: cell.fill = _fill(C_SOFT)
ws2.merge_cells(start_row=len(OP)+3, start_column=1, end_row=len(OP)+3, end_column=4)
ws2.cell(len(OP)+3, 1, "※ 핵심: 스마트팜 CAPEX(제어·난방·관수 자동화)는 에너지·유지보수 OPEX를 유발하되, "
        "노무비는 절감한다. 투자 의사결정은 감가상각+연동 OPEX 증분 vs 노무·수율 편익으로 판단.").font = _f(9, False, "595959")

# ══ Sheet3: 내용연수 표준 & 계층 요약 ═══════════════════════════════════════
ws3 = wb.create_sheet("내용연수 표준·요약")
for i, w in enumerate([26, 14, 40]): ws3.column_dimensions[get_column_letter(i+1)].width = w
ws3.merge_cells("A1:C1")
ws3["A1"] = "자산군별 표준 내용연수(수명연한) & 계층 요약"
ws3["A1"].font = _f(13, True, "FFFFFF"); ws3["A1"].fill = _fill(C_TITLE); ws3["A1"].alignment = CEN
LIFE = [
    ["자산군", "내용연수(년)", "근거·비고"],
    ["유리/경질판 온실", "15~20", "법인세법 시행규칙 별표(건물·구축물)"],
    ["비닐온실(철골)", "10~15", "내재해형 기준, 골조 위주"],
    ["피복필름(PO·비닐)", "1~3", "★소모성 — 자산화 여부 회계기준 확인"],
    ["보온·차광 스크린", "5~7", "개폐 반복 마모"],
    ["복합환경제어 시스템", "7~10", "전자설비, SW 업데이트 별도"],
    ["관수·관비장치(양액기)", "7~10", "펌프·밸브 소모부품 별도"],
    ["난방기", "8~10", "농진청 농업기계 내용연수"],
    ["CO2 발생·환기 설비", "8~10", "기계·전자 혼합"],
    ["환경 센서류", "5", "교정·전극 소모"],
    ["대농기구(운반·방제)", "5~8", "농진청 농업기계 기준"],
]
for ri, row in enumerate(LIFE):
    for ci, v in enumerate(row):
        cell = ws3.cell(ri+2, ci+1, v); cell.border = BORDER; cell.font = _f(9, ri == 0, "FFFFFF" if ri == 0 else C_INK)
        cell.alignment = CEN if ci == 1 else LEF
        if ri == 0: cell.fill = _fill(C_HDR); cell.alignment = CEN
        elif ri % 2 == 0: cell.fill = _fill(C_SOFT)
base = len(LIFE) + 4
ws3.merge_cells(start_row=base, start_column=1, end_row=base, end_column=3)
ws3.cell(base, 1, "계층 구조 요약").font = _f(11, True, C_TITLE)
SUMM = [
    "대분류 3(+소모성) : ① 영농시설  ② 환경관리 기자재  ③ 대농기구  (④ 소모성=당해비용)",
    "중분류 : 구조·피복·보온·차광·베드 / 제어·관수·난방·CO2·환기·센서 / 운반·방제·관리",
    "속성 : 업체(제조사) · 성능·사양 · 취득가액 · 내용연수 · 잔존율 · 연 감가상각(정액) · 연동 OPEX",
    "정액 감가상각 = 취득가액 × (1 − 잔존율) ÷ 내용연수  (잔존율 표준 10%)",
    "조사표 대조 : 대농구 675,000 + 영농시설 783,000 = 1,458,000원 (900㎡, 10a당 16,200원)",
    "OPEX 연동 : 시설→수리유지·임차, 제어/관수/난방→수도광열, 소모성→기타재료·소농구",
]
for i, s in enumerate(SUMM):
    ws3.cell(base+1+i, 1, "• " + s).font = _f(9)
    ws3.merge_cells(start_row=base+1+i, start_column=1, end_row=base+1+i, end_column=3)

# ══ Sheet4: 작목별 시설 구성 비교 (실 데이터) ═══════════════════════════════
ws4 = wb.create_sheet("작목별 시설 구성")
crops = list(CROP_FACILITY.keys())[1:]
ncol = 1 + len(crops)
for i in range(ncol): ws4.column_dimensions[get_column_letter(i+1)].width = 18 if i == 0 else 16
ws4.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
ws4["A1"] = "작목별 스마트팜 시설 구성 (조사표 '농가' 시트 제어현황 · 실 데이터)"
ws4["A1"].font = _f(13, True, "FFFFFF"); ws4["A1"].fill = _fill(C_TITLE); ws4["A1"].alignment = CEN
ws4.row_dimensions[1].height = 24
ws4.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncol)
ws4["A2"] = "★ CAPEX 실 차이는 여기서 온다 — ○설치 자산만 취득가·감가상각 대상. 참외는 보온·차광·관수 미설치/고장으로 최소 CAPEX, 딸기가 최다."
ws4["A2"].font = _f(8, False, "595959"); ws4["A2"].alignment = LEF; ws4.row_dimensions[2].height = 24
# 헤더
hr4 = 3
ws4.cell(hr4, 1, "환경관리 시설 항목").font = _f(9, True, "FFFFFF"); ws4.cell(hr4, 1).fill = _fill(C_HDR); ws4.cell(hr4, 1).alignment = CEN; ws4.cell(hr4, 1).border = BORDER
for j, c in enumerate(crops):
    cell = ws4.cell(hr4, j+2, c); cell.font = _f(9, True, "FFFFFF"); cell.fill = _fill(C_HDR); cell.alignment = CEN; cell.border = BORDER
# 항목 행
for i, name in enumerate(CROP_FACILITY["항목"]):
    rr = hr4 + 1 + i
    ic = ws4.cell(rr, 1, name); ic.font = _f(9, True); ic.alignment = LEF; ic.border = BORDER; ic.fill = _fill(C_SOFT)
    for j, c in enumerate(crops):
        v = CROP_FACILITY[c][i]
        cell = ws4.cell(rr, j+2, v); cell.border = BORDER; cell.alignment = CEN
        cell.font = _f(11, True, "2F9A62" if v == "○" else ("A6431E" if v == "고장" else "B0B0B0"))
# 메타 행
base4 = hr4 + 1 + len(CROP_FACILITY["항목"])
for k, lbl in enumerate(["재배유형", "난방에너지원", "생산량(kg)"]):
    rr = base4 + k
    ws4.cell(rr, 1, lbl).font = _f(9, True, C_TITLE); ws4.cell(rr, 1).alignment = LEF; ws4.cell(rr, 1).border = BORDER; ws4.cell(rr, 1).fill = _fill(C_L1)
    for j, c in enumerate(crops):
        cell = ws4.cell(rr, j+2, CROP_META[c][k]); cell.font = _f(9); cell.alignment = CEN; cell.border = BORDER
# 해설
ws4.merge_cells(start_row=base4+4, start_column=1, end_row=base4+4, end_column=ncol)
ws4.cell(base4+4, 1, "※ 설치된 시설(○)만 CAPEX 등록부에 취득가·내용연수를 입력해 감가상각을 계산한다. "
         "'고장'은 재투자(교체 CAPEX) 또는 수리(OPEX) 의사결정 대상. 작목별 감가상각 총액은 시설 구성 차이만큼 달라진다.").font = _f(9, False, "595959")

OUT.parent.mkdir(exist_ok=True)
wb.save(OUT)
print(f"저장: {OUT}")
