/* 소득조사표 현행 vs 개선 — 발주처 제출용 상세보고서 (.docx)
 *
 * 근거: docs/소득조사표_현행_개선_대조.md · docs/소득조사표_품목별_개선_활용.md
 *       (농진청 소득조사표 4작목 실데이터 + CAPEX/OPEX 체계화·비용모델 연동)
 * 산출: out/소득조사표_현행_개선_발주처보고서.docx
 * 사용: NODE_PATH="C:/smart_farm/node_modules" node scripts/_build_income_survey_report.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  LevelFormat, Footer, PageNumber, PageBreak, VerticalAlign, ImageRun,
} = require('docx');

const ROOT = path.join(__dirname, '..');
// 20농가 실 자산등록부 (scripts/_extract_asset_register.py 산출) — 취득가·내용연수·사양 실측
let REG = { crops: {} };
try { REG = require(path.join(ROOT, 'out', 'asset_register.json')); } catch (e) { console.warn('asset_register.json 없음 — 실측 섹션 생략'); }
const OUT = path.join(ROOT, 'out', '소득조사표_현행_개선_발주처보고서.docx');
const LOGO = path.join(ROOT, 'assets', 'kaasa_logo.png');
const A4 = { width: 11906, height: 16838 };
const MARGIN = 1134;
const W = A4.width - MARGIN * 2;
const FONT = '맑은 고딕';
const bd = { style: BorderStyle.SINGLE, size: 1, color: 'BFBFBF' };
const BORDERS = { top: bd, bottom: bd, left: bd, right: bd };
const CELL_M = { top: 60, bottom: 60, left: 100, right: 100 };
const HEAD_FILL = 'DCE6F1';
const NEW_FILL = 'E4EDE4';   // 개선 강조
const OLD_FILL = 'F3E9D4';   // 현행

const P = (t, o = {}) => new Paragraph({
  spacing: { after: o.after ?? 100, line: 300 }, alignment: o.align,
  children: [new TextRun({ text: t, bold: o.bold, size: o.size ?? 20, color: o.color, font: FONT })],
});
const H = (t, lv) => new Paragraph({
  heading: lv, spacing: { before: lv === HeadingLevel.HEADING_1 ? 320 : 220, after: 150 },
  pageBreakBefore: lv === HeadingLevel.HEADING_1,
  children: [new TextRun({ text: t, font: FONT })],
});
const B = (t, lv = 0) => new Paragraph({
  numbering: { reference: 'b', level: lv }, spacing: { after: 70, line: 300 },
  children: [new TextRun({ text: t, size: 20, font: FONT })],
});
const cell = (t, { head = false, w, align, fill, color, bold } = {}) => new TableCell({
  borders: BORDERS, margins: CELL_M, verticalAlign: VerticalAlign.CENTER,
  width: { size: w, type: WidthType.DXA },
  shading: (head || fill) ? { fill: head ? HEAD_FILL : fill, type: ShadingType.CLEAR } : undefined,
  children: String(t).split('\n').map((line) => new Paragraph({
    alignment: align ?? (head ? AlignmentType.CENTER : AlignmentType.LEFT),
    children: [new TextRun({ text: line, bold: bold || head, size: 18, font: FONT, color })],
  })),
});
const TBL = (widths, rows, aligns, fills) => new Table({
  width: { size: W, type: WidthType.DXA }, columnWidths: widths,
  rows: rows.map((r, ri) => new TableRow({
    tableHeader: ri === 0,
    children: r.map((c, ci) => cell(typeof c === 'object' ? c.t : c, {
      head: ri === 0, w: widths[ci], align: aligns?.[ci],
      fill: (typeof c === 'object' ? c.fill : (fills ? fills[ci] : null)),
      color: (typeof c === 'object' ? c.color : null), bold: (typeof c === 'object' ? c.bold : false),
    })),
  })),
});
const CAP = (t) => new Paragraph({
  spacing: { before: 70, after: 200 }, alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: t, size: 17, color: '595959', font: FONT })],
});
let TN = 0; const T = (t) => CAP(`표 ${++TN}. ${t}`);
// 강조 상자 — 핵심 요약·실무 예시용 (좌측 녹색 바 + 연녹 배경). \n = 줄바꿈.
const BOX = (t, o = {}) => {
  const lines = String(t).split('\n');
  const runs = o.label ? [new TextRun({ text: o.label + '  ', bold: true, size: 19, color: '1C5A3A', font: FONT })] : [];
  lines.forEach((ln, i) => runs.push(new TextRun({ text: ln, size: 19, color: '1B211D', font: FONT, break: i > 0 ? 1 : undefined })));
  return new Paragraph({
    spacing: { before: o.before ?? 120, after: o.after ?? 160, line: 300 },
    shading: { fill: o.fill ?? 'EFF5EF', type: ShadingType.CLEAR },
    border: {
      top: { style: BorderStyle.SINGLE, size: 2, color: 'C7DECF', space: 6 },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: 'C7DECF', space: 6 },
      left: { style: BorderStyle.SINGLE, size: 18, color: '2F9A62', space: 8 },
      right: { style: BorderStyle.SINGLE, size: 2, color: 'C7DECF', space: 6 },
    },
    children: runs,
  });
};
const logoPara = (w = 190) => (!fs.existsSync(LOGO) ? [] : [new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { after: 240 },
  children: [new ImageRun({ type: 'png', data: fs.readFileSync(LOGO),
    transformation: { width: w, height: Math.round(w * 261 / 588) },
    altText: { title: 'KAASA', name: 'KAASA 로고', description: '한국스마트농업AI협회' } })],
})]);

// ── 표지 ─────────────────────────────────────────────────────────────────────
const cover = [
  new Paragraph({ spacing: { before: 560 } }),
  ...logoPara(190),
  new Paragraph({ spacing: { before: 60, after: 100 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '스마트팜 소득조사표', bold: true, size: 36, font: FONT })] }),
  new Paragraph({ spacing: { after: 120 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '현행 현안 · 개선 방향 · 품목별 활용방안', bold: true, size: 28, font: FONT })] }),
  new Paragraph({ spacing: { after: 560 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '— CAPEX(투자비) 체계화·계층화 및 감가상각·OPEX 연동 —', size: 21, color: '595959', font: FONT })] }),
  TBL([3200, 6438], [
    ['구 분', '내 용'],
    ['목적', '소득조사표 CAPEX/OPEX 구조 개선 방향 및 품목별 활용방안 제시'],
    ['대상 작목', '딸기·방울토마토·완숙토마토·참외 (스마트팜 각 900㎡)'],
    ['근거', '농진청 스마트팜 소득조사표 4작목 실데이터'],
    ['공동연구기관', '(주)이암허브 · 한국스마트농업AI협회'],
    ['작성일', '2026-08-05'],
  ]),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: '목  차', bold: true, size: 28, font: FONT })] }),
  TBL([1600, 8038], [
    ['장', '내용'],
    ['제1장', '개요 — 배경·목적, CAPEX/OPEX 핵심 개념, 보고서 구성'],
    ['제2장', '현행 소득조사표 현안 — 7대 현안과 근본 원인'],
    ['제3장', '개선 방향 — 3계층 자산등록부·감가상각 수식·OPEX 연동'],
    ['제4장', '품목별 이전 vs 이후 — 딸기·방울·완숙·참외'],
    ['제5장', '실 자산등록부 (20농가 실측) — 작목별 CAPEX·대표자산 사양'],
    ['제6장', '종합 및 활용방안 — 활용 6과제·선행 조건'],
  ], [AlignmentType.CENTER, AlignmentType.LEFT]),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── 제1장 개요 ───────────────────────────────────────────────────────────────
const ch1 = [
  H('제1장  개요', HeadingLevel.HEADING_1),
  BOX('현행 스마트팜 소득조사표는 투자비(CAPEX)를 "상각비 두 줄"로만 담아 자산을 추적할 수 없다. 본 보고서는 4작목·20농가 실데이터로 현안 7가지를 규명하고, 자산을 3계층으로 분해해 감가상각을 수식화하며 운영비(OPEX)와 연결하는 개선안을 제시한다. 개선안은 비용모델·ERP에 이미 연동돼 있으며, 농가별 투자비는 조사표 "농가" 시트에 실입력된 취득가·내용연수·사양으로 산출한다.', { label: '핵심 요약' }),
  H('제1절  배경과 목적', HeadingLevel.HEADING_2),
  P('스마트팜은 온실·복합환경제어기·양액기·난방기 등 고가 설비에 대한 투자(CAPEX)가 경영의 핵심이다. 그러나 현행 소득조사표는 이 투자비를 대농구·영농시설 "상각비 두 줄"로만 담고 있어, 무엇을 얼마에 몇 년 동안 사용하는 자산인지, 어느 업체의 어떤 사양인지 추적할 수 없다. 투자 대비 성과(ROI)를 따지거나 재투자 시점을 판단할 근거가 조사표 안에 남지 않는 것이다.', { after: 120 }),
  P('본 보고서는 농진청 스마트팜 소득조사표 4작목(딸기·방울토마토·완숙토마토·참외), 각 작목 5농가씩 총 20농가의 실데이터를 분석하여 현행 현안을 규명하고, 3계층 자산등록부에 기반한 개선 방향과 품목별 활용방안을 제시한다.', { after: 130 }),
  H('제2절  핵심 개념 — CAPEX와 OPEX', HeadingLevel.HEADING_2),
  P('CAPEX(자본적 지출·투자비)는 온실·환경제어기·트랙터처럼 여러 해에 걸쳐 사용하는 자산을 사는 비용이다. 이 비용은 산 해에 전부 잡지 않고 "감가상각"으로 사용 연수에 나누어 매년 비용으로 반영한다. 반면 OPEX(운영비)는 전기·연료·수리·인건비처럼 그 해에 소모되는 비용이다.', { after: 120 }),
  BOX('연 감가상각 = 취득가액 × (1 − 잔존율) ÷ 내용연수.  예) 온실 구조를 1,200만원에 짓고 12년 사용, 잔존가치 10%면 → 1,200만 × 0.9 ÷ 12 = 90만원/년. 이렇게 자산마다 "취득가·내용연수·잔존율"이 있어야 감가상각을 계산·검증할 수 있다.', { label: '예시(감가상각)' }),
  P('두 비용은 서로 연결돼 있다. 자동화 설비(CAPEX)를 늘리면 전기·연료·수리 같은 운영비(OPEX)는 늘지만 인건비(OPEX)는 줄어든다. 따라서 투자 판단은 "감가상각 + 늘어나는 운영비"와 "줄어드는 인건비·높아지는 수율·품질"을 함께 견주어야 한다. 본 보고서의 개선안은 이 연결을 구조로 담는다.', { after: 130 }),
  H('제3절  보고서 구성', HeadingLevel.HEADING_2),
  P('제2장은 현행 조사표의 현안 7가지와 근본 원인을, 제3장은 개선 방향(3계층 등록부·감가상각 수식·OPEX 연동)을, 제4장은 품목별 이전 vs 이후를, 제5장은 20농가에서 추출한 실 자산등록부를, 제6장은 종합 및 활용방안을 다룬다.', { after: 120 }),
  P('★ 분석 과정에서 확인한 중요 사실 두 가지 — (1) 조사표의 집계 상각비(대농구 675,000 + 영농시설 783,000)와 성명 "홍길동"은 4작목이 완전히 동일한 샘플 템플릿이며 실 농가 투자비가 아니다. (2) 반면 조사표 "농가" 시트에는 자산별 취득가·내용연수·사양이 실제로 입력돼 있어, 이를 추출하면 농가별 실 투자비를 산출할 수 있다(제5장).', { bold: true, after: 130 }),
];

// ── 제2장 현안 ───────────────────────────────────────────────────────────────
const ch2 = [
  H('제2장  현행 소득조사표 현안', HeadingLevel.HEADING_1),
  P('소득조사표는 크게 두 부분으로 나뉜다. "소득분석" 시트는 소득을 계산하는 요약표이고, "농가" 시트는 농가가 실제로 입력하는 원자료다. 문제의 뿌리는, 소득 계산에 쓰이는 요약표가 투자비를 상각비 두 줄로만 축약해 버려 원자료의 자산 상세가 소득·투자 분석으로 이어지지 못한다는 데 있다.', { after: 120 }),
  P('아래는 소득조사표에서 실제 확인한 7대 현안이다. "근거"는 조사표의 어느 부분에서 확인했는지, "영향"은 그 현안이 투자·소득 분석에 어떤 문제를 일으키는지를 나타낸다.', { after: 130 }),
  TBL([600, 2600, 3400, 3038], [
    ['#', '현안', '근거 (조사표)', '영향'],
    ['1', '소득분석 반영이 집계 상각비 2줄뿐', '소득분석2: 대농구 675,000 + 영농시설 783,000(템플릿)', '원자료(농가 시트)의 자산별 취득가·사양이 분석·모델로 미연계, 업체 결측 → 투자 분석 불가'],
    ['2', '샘플 템플릿이 실데이터처럼 존재', '이름 "홍길동", 4작목 상각비 값 완전 동일', '소득분석2 값은 실 농가 투자비 아님(원자료는 농가 시트)'],
    ['3', '분류가 2종(대농구/영농시설)뿐', '복합환경제어·양액기·센서·난방기 혼재', '스마트팜 자동화 설비 특성 미반영'],
    ['4', '감가상각 근거가 소득분석에 미표기', '농가 시트엔 신조가·내용연수 실입력, 소득분석은 집계 상각비만', '자산별 재계산·검증·재투자 판단이 분석단에서 불가'],
    ['5', 'OPEX↔CAPEX 연동 단절', '수리유지·수도광열·임차료 대부분 0, 매핑 없음', '투자→운영비 파급 분석 불가'],
    ['6', '시설이 정성 코드로만', '농가 시설현황이 코드값(○/×)만', '정량 투자비 산출 불가'],
    ['7', '작목별 시설차이 미반영', '참외=보온·차광·관수 미설치/고장인데 상각비는 동일', '작목별 CAPEX 차이가 소득에 안 잡힘'],
  ], [AlignmentType.CENTER, AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.LEFT]),
  T('현행 소득조사표 7대 현안'),
  BOX('현안의 근본 원인은 "자산을 하나하나 관리하는 등록부가 없다"는 한 가지로 모인다. 원자료(농가 시트)에는 취득가·내용연수·사양이 있지만, ① 자산별로 구조화돼 있지 않고 ② 소득 계산으로 이어지지 않으며 ③ 업체 정보와 ④ 운영비(OPEX) 연결이 빠져 있다. 다음 장의 개선안은 이 네 가지를 자산등록부 하나로 해소한다.', { label: '근본 원인' }),
];

// ── 제3장 개선 방향 ─────────────────────────────────────────────────────────
const ch3 = [
  H('제3장  개선 방향', HeadingLevel.HEADING_1),
  P('개선의 핵심은 세 가지다. 첫째, 자산을 "대분류 > 중분류 > 세부품목"의 3계층으로 나누고 각 자산에 업체·사양·취득가·내용연수·잔존율을 붙인다. 둘째, 감가상각을 하나의 수식으로 고정해 누구나 같은 방식으로 계산·검증하게 한다. 셋째, 각 자산이 유발하는 운영비(OPEX)를 연결한다. 이 세 가지는 이미 구축·연동을 마친 상태다.', { after: 120 }),
  BOX('연 감가상각 = 취득가액 × (1 − 잔존율) ÷ 내용연수.  예) 복합환경제어기 800만원·내용연수 8년·잔존율 10% → 800만 × 0.9 ÷ 8 = 90만원/년. 이 수식이 있으면 견적서만 입력해도 감가가 자동으로 계산·검증되고, 재투자·교체 판단의 근거가 남는다.', { label: '감가상각 수식' }),
  P('아래 표는 7가지 개선 항목과 그것이 해소하는 현안(제2장의 번호)을 짝지은 것이다.', { after: 130 }),
  TBL([600, 3400, 2800, 2838], [
    ['#', '개선', '산출물', '해소 현안'],
    ['1', '3계층 자산등록부 (대분류>중분류>세부품목)', 'CAPEX 계층 등록부', '#1·#3'],
    ['2', '자산별 속성 — 업체·성능·취득가·내용연수·잔존율·정액감가상각(수식)', '등록부 11열', '#1·#4·#6'],
    ['3', '표준 내용연수 명시 (법인세법 별표·농진청 농기계)', '내용연수 표준', '#4'],
    ['4', 'OPEX↔CAPEX 연동 매트릭스', '연동 매트릭스', '#5'],
    ['5', '작목별 시설구성 실데이터 (○설치만 감가 대상)', '작목별 시설 구성', '#7'],
    ['6', '비용모델·ERP 자동 연동 (감가상각·수리유지 자동 항목화)', 'capex_cost·m4_cost·ERP', '#4·#5'],
    ['7', '정직성 — 집계 상각비가 템플릿임을 명시(견적 입력 전 template 표기)', '전 산출물', '#2'],
  ], [AlignmentType.CENTER, AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.CENTER]),
  T('개선 방향과 현안 해소'),
  P('다음 표는 같은 항목이 현행과 개선에서 어떻게 달라지는지를 보여준다. 왼쪽(연한 갈색)이 현행, 오른쪽(연한 녹색)이 개선이다.', { after: 80 }),
  TBL([2600, 3400, 3638], [
    ['항목', '현행', '개선'],
    [{ t: '영농시설 투자', bold: true }, { t: '"영농시설 상각비 783,000" (한 줄)', fill: OLD_FILL }, { t: '온실구조·보온·차광 등 자산별 분해 (취득가·내용연수·정액감가)', fill: NEW_FILL }],
    [{ t: '감가상각 근거', bold: true }, { t: '(없음)', fill: OLD_FILL }, { t: '= 취득가액×(1−잔존율)÷내용연수 (수식)', fill: NEW_FILL }],
    [{ t: '작목 차이', bold: true }, { t: '딸기=방울=완숙=참외 동일', fill: OLD_FILL }, { t: '참외 96.1 vs 완숙 126.9 원/㎡·월 (5농가 실측 시설완비도 차등)', fill: NEW_FILL }],
    [{ t: '운영비 연결', bold: true }, { t: '(없음)', fill: OLD_FILL }, { t: '난방기→수도광열, 양액기→전기·물, 시설→수리유지', fill: NEW_FILL }],
    [{ t: '소득 반영', bold: true }, { t: '상각비 수기', fill: OLD_FILL }, { t: 'ERP /costs에 "감가상각·수리유지" 자동 항목화', fill: NEW_FILL }],
  ], [AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.LEFT]),
  T('현행 vs 개선 항목 대조'),
  P('요약하면, 개선 후에는 "영농시설 상각비 783,000원"이라는 한 줄이 온실구조·보온·차광 등 자산별로 분해되고, 각 자산의 감가상각이 운영비·소득 계산까지 자동으로 이어진다. 조사표에 실입력된 취득가·내용연수를 넣으면 이 흐름이 그대로 작동한다.', { after: 130 }),

  H('제3절  핵심 산식 정의', HeadingLevel.HEADING_2),
  P('개선안의 정량 지표는 두 개의 산식으로 계산한다. 첫째는 각 농가의 시설이 얼마나 완비됐는지를 0~1로 나타내는 "시설 완비도 계수"이고, 둘째는 자산별 "감가상각"이다.', { after: 100 }),
  P('1) 시설 완비도 계수', { bold: true, after: 60 }),
  BOX('계수 = 0.60 (온실구조 공통) + Σ ( 시설별 가중치 × 설치배수 )\n설치배수: 설치(○) = 1.0,  고장 = 0.5,  미설치(×) = 0.\n가중치 합은 0.40이므로 모든 시설을 갖추면 계수 = 1.00, 온실구조만 있으면 0.60이다.', { label: '산식' }),
  P('시설별 가중치는 스마트팜 자동화·보온 기여도를 반영해 다음과 같이 부여한다.', { after: 60 }),
  TBL([2400, 1400, 2400, 1400, 1638], [
    ['시설 항목', '가중치', '시설 항목', '가중치', '비고'],
    ['온실구조체(공통)', '0.60', '천정 보온스크린', '0.07', '설치배수'],
    ['일중천장', '0.03', '측면 보온스크린', '0.06', '○=1'],
    ['이중천장', '0.03', '차광 스크린', '0.06', '고장=0.5'],
    ['측창(환기)', '0.07', '관수·관비장치', '0.08', '×=0'],
    ['', '', '가중치 합', '1.00', '최대 계수'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.CENTER]),
  T('시설별 가중치 (합 1.00)'),
  BOX('딸기 표본농가(류창영)는 이중천장만 미설치이므로 →\n0.60 + 0.03(일중천장) + 0.07(측창) + 0.07(천정보온) + 0.06(측면보온) + 0.06(차광) + 0.08(관수) = 0.97.\n작목 대표 계수는 같은 산식을 5농가에 각각 적용한 평균이다(딸기 0.934 등).', { label: '계산 예시' }),
  P('2) 감가상각 (두 관례)', { bold: true, after: 60 }),
  BOX('ⓐ 조사표 실측 방식:  연 감가상각 = 취득가액 ÷ 내용연수\nⓑ 개선 표준 방식:  연 감가상각 = 취득가액 × (1 − 잔존율) ÷ 내용연수  (잔존율 표준 10%)\n예) 완숙 유리온실 36억·30년 → ⓐ 1.2억/년, ⓑ 1.08억/년. 제5장의 "평균 연감가"는 ⓐ, 서비스 ERP는 ⓑ를 쓴다.', { label: '산식' }),
  P('★ 개선 전략과 위 산식의 살아있는 계산 과정은 동봉한 엑셀 "소득조사표_개선_산식.xlsx"에 담았다. 3개 시트(① 시설완비도 계수 산식 · ② 감가상각 산식 · ③ 개선 전략·산식)에서 파랑 셀(설치배수·취득가·내용연수)을 바꾸면 계수·감가가 자동으로 재계산된다.', { after: 130 }),
];

// ── 제4장 품목별 ─────────────────────────────────────────────────────────────
const O = (t) => ({ t, fill: OLD_FILL }); const N = (t) => ({ t, fill: NEW_FILL });
const ch4 = [
  H('제4장  품목별 이전 vs 이후', HeadingLevel.HEADING_1),
  P('이전에는 4작목이 모두 동일한 템플릿 값(감가 1,458,000원)이었으나, 개선 후에는 조사표 "농가" 시트의 실 시설 구성으로 품목별 CAPEX를 차등한다. 아래 표의 "시설 완비도 계수"는 각 작목 5농가가 실제로 갖춘 시설의 완비 정도를 0~1로 나타낸 지표로, 값이 클수록 자동화·보온 설비가 잘 갖춰졌다는 뜻이다.', { after: 120 }),
  P('각 절은 "이전(현행 조사표) → 이후(개선) → 활용(현장 적용)" 순으로 읽으면 된다.', { after: 130 }),
  TBL([2200, 1859, 1859, 1859, 1859], [
    ['항목', '딸기', '방울토마토', '완숙토마토', '참외'],
    ['재배유형', '촉성', '촉성', '촉성', { t: '반촉성', bold: true }],
    ['생산량(kg/900㎡)', '23,516', '65,464', { t: '198,797', bold: true }, '50,000'],
    ['측창(환기)', '○', '○', { t: '✕', bold: true }, '○'],
    ['천정 보온스크린', '○', '○', '○', { t: '✕', bold: true }],
    ['측면 보온스크린', '○', { t: '✕', bold: true }, '✕', '✕'],
    ['차광스크린', '○', '○', '○', { t: '✕', bold: true }],
    ['관수·관비장치', '○', '○', { t: '✕', bold: true }, { t: '고장', bold: true, color: 'A6431E' }],
    [{ t: '시설 완비도 계수(5농가 실측)', bold: true }, { t: '0.934', bold: true }, '0.910', { t: '0.940', bold: true }, { t: '0.712', bold: true }],
    [{ t: '이전(조사표) 감가상각', bold: true }, O('1,458,000'), O('1,458,000'), O('1,458,000'), O('1,458,000')],
    [{ t: '이후 연 감가상각', bold: true }, N('1,361,772'), N('1,326,780'), N('1,370,520'), N('1,038,096')],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER]),
  T('품목별 시설 구성 및 감가상각 (○/✕는 표본농가 1곳, 계수·감가는 작목별 5농가 실측 평균)'),
  P('★ 시설 완비도 계수는 작목별 5농가(총 20농가) 소득조사표 실측 평균이다. 위 ○/✕는 각 작목 대표 표본농가 1곳의 구성이며, 완숙토마토는 표본농가(김선환)가 측창·관수관비를 갖추지 않았으나 5농가 평균 계수는 0.940으로 대부분 완비 — 자동화 편차가 농가별로 크다는 점에 유의한다.', { after: 130 }),

  H('제1절  딸기 (류창영) — 시설 완비·노동집약', HeadingLevel.HEADING_2),
  P('딸기는 저온에서 관리하고 수확을 손으로 하는 노동집약 작목이다. 5농가 완비도 편차가 0.91~0.97로 작아, 시설 구성이 비교적 표준화돼 있다.', { after: 80 }),
  B('이전 : 상각비 675,000+783,000(템플릿). 저온관리·수작업 수확·시설 완비 미반영.'),
  B('이후 : 표본농가 전 시설 ○, 5농가 실측 계수 0.934(감가 1,361,772). 저온기 보온 투자와 감가가 자산별로 명시.'),
  B('활용 : 노동집약 → 관리 자동화(유인·적엽) 투자 ROI를 감가+노무절감으로 대조. 측면보온 완비 → 난방절감 회수기간 검증.'),

  H('제2절  방울토마토 (박경종) — 다수확·측면보온 미설치', HeadingLevel.HEADING_2),
  P('방울토마토는 수확량이 많은 작목이다. 5농가 완비도 편차가 0.76~0.97로 4작목 중 가장 커, 농가별 시설 격차가 뚜렷하다.', { after: 80 }),
  B('이전 : 딸기와 동일 템플릿 → 다수확(65,464kg)·측면보온 부재 미반영.'),
  B('이후 : 표본농가는 측면 보온스크린만 ✕, 5농가 실측 계수 0.910(감가 1,326,780). 보온 투자 여지가 공백으로 노출.'),
  B('활용 : 측면보온 신규투자 시뮬레이션(추가 감가 vs 난방비 절감). 다수확 → 자동 선별·포장 검토.'),

  H('제3절  완숙토마토 (김선환) — 최다 생산량·대부분 완비', HeadingLevel.HEADING_2),
  P('완숙토마토는 4작목 중 생산량이 가장 많고 투자 규모도 가장 크다(대형 유리온실 다수). 5농가 대부분이 시설을 잘 갖췄으며, 표본농가(김선환)만 환기·관수가 수동인 예외 사례다.', { after: 80 }),
  B('이전 : 동일 템플릿 → 최다 생산량(198,797kg)·측창/관수 부재(수동 운영) 미반영.'),
  B('이후 : 표본농가(김선환)는 측창·관수관비 ✕이나, 5농가 실측 계수 0.940(감가 1,370,520)으로 대부분 완비 — 초기 단일샘플 판단(공백 최대)을 실측이 정정. 자동화 편차가 농가별로 크다.'),
  B('활용 : 최다 생산량(198,797kg)으로 규모 효과 큼. 5농가 중 시설 미비 농가(표본 김선환 등)에 한해 환기·관수 자동화 CAPEX(감가+전기) vs 노무·수율 ROI를 개별 제안 — 완숙 전반의 공백이 아니라 농가 편차 대응.'),

  H('제4절  참외 (강석구) — 반촉성·저투자·관수 고장', HeadingLevel.HEADING_2),
  P('참외는 반촉성(난방을 최소화하는 재배)·최소 시설 작목으로, 4작목 중 투자비가 가장 낮다. 완비도 0.67~0.75로 일관되게 낮아 저CAPEX 특성이 뚜렷하다.', { after: 80 }),
  B('이전 : 동일 템플릿(1,458,000) → 반촉성·최소 시설인 참외가 딸기와 같은 투자비로 잡혀 소득 왜곡.'),
  B('이후 : 표본농가는 보온·차광 없음·측창만 ○·관수관비 고장, 5농가 실측 계수 0.712(감가 1,038,096·최소). 4작목 중 유일하게 확연히 낮아 저CAPEX 특성이 실측으로 확인됨.'),
  B('활용 : 관수관비 "고장" → 재투자(교체) vs 수리(OPEX) 의사결정 최우선. 저투자·저비용 구조 → 신규 진입농가 표준 모델.'),
];

// ── 제5장 실 자산등록부 (20농가 실측) ───────────────────────────────────────
const _n = v => (v == null ? '' : Number(v).toLocaleString());
const CROP_ORDER = ['딸기', '방울토마토', '완숙토마토', '참외'];
const regRows = CROP_ORDER.map(c => {
  const d = REG.crops[c] || {};
  return [c, String(d.n_farms || 0), _n(d.capex_mean_krw), `${_n(d.capex_min)} ~ ${_n(d.capex_max)}`, _n(d.annual_deprec_mean)];
});
const sampleRows = CROP_ORDER.map(c => {
  const d = REG.crops[c] || {}; let best = null;
  (d.farms || []).forEach(fm => (fm.assets || []).forEach(a => {
    if (a.category === '영농시설' && (!best || a.acq_krw > best.acq_krw)) best = { ...a, farm: fm.farm };
  }));
  return best ? [c, best.asset, _n(best.acq_krw), String(best.life_yr || ''), best.spec || '—'] : [c, '—', '—', '—', '—'];
});
const A = AlignmentType;
const chReg = [
  H('제5장  실 자산등록부 (20농가 실측)', HeadingLevel.HEADING_1),
  P('★ 조사표 원자료 재검토 결과, "농가" 시트의 대농기구·영농시설 상세표에는 자산별 신조가격(취득가)·내용연수·사용년수·규격(사양)이 실제로 입력돼 있음을 확인하였다. 즉 취득가는 "미수집"이 아니라 "소득분석 집계로만 축약"된 것이며, 20농가 전체를 추출해 실 자산등록부(총 251개 자산)를 구축하였다. 다만 업체(제조사)는 조사표 ( )칸에 거의 미기재(사양 위주 약 45% 기입)로, 견적서 연동을 통한 보강이 필요하다.', { after: 130 }),
  H('제1절  작목별 CAPEX 실측 집계', HeadingLevel.HEADING_2),
  TBL([1500, 1000, 2400, 2900, 1838], [
    ['작목', '농가수', '평균 총취득가(원)', '취득가 범위(원)', '평균 연감가(원)'],
    ...regRows,
  ], [A.LEFT, A.CENTER, A.RIGHT, A.RIGHT, A.RIGHT]),
  T('작목별 실 취득가·감가 (조사표 템플릿 1,458,000 동일값을 실측으로 대체)'),
  P('"평균 총취득가"는 한 농가가 보유한 대농기구·영농시설을 새로 살 때의 금액(신조가격)을 모두 더한 값이고, "평균 연감가"는 그 자산들을 내용연수로 나눠 매년 비용으로 잡히는 감가상각의 합이다. 완숙토마토 평균 14.2억(유리온실 다수)~참외 2.0억으로, 템플릿의 4작목 동일 상각비와 달리 실 CAPEX는 온실 형태·규모에 따라 7배 이상 차이가 난다.', { after: 120 }),
  BOX('완숙토마토 유리온실은 취득가 약 36억원·내용연수 30년이므로 연 감가상각은 36억 ÷ 30 ≈ 1.2억원이다. 반면 참외 하우스는 취득가·규모가 훨씬 작아 감가 부담이 낮다. 이처럼 조사표에 실입력된 취득가를 넣으면 작목·농가별 투자비가 정확히 드러난다.', { label: '감가상각 예시(실측)' }),
  H('제2절  대표 자산 사양 예시 (실입력)', HeadingLevel.HEADING_2),
  TBL([1500, 2400, 1900, 1200, 2638], [
    ['작목', '대표 영농시설', '취득가(원)', '내용연수', '규격·사양(원문)'],
    ...sampleRows,
  ], [A.LEFT, A.LEFT, A.RIGHT, A.CENTER, A.LEFT]),
  T('작목별 최고가 영농시설 자산 — 취득가·내용연수·사양 실입력 (업체는 조사표 미기재)'),
];

// ── 제6장 활용방안 ─────────────────────────────────────────────────────────
const ch5 = [
  H('제6장  종합 및 활용방안', HeadingLevel.HEADING_1),
  H('제1절  품목별 개선의 의미', HeadingLevel.HEADING_2),
  TBL([2400, 3400, 3838], [
    ['관점', '이전', '이후'],
    ['품목 구분', { t: '4작목 CAPEX 동일(템플릿)', fill: OLD_FILL }, { t: '5농가 실측 시설구성으로 차등(참외가 3작목 대비 약 −24%)', fill: NEW_FILL }],
    ['투자 공백', { t: '안 보임', fill: OLD_FILL }, { t: '방울=측면보온·완숙=환기/관수·참외=보온/차광 노출', fill: NEW_FILL }],
    ['재투자 신호', { t: '없음', fill: OLD_FILL }, { t: '참외 관수 "고장" 등 교체 시점 포착', fill: NEW_FILL }],
    ['소득 정확도', { t: '상각비 수기·무차별', fill: OLD_FILL }, { t: '감가상각을 ERP·비용모델에 품목·면적 차등 자동 반영', fill: NEW_FILL }],
  ], [AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.LEFT]),
  T('품목별 개선의 의미'),

  H('제2절  활용방안', HeadingLevel.HEADING_2),
  P('자산등록부가 갖춰지면 다음 여섯 가지로 활용할 수 있다. 조사 부담을 줄이는 것부터(①), 투자 판단(②③), 표준화·모델 정합(④⑤), 정책 근거(⑥)까지 이어진다.', { after: 100 }),
  B('견적서 연동 자동화 — 기자재 등록(C16) 업로드 견적서·시방서에서 취득가·업체·사양 추출 → 자산등록부 자동 채움 → 감가상각·수리유지 자동 산출(수기 조사 부담 제거).'),
  B('투자 의사결정 지원 — 신규 CAPEX의 (연 감가상각 + 유발 OPEX 증분) vs (노무 절감·수율·품질 편익) ROI 시뮬레이션. 농가별 시설 공백에 맞춘 최우선 투자를 자동 제안(참외 관수 교체, 시설 미비 농가의 보온·측창 등).'),
  B('재투자·교체 시점 관리 — 내용연수 만료 및 "고장" 자산을 재투자(교체 CAPEX) vs 수리(OPEX)로 구분해 알림.'),
  B('작목·지역 표준 CAPEX 벤치마크 — 과업①(소득조사 20개소) 견적 축적 시 품목·규모·지역별 표준 투자비·감가상각 벤치마크 구축 → 신규 진입농가 투자계획 근거.'),
  B('소득 모델 정합 — stage3(매출)·stage4(비용) 소득 검증에 실 감가상각·수리유지를 반영하여 소득(매출−비용) 정확도 향상.'),
  B('정책·보조사업 근거 — 스마트팜 투자 ROI·감가상각 구조 표준화 → 보조사업 심사·경영진단·다년 손익분기(CAPEX/OPEX) 산정 자료로 활용.'),

  H('제3절  선행 조건', HeadingLevel.HEADING_2),
  B('업체(제조사) 정보 확보 — 취득가·내용연수·사양은 조사표(농가 시트)에 실입력돼 있으나, 업체는 거의 미기재. 견적서·시방서 연동으로 보강 필요.'),
  B('과업①에서 견적서·시방서를 조사 항목에 포함하면 업체·단가 결측이 해소되고 개선안이 완결된다.'),
  B('업체·단가 등 영업정보 취급 기준 확정.'),
  new Paragraph({ spacing: { before: 300, after: 200 },
    children: [new TextRun({ text: '※ 본 보고서의 품목별 시설완비도 계수·감가는 20농가 실측 평균이며, 제5장의 취득가·사양은 조사표 실입력값이다. 업체(제조사)만 조사표에 미기재로 견적 연동이 필요하다.', size: 18, color: '595959', font: FONT })] }),
];

const doc = new Document({
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 28, bold: true, font: FONT }, paragraph: { spacing: { before: 320, after: 160 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 24, bold: true, font: FONT }, paragraph: { spacing: { before: 220, after: 130 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: 'b',
    levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 400, hanging: 220 } } } }] }] },
  sections: [{
    properties: { page: { size: A4, margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: '- ', size: 18, font: FONT }),
                 new TextRun({ children: [PageNumber.CURRENT], size: 18, font: FONT }),
                 new TextRun({ text: ' -  ·  스마트팜 소득조사표 현행·개선 보고서', size: 16, color: '888888', font: FONT })] })] }) },
    children: [...cover, ...ch1, ...ch2, ...ch3, ...ch4, ...chReg, ...ch5],
  }],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(OUT, b); console.log(`저장: ${OUT} (${b.length.toLocaleString()} bytes) · 표 ${TN}개`); });
