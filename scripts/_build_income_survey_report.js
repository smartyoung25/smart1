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
    ['작성일', '2026-08-04'],
  ]),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── 제1장 개요 ───────────────────────────────────────────────────────────────
const ch1 = [
  H('제1장  개요', HeadingLevel.HEADING_1),
  H('제1절  배경과 목적', HeadingLevel.HEADING_2),
  P('현행 스마트팜 소득조사표는 투자비(CAPEX)를 "상각비 두 줄"(대농구·영농시설)로만 담고 있어, 무엇을 얼마에 몇 년 동안 사용하는 자산인지 추적할 수 없다. 본 보고서는 소득조사표 4작목(딸기·방울토마토·완숙토마토·참외)의 실데이터를 분석하여 현행 현안을 규명하고, 3계층 자산등록부 기반의 개선 방향과 품목별 활용방안을 제시한다.', { after: 130 }),
  P('★ 분석 과정에서 확인한 중요 사실: 조사표의 집계 상각비(대농구 675,000 + 영농시설 783,000)와 성명 "홍길동"은 4작목이 완전히 동일한 샘플 템플릿이며, 실 농가 투자비가 아니다. 품목별 실 차이는 조사표 "농가" 시트의 시설 구성에 있다.', { bold: true, after: 130 }),
];

// ── 제2장 현안 ───────────────────────────────────────────────────────────────
const ch2 = [
  H('제2장  현행 소득조사표 현안', HeadingLevel.HEADING_1),
  P('소득조사표에서 실제 확인한 7대 현안은 다음과 같다.', { after: 130 }),
  TBL([600, 2600, 3400, 3038], [
    ['#', '현안', '근거 (조사표)', '영향'],
    ['1', 'CAPEX가 집계 상각비 2줄뿐', '소득분석2: 대농구 675,000 + 영농시설 783,000', '자산별 세분·취득가·업체·성능 부재 → 투자 분석 불가'],
    ['2', '샘플 템플릿이 실데이터처럼 존재', '이름 "홍길동", 4작목 상각비 값 완전 동일', '실 농가 투자비 아님'],
    ['3', '분류가 2종(대농구/영농시설)뿐', '복합환경제어·양액기·센서·난방기 혼재', '스마트팜 자동화 설비 특성 미반영'],
    ['4', '감가상각 산출근거 불투명', '취득가·내용연수·잔존율 부재', '재계산·검증·재투자 판단 불가'],
    ['5', 'OPEX↔CAPEX 연동 단절', '수리유지·수도광열·임차료 대부분 0, 매핑 없음', '투자→운영비 파급 분석 불가'],
    ['6', '시설이 정성 코드로만', '농가 시설현황이 코드값(○/×)만', '정량 투자비 산출 불가'],
    ['7', '작목별 시설차이 미반영', '참외=보온·차광·관수 미설치/고장인데 상각비는 동일', '작목별 CAPEX 차이가 소득에 안 잡힘'],
  ], [AlignmentType.CENTER, AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.LEFT]),
  T('현행 소득조사표 7대 현안'),
];

// ── 제3장 개선 방향 ─────────────────────────────────────────────────────────
const ch3 = [
  H('제3장  개선 방향', HeadingLevel.HEADING_1),
  P('현안을 해소하기 위해 CAPEX를 3계층 자산등록부로 구조화하고, 감가상각을 수식화하며, OPEX와 연동하였다. 구축·연동은 완료된 상태다.', { after: 130 }),
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
  P('같은 항목이 어떻게 바뀌는가 (대조)', { bold: true, after: 80 }),
  TBL([2600, 3400, 3638], [
    ['항목', '현행', '개선'],
    [{ t: '영농시설 투자', bold: true }, { t: '"영농시설 상각비 783,000" (한 줄)', fill: OLD_FILL }, { t: '온실구조·보온·차광 등 자산별 분해 (취득가·내용연수·정액감가)', fill: NEW_FILL }],
    [{ t: '감가상각 근거', bold: true }, { t: '(없음)', fill: OLD_FILL }, { t: '= 취득가액×(1−잔존율)÷내용연수 (수식)', fill: NEW_FILL }],
    [{ t: '작목 차이', bold: true }, { t: '딸기=방울=완숙=참외 동일', fill: OLD_FILL }, { t: '참외 96.1 vs 완숙 126.9 원/㎡·월 (5농가 실측 시설완비도 차등)', fill: NEW_FILL }],
    [{ t: '운영비 연결', bold: true }, { t: '(없음)', fill: OLD_FILL }, { t: '난방기→수도광열, 양액기→전기·물, 시설→수리유지', fill: NEW_FILL }],
    [{ t: '소득 반영', bold: true }, { t: '상각비 수기', fill: OLD_FILL }, { t: 'ERP /costs에 "감가상각·수리유지" 자동 항목화', fill: NEW_FILL }],
  ], [AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.LEFT]),
  T('현행 vs 개선 항목 대조'),
];

// ── 제4장 품목별 ─────────────────────────────────────────────────────────────
const O = (t) => ({ t, fill: OLD_FILL }); const N = (t) => ({ t, fill: NEW_FILL });
const ch4 = [
  H('제4장  품목별 이전 vs 이후', HeadingLevel.HEADING_1),
  P('★ 이전에는 4작목이 동일한 템플릿 값이었으나, 이후에는 조사표 "농가" 시트의 실 시설 구성으로 품목별 CAPEX를 차등한다.', { after: 130 }),
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
  B('이전 : 상각비 675,000+783,000(템플릿). 저온관리·수작업 수확·시설 완비 미반영.'),
  B('이후 : 표본농가 전 시설 ○, 5농가 실측 계수 0.934(감가 1,361,772). 저온기 보온 투자와 감가가 자산별로 명시.'),
  B('활용 : 노동집약 → 관리 자동화(유인·적엽) 투자 ROI를 감가+노무절감으로 대조. 측면보온 완비 → 난방절감 회수기간 검증.'),

  H('제2절  방울토마토 (박경종) — 다수확·측면보온 미설치', HeadingLevel.HEADING_2),
  B('이전 : 딸기와 동일 템플릿 → 다수확(65,464kg)·측면보온 부재 미반영.'),
  B('이후 : 표본농가는 측면 보온스크린만 ✕, 5농가 실측 계수 0.910(감가 1,326,780). 보온 투자 여지가 공백으로 노출.'),
  B('활용 : 측면보온 신규투자 시뮬레이션(추가 감가 vs 난방비 절감). 다수확 → 자동 선별·포장 검토.'),

  H('제3절  완숙토마토 (김선환) — 최다 생산량·환기/관수 수동', HeadingLevel.HEADING_2),
  B('이전 : 동일 템플릿 → 최다 생산량(198,797kg)·측창/관수 부재(수동 운영) 미반영.'),
  B('이후 : 표본농가(김선환)는 측창·관수관비 ✕이나, 5농가 실측 계수 0.940(감가 1,370,520)으로 대부분 완비 — 초기 단일샘플 판단(공백 최대)을 실측이 정정. 자동화 편차가 농가별로 크다.'),
  B('활용 : 최다 생산량(198,797kg)으로 규모 효과 큼. 5농가 중 시설 미비 농가(표본 김선환 등)에 한해 환기·관수 자동화 CAPEX(감가+전기) vs 노무·수율 ROI를 개별 제안 — 완숙 전반의 공백이 아니라 농가 편차 대응.'),

  H('제4절  참외 (강석구) — 반촉성·저투자·관수 고장', HeadingLevel.HEADING_2),
  B('이전 : 동일 템플릿(1,458,000) → 반촉성·최소 시설인 참외가 딸기와 같은 투자비로 잡혀 소득 왜곡.'),
  B('이후 : 표본농가는 보온·차광 없음·측창만 ○·관수관비 고장, 5농가 실측 계수 0.712(감가 1,038,096·최소). 4작목 중 유일하게 확연히 낮아 저CAPEX 특성이 실측으로 확인됨.'),
  B('활용 : 관수관비 "고장" → 재투자(교체) vs 수리(OPEX) 의사결정 최우선. 저투자·저비용 구조 → 신규 진입농가 표준 모델.'),
];

// ── 제5장 활용방안 ─────────────────────────────────────────────────────────
const ch5 = [
  H('제5장  종합 및 활용방안', HeadingLevel.HEADING_1),
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
  B('견적서 연동 자동화 — 기자재 등록(C16) 업로드 견적서·시방서에서 취득가·업체·사양 추출 → 자산등록부 자동 채움 → 감가상각·수리유지 자동 산출(수기 조사 부담 제거).'),
  B('투자 의사결정 지원 — 신규 CAPEX의 (연 감가상각 + 유발 OPEX 증분) vs (노무 절감·수율·품질 편익) ROI 시뮬레이션. 농가별 시설 공백에 맞춘 최우선 투자를 자동 제안(참외 관수 교체, 시설 미비 농가의 보온·측창 등).'),
  B('재투자·교체 시점 관리 — 내용연수 만료 및 "고장" 자산을 재투자(교체 CAPEX) vs 수리(OPEX)로 구분해 알림.'),
  B('작목·지역 표준 CAPEX 벤치마크 — 과업①(소득조사 20개소) 견적 축적 시 품목·규모·지역별 표준 투자비·감가상각 벤치마크 구축 → 신규 진입농가 투자계획 근거.'),
  B('소득 모델 정합 — stage3(매출)·stage4(비용) 소득 검증에 실 감가상각·수리유지를 반영하여 소득(매출−비용) 정확도 향상.'),
  B('정책·보조사업 근거 — 스마트팜 투자 ROI·감가상각 구조 표준화 → 보조사업 심사·경영진단·다년 손익분기(CAPEX/OPEX) 산정 자료로 활용.'),

  H('제3절  선행 조건', HeadingLevel.HEADING_2),
  B('자산별 취득가(견적) 확보 — 현재 자산등록부는 내용연수·잔존율 표준만 갖고 있고 취득가는 입력 대기 상태.'),
  B('과업①에서 견적서·시방서를 조사 항목에 포함하면 개선안이 실데이터로 즉시 작동한다.'),
  B('업체·단가 등 영업정보 취급 기준 확정.'),
  new Paragraph({ spacing: { before: 300, after: 200 },
    children: [new TextRun({ text: '※ 본 보고서의 CAPEX 감가상각 수치는 조사표 표준 템플릿을 시설 완비도로 차등한 값이며, 각 농가 견적서 입력 시 실 취득가 기반으로 갱신된다.', size: 18, color: '595959', font: FONT })] }),
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
    children: [...cover, ...ch1, ...ch2, ...ch3, ...ch4, ...ch5],
  }],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(OUT, b); console.log(`저장: ${OUT} (${b.length.toLocaleString()} bytes) · 표 ${TN}개`); });
