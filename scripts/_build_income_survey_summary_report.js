// 소득조사표 개선 — 종합 보고서(docx). 현황·문제점·개선점(통합) + 품목별 실측 대조 + 활용·한계.
// 근거: 20농가 실측. 아티팩트/엑셀/발주처 docx와 동일 기준.
// 실행: NODE_PATH="C:/smart_farm/node_modules" node scripts/_build_income_survey_summary_report.js
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType, PageNumber, Footer, Header,
} = require('docx');

const FONT = '맑은 고딕';
const GREEN = '1F7A4D', CLAY = '9C6A2E', WARN = 'B0472E', INK = '1B211D', SOFT = '55605A';
const GREEN_BG = 'E3EFE7', CLAY_BG = 'F2E8D6', HEAD_BG = '123D2A', ZEBRA = 'F4F6F1';
const CW = 9360; // content width (US Letter, 1" margins)

const R = (t, o = {}) => new TextRun({ text: t, font: FONT, size: o.size || 20, bold: !!o.bold, italics: !!o.italics, color: o.color || INK });
const P = (runs, o = {}) => new Paragraph({ children: Array.isArray(runs) ? runs : [runs], spacing: { after: o.after != null ? o.after : 120, before: o.before || 0, line: 276 }, alignment: o.align, ...(o.bullet ? { bullet: { level: 0 } } : {}) });
const H = (t, lvl = HeadingLevel.HEADING_1) => new Paragraph({ heading: lvl, spacing: { before: 280, after: 140 }, children: [new TextRun({ text: t, font: FONT, bold: true, size: lvl === HeadingLevel.HEADING_1 ? 30 : 24, color: lvl === HeadingLevel.HEADING_1 ? GREEN : INK })] });

const B = { style: BorderStyle.SINGLE, size: 4, color: 'D6DCD2' };
const BORDERS = { top: B, bottom: B, left: B, right: B, insideHorizontal: B, insideVertical: B };
function cell(content, o = {}) {
  const runs = (Array.isArray(content) ? content : [content]).map(c => typeof c === 'string' ? R(c, o) : c);
  return new TableCell({
    width: { size: o.w || 2000, type: WidthType.DXA },
    shading: o.bg ? { fill: o.bg, type: ShadingType.CLEAR, color: 'auto' } : undefined,
    margins: { top: 60, bottom: 60, left: 110, right: 110 },
    verticalAlign: 'center',
    children: [new Paragraph({ alignment: o.align || AlignmentType.LEFT, spacing: { after: 0, line: 250 }, children: runs })],
  });
}
const hcell = (t, w, al) => cell(t, { w, bg: HEAD_BG, color: 'FFFFFF', bold: true, align: al || AlignmentType.CENTER });
function table(widths, rows) {
  return new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: widths, borders: BORDERS, rows });
}

// ── 데이터 ──
const PROBS = [
  ['1', 'CAPEX가 집계 상각비 2줄뿐', '소득분석2 R21~23', '자산별 취득가·업체·성능·수명 추적 불가'],
  ['2', '샘플 템플릿이 실데이터처럼 존재', '‘홍길동’·4작목 675k/783k 동일', '실 투자비가 아님'],
  ['3', '분류가 2종(대농구·영농시설)뿐', '복합제어·양액기·센서 혼재', '스마트팜 자동화 설비 미반영'],
  ['4', '감가상각 근거가 소득분석에 미표기', '농가시트엔 신조가·내용연수 실입력, 소득분석은 집계만', '자산별 재계산·검증이 분석단에서 불가'],
  ['5', 'OPEX↔CAPEX 연동 단절', '수리유지·수도광열 대부분 0', '투자→운영비 파급 분석 불가'],
  ['6', '시설이 정성 코드로만', '‘농가’ 시설현황 ○/✕·취득가 결측', '정량 투자비 산출 불가'],
  ['7', '작목별 시설차이 미반영', '실측 완비도 0.71~0.94인데 상각비 4작목 동일', '작목 CAPEX 차이가 소득에 안 잡힘'],
];
const IMPS = [
  ['3계층 자산등록부', '대분류(영농시설/기자재/대농기구) > 중분류 > 세부품목', '#1·#3'],
  ['자산별 11속성 + 정액감가상각 수식', '업체·성능·사양·취득가·내용연수·잔존율·감가상각', '#1·#4·#6'],
  ['표준 내용연수 명시', '법인세법 별표·농진청(온실15~20·스크린5~7·제어/관수7~10·센서5)', '#4'],
  ['OPEX↔CAPEX 연동 매트릭스', '수리유지→시설/대농기구 · 수도광열→제어·난방·관수', '#5'],
  ['작목별 시설구성 실데이터', '○설치 자산만 감가대상 · 작목 차등', '#7'],
  ['비용모델·ERP 자동연동', 'register 취득가 → 감가상각·수리유지 자동 → 소득구조 반영', '#4·#5'],
  ['정직성 표기', '견적 입력 전엔 source=template로 명시', '#2'],
];
// 품목별 매트릭스: 라벨 + [딸기,방울,완숙,참외]
const MATRIX = [
  ['시설 완비도 (5농가 평균)', ['0.934', '0.910', '0.940', '0.712'], true],
  ['완비도 범위 (농가 편차)', ['0.91–0.97', '0.76–0.97', '0.76–1.00', '0.67–0.75'], false],
  ['평균 생산량 (kg)', ['30,448', '78,344', '164,314', '78,768'], false],
  ['생산량 범위 (kg)', ['12k–59.5k', '58k–112k', '50k–450k', '39k–120k'], false],
  ['이전 감가 (템플릿)', ['1,458,000', '1,458,000', '1,458,000', '1,458,000'], false],
  ['이후 감가 (실측)', ['1,361,772', '1,326,780', '1,370,520', '1,038,096'], true],
  ['월 감가 (원/㎡)', ['126.1', '122.9', '126.9', '96.1'], false],
];
const CROPS = [
  ['🍓 딸기 — 완비·노동집약', '완비 시설이 템플릿에 안 잡힘 → 자산별 분해로 보온 투자·감가 명시. 계수 0.934, 편차 작음(표준화). 활용: 관리 자동화(유인·적엽) ROI를 실감가+노무절감으로 대조.'],
  ['🍅 방울토마토 — 다수확·측면보온 공백', '다수확·측면보온 부재 미반영 → 표본 측면보온만 ✕로 공백 노출. 계수 0.910, 완비도 편차 최대(0.76~0.97). 활용: 측면보온 신규투자 시뮬레이션(추가 감가 vs 난방 절감), 자동 선별·포장 검토.'],
  ['🍅 완숙토마토 — 최다 생산·대부분 완비 (정정)', '표본농가는 측창·관수관비 ✕였으나 5농가 평균 0.940 = 대부분 완비. 초기 단일샘플 “자동화 공백 최대” 판단을 실측이 정정 — 공백은 완숙 전반이 아니라 농가 편차. 활용: 시설 미비 개별 농가에 한해 자동화 ROI 제안.'],
  ['🍈 참외 — 반촉성·저투자', '딸기와 동일 투자비로 잡혀 소득 왜곡 → 계수 0.712, 감가 최소(−24%)로 저CAPEX 실측 확인. 관수관비 고장. 활용: 재투자(교체 CAPEX) vs 수리(OPEX) 갈림길, 신규진입 저CAPEX 표준 모델.'],
];
const ROAD = [
  ['견적 연동 자동화', 'C16 업로드 견적서·시방서에서 취득가·업체·사양 추출 → register 자동 채움'],
  ['투자 ROI 시뮬레이션', '신규 CAPEX(연 감가+유발 OPEX) vs 노무·수율·품질 편익'],
  ['재투자·교체 알림', '내용연수 만료·‘고장’ 자산을 재투자 vs 수리로 구분'],
  ['표준 CAPEX 벤치마크', '20개소 견적 축적 → 작목·규모·지역별 투자·감가 표준'],
  ['소득 모델 정합', 'stage3·4 소득 검증에 실 감가·수리유지 반영(flat 고정비 대체)'],
  ['정책·보조사업 근거', 'ROI·감가 구조 표준화로 심사·다년 손익분기 자료'],
];

const body = [];
// 표지 제목
body.push(new Paragraph({ spacing: { after: 60, before: 200 }, children: [new TextRun({ text: 'KAASA Farmingsight · 발주처 검토자료', font: FONT, size: 18, bold: true, color: GREEN })] }));
body.push(new Paragraph({ spacing: { after: 80 }, children: [new TextRun({ text: '소득조사표 CAPEX/OPEX 체계화', font: FONT, size: 40, bold: true, color: INK })] }));
body.push(new Paragraph({ spacing: { after: 200 }, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: GREEN, space: 8 } }, children: [new TextRun({ text: '현황 · 문제점 · 개선점 종합 보고서 (통합 + 품목별)', font: FONT, size: 26, bold: true, color: SOFT })] }));
body.push(P([R('근거: ', { bold: true, color: SOFT }), R('농진청 소득조사표 4작목 · 20농가 실측(작목당 5) · 각 900㎡ · 2026-08-05', { color: SOFT })], { after: 40 }));
body.push(P([R('연동: ', { bold: true, color: SOFT }), R('capex_cost.py → m4_cost → ERP /costs · 산출물 정합(아티팩트·엑셀·docx 동일 실측 기준)', { color: SOFT })], { after: 240 }));

// 1 개요
body.push(H('1. 개요'));
body.push(P('현행 소득조사표는 투자비(CAPEX)를 “상각비 2줄”로만 담아, 무엇을·얼마에·몇 년 쓰는 자산인지 추적할 수 없다. 본 보고서는 조사 과정에서 실제로 확인한 7대 현안과, 이를 3계층 자산등록부·정액감가상각 수식·OPEX 연동으로 구조화하고 비용모델·ERP에 자동 연결한 개선안을 통합·품목별로 대조한다. 계수·생산량은 작목별 5농가(총 20) 실측 평균이다.'));

// 2 현황
body.push(H('2. 현행 소득조사표 현황'));
body.push(P([R('상각비 2줄로 압축 — ', { bold: true }), R('소득분석2 = 대농구 675,000 + 영농시설 783,000. 이 값은 이름 “홍길동”·4작목 완전 동일 샘플 템플릿이며, 실제 차이(생산량·시설유무)는 ‘농가’ 시트에 정성 코드(○/✕)로만 흩어져 있다.')]));

// 3 문제점
body.push(H('3. 문제점 — 7대 현안'));
body.push(table([620, 3000, 2740, 3000], [
  new TableRow({ tableHeader: true, children: [hcell('#', 620), hcell('현안', 3000, AlignmentType.LEFT), hcell('근거(조사표)', 2740, AlignmentType.LEFT), hcell('영향', 3000, AlignmentType.LEFT)] }),
  ...PROBS.map(([n, a, e, i], idx) => new TableRow({ children: [
    cell(n, { w: 620, bold: true, color: CLAY, align: AlignmentType.CENTER, bg: idx % 2 ? ZEBRA : undefined }),
    cell(a, { w: 3000, bold: true, bg: idx % 2 ? ZEBRA : undefined }),
    cell(e, { w: 2740, color: SOFT, size: 18, bg: idx % 2 ? ZEBRA : undefined }),
    cell(i, { w: 3000, color: SOFT, size: 18, bg: idx % 2 ? ZEBRA : undefined }),
  ] })),
]));

// 4 개선점
body.push(H('4. 개선 방향 — 3계층 자산등록부 + 연동 (구축 완료)'));
body.push(table([3300, 4560, 1500], [
  new TableRow({ tableHeader: true, children: [hcell('개선', 3300, AlignmentType.LEFT), hcell('내용', 4560, AlignmentType.LEFT), hcell('해소 현안', 1500)] }),
  ...IMPS.map(([t, d, s], idx) => new TableRow({ children: [
    cell(t, { w: 3300, bold: true, bg: idx % 2 ? ZEBRA : undefined }),
    cell(d, { w: 4560, color: SOFT, size: 18, bg: idx % 2 ? ZEBRA : undefined }),
    cell(s, { w: 1500, bold: true, color: GREEN, align: AlignmentType.CENTER, bg: GREEN_BG }),
  ] })),
]));
body.push(P([R('핵심 전환:  ', { bold: true, color: GREEN }), R('“영농시설 상각비 783,000”(한 줄)  →  자산별 분해 + 「취득가×(1−잔존율)÷수명」 수식', { color: INK })], { before: 120 }));

// 5 품목별
body.push(H('5. 품목별 실측 대조 (20농가)'));
body.push(P([R('계수·생산량·범위 = 작목별 5농가 실측 평균 · 이후 감가 = 템플릿 1,458,000 × 완비도계수 · 월 감가 = 감가 ÷ 900㎡ ÷ 12', { italics: true, color: SOFT, size: 17 })], { after: 100 }));
const cropCols = ['🍓 딸기', '🍅 방울', '🍅 완숙', '🍈 참외'];
body.push(table([2760, 1650, 1650, 1650, 1650], [
  new TableRow({ tableHeader: true, children: [hcell('항목', 2760, AlignmentType.LEFT), ...cropCols.map(c => hcell(c, 1650))] }),
  ...MATRIX.map(([label, vals, strong], idx) => new TableRow({ children: [
    cell(label, { w: 2760, bold: strong, color: strong ? INK : SOFT, size: strong ? 20 : 18, bg: strong ? GREEN_BG : (idx % 2 ? ZEBRA : undefined) }),
    ...vals.map((v, ci) => {
      const low = strong && ci === 3;
      return cell(v, { w: 1650, bold: strong, align: AlignmentType.CENTER, color: low ? WARN : (strong ? INK : SOFT), bg: strong ? (low ? 'F6E2DB' : GREEN_BG) : (idx % 2 ? ZEBRA : undefined) });
    }),
  ] })),
]));
body.push(P('', { after: 40 }));
CROPS.forEach(([name, story]) => {
  body.push(P([R(name, { bold: true, size: 21 })], { after: 30, before: 100 }));
  body.push(P([R(story, { color: SOFT, size: 19 })], { after: 60 }));
});

// 6 활용
body.push(H('6. 활용 로드맵'));
body.push(table([620, 3000, 5740], [
  new TableRow({ tableHeader: true, children: [hcell('#', 620), hcell('과제', 3000, AlignmentType.LEFT), hcell('내용', 5740, AlignmentType.LEFT)] }),
  ...ROAD.map(([t, d], idx) => new TableRow({ children: [
    cell(String(idx + 1), { w: 620, bold: true, color: GREEN, align: AlignmentType.CENTER, bg: idx % 2 ? ZEBRA : undefined }),
    cell(t, { w: 3000, bold: true, bg: idx % 2 ? ZEBRA : undefined }),
    cell(d, { w: 5740, color: SOFT, size: 18, bg: idx % 2 ? ZEBRA : undefined }),
  ] })),
]));

// 7 선행조건·한계
body.push(H('7. 선행조건 및 한계 (정직성)'));
body.push(new Paragraph({
  spacing: { after: 120, line: 276 },
  shading: { fill: CLAY_BG, type: ShadingType.CLEAR, color: 'auto' },
  border: { top: { style: BorderStyle.SINGLE, size: 2, color: 'E4D3B4' }, bottom: { style: BorderStyle.SINGLE, size: 2, color: 'E4D3B4' }, left: { style: BorderStyle.SINGLE, size: 12, color: CLAY }, right: { style: BorderStyle.SINGLE, size: 2, color: 'E4D3B4' } },
  children: [R('생산량·시설구성·자산별 취득가(신조가격)·내용연수·사양은 조사표 ‘농가’ 시트에 실입력돼 있다(20농가 251자산 확인). 다만 업체(제조사)는 조사표에 거의 미기재로, 과업①에서 견적서·시방서를 조사항목에 포함하면 업체·단가 결측이 해소된다.', { color: INK, size: 19 })],
}));

// 부록: 산출물
body.push(H('부록. 정합 산출물'));
[['종합 보고서(docx)', '본 문서 — 통합 현황·문제점·개선점 + 품목별 + 활용'],
 ['한눈 비교(아티팩트)', '웹 대조 페이지 — 통합·품목별 게이지·before/after'],
 ['개선 정리(xlsx)', '3시트 — 현황·문제점·개선점 / 품목별 실측 대조 / 로드맵·선행조건'],
 ['CAPEX/OPEX 체계화(xlsx)', '자산등록부·OPEX연동·내용연수·작목별 시설구성'],
 ['시설계수·생산량 실측(xlsx)', '20농가 데이터셋 + 작목별 계수'],
].forEach(([a, b2]) => body.push(P([R('· ', { color: GREEN, bold: true }), R(a + ' — ', { bold: true }), R(b2, { color: SOFT })], { after: 40 })));

const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: 20 } } } },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: 'KAASA Farmingsight · 소득조사표 CAPEX/OPEX 체계화 종합보고서 · ', font: FONT, size: 15, color: SOFT }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 15, color: SOFT })] })] }) },
    children: body,
  }],
});

const OUT = 'C:/smart_farm/out/소득조사표_개선_종합보고서.docx';
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log(`저장: ${OUT} (${buf.length.toLocaleString()} bytes)`); });
