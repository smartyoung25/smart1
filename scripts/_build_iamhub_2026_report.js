/* (주)이암허브 2026년(1단계 2년차) 중간보고서 (.docx)
 *
 * 근거 문서: 「[첨부2] 연구개발계획서-PART2(본문1) — 스마트팜 수익성 제고 및 경영성과
 *            조사 기반 구축 연구」(260220 수정본)
 * 구성 원칙: 계획서의 '이암허브 1단계-2년차(2026년)' 과업 ①~④ 순서를 그대로 따른다.
 *            평가자가 계획 대비 이행을 바로 대조할 수 있어야 하기 때문이다.
 *
 * ★ 정직성 원칙 (이 보고서는 농진청 제출물이다):
 *   · 현장 활동(소득자료 조사 20개소·FGI 등)은 코드베이스로 확인할 수 없다 →
 *     추정해 쓰지 않고 「기재 필요」 틀만 둔다.
 *   · 계획·평가의견에서 약속했으나 미이행인 항목은 '미이행/추진예정'으로 명시한다.
 *     (실측: 경영비 이상치 알림 미이행 — 현 anomaly_detector 는 환경 센서용이다.
 *            주간/일일 작업추천·RFID 미이행. CAPEX/OPEX 구분·다년 ROI 는 부분 이행.)
 *   · 표4·스택 규모 등 수치는 scripts/_report_facts.py 가 코드에서 재도출한 값만 쓴다.
 *   · farm_registry 716농가는 2018~2022 축적분이며 2026년 조사 20개소와 별개다 — 섞지 않는다.
 *
 * 사용:
 *   PYTHONPATH=C:/smart_farm python scripts/_report_facts.py
 *   NODE_PATH="C:/smart_farm/node_modules" node scripts/_build_iamhub_2026_report.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  LevelFormat, TableOfContents, Footer, PageNumber, PageBreak, VerticalAlign,
} = require('docx');

const ROOT = path.join(__dirname, '..');
const F = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', '_report_facts.json'), 'utf8'));
const OUT = path.join(ROOT, 'out', '이암허브_2026_중간보고서.docx');

const A4 = { width: 11906, height: 16838 };
const MARGIN = 1134;
const W = A4.width - MARGIN * 2;          // 9638
const FONT = '맑은 고딕';
const bd = { style: BorderStyle.SINGLE, size: 1, color: 'BFBFBF' };
const BORDERS = { top: bd, bottom: bd, left: bd, right: bd };
const CELL_M = { top: 60, bottom: 60, left: 100, right: 100 };
const HEAD_FILL = 'DCE6F1';
const TODO_COLOR = 'C00000';

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
/** 「기재 필요」 안내 — 눈에 띄게 */
const TODO = (t) => new Paragraph({
  spacing: { after: 90, line: 300 },
  children: [new TextRun({ text: `「기재 필요」 ${t}`, size: 19, color: TODO_COLOR, italics: true, font: FONT })],
});

const cell = (t, { head = false, w, align, color } = {}) => new TableCell({
  borders: BORDERS, margins: CELL_M, verticalAlign: VerticalAlign.CENTER,
  width: { size: w, type: WidthType.DXA },
  shading: head ? { fill: HEAD_FILL, type: ShadingType.CLEAR } : undefined,
  children: String(t).split('\n').map((line) => new Paragraph({
    alignment: align ?? (head ? AlignmentType.CENTER : AlignmentType.LEFT),
    children: [new TextRun({ text: line, bold: head, size: 18, font: FONT,
                            color: color ?? (String(line).includes('「기재') ? TODO_COLOR : undefined) })],
  })),
});
const TBL = (widths, rows, aligns) => new Table({
  width: { size: W, type: WidthType.DXA }, columnWidths: widths,
  rows: rows.map((r, ri) => new TableRow({
    tableHeader: ri === 0,
    children: r.map((c, ci) => cell(c, { head: ri === 0, w: widths[ci], align: aligns?.[ci] })),
  })),
});
const CAP = (t) => new Paragraph({
  spacing: { before: 70, after: 220 }, alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: t, size: 17, color: '595959', font: FONT })],
});

const S = F.stack, G = F.gate, KB = F.kb, FARMS = F.farms;

// ── 표지 ─────────────────────────────────────────────────────────────────────
const cover = [
  new Paragraph({ spacing: { before: 800, after: 100 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '2026년(1단계 2년차) 중간보고서', bold: true, size: 40, font: FONT })] }),
  new Paragraph({ spacing: { after: 700 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '공동연구기관 : (주)이암허브', size: 24, color: '595959', font: FONT })] }),
  new Paragraph({ spacing: { after: 120 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '스마트팜 수익성 제고 및', bold: true, size: 32, font: FONT })] }),
  new Paragraph({ spacing: { after: 700 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '경영성과 조사 기반 구축 연구', bold: true, size: 32, font: FONT })] }),
  TBL([3200, 6438], [
    ['구 분', '내 용'],
    ['과제번호', '「기재 필요」'],
    ['연구개발기간', '「기재 필요」 (1단계 2년차 : 2026년)'],
    ['연구단계', '1단계 2년차'],
    ['주관연구기관', '농촌진흥청 (연구책임자 : 정재원)'],
    ['공동연구기관', '(주)이암허브 (연구책임자 : 구교영)'],
    ['당해연도 연구개발비', '「기재 필요」'],
    ['보고서 작성일', F.generated],
  ]),
  new Paragraph({ spacing: { before: 800, after: 100 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: F.report_month, size: 24, font: FONT })] }),
  new Paragraph({ spacing: { after: 600 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '공동연구기관 : (주)이암허브', size: 20, font: FONT })] }),
  new Paragraph({ alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '농 촌 진 흥 청', bold: true, size: 30, font: FONT })] }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── 요약 ─────────────────────────────────────────────────────────────────────
const summary = [
  new Paragraph({ spacing: { after: 240 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '요       약', bold: true, size: 30, font: FONT })] }),
  P('본 보고서는 「스마트팜 수익성 제고 및 경영성과 조사 기반 구축 연구」의 1단계 2년차(2026년) 중 공동연구기관 (주)이암허브가 수행한 과업의 추진실적을 연구개발계획서의 과업 구성(①소득자료 조사 ②경영성과 제고 모델검증 ③조사체계 기준 기반 설계 ④경영성과 분석 플랫폼 구축) 순서에 따라 기술한다.', { after: 170 }),
  P(`당해연도 주요 실적은 다음과 같다. 첫째, 경영성과 분석 플랫폼(farmingsight.org)을 ${S.screens}개 화면·${S.routers}개 API 라우터·${S.services}개 도메인 서비스 규모로 구축하여 상시 운영 중이다. 둘째, 주요 시설작목의 수확량 예측모델을 검증 산출물(stage2_meta) 기준으로 평가하고, 다지표 게이트(MAPE·CV R²·표본수·과적합 가드)를 단일 정책 모듈로 통합하여 딸기·오이는 서비스 적용, 방울토마토·참외는 상위 계층 폴백으로 판정하였다. 셋째, 평가의견에서 요구된 생성형 AI 활용 방법론의 구체화와 관련하여, 자사 교재·현장 규칙을 ${KB.total}개 단위의 지식베이스로 구축하고 답변에 출처·쪽수를 명시하는 근거 제시형 AI 상담 체계를 구현하였다.`, { after: 170 }),
  P('한편 계획 대비 미이행 항목이 존재한다. 경영비 이상치 탐지·알림 서비스, 주간/일일 작업추천 시스템, RFID 활용방안은 미착수이며, CAPEX/OPEX 구분에 따른 다년 ROI 추정은 부분 이행 상태이다. 해당 항목은 제5장 잔여기간 추진계획에 반영하였다.', { after: 170 }),
  P('2차년도 소득자료 조사(20개소)는 계획서상 조사시기가 작목의 수확·판매 종료 시점이므로, 조사 실적은 확정 후 기재한다(제2장 참조).', { after: 240 }),
  P('주제어 : 스마트팜, 경영성과, 수익성, 소득조사, 빅데이터, 생성형 AI, 모델검증, 지식베이스, 경영 컨설팅', { size: 19 }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { after: 200 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '목       차', bold: true, size: 30, font: FONT })] }),
  new TableOfContents('목차', { hyperlink: true, headingStyleRange: '1-3' }),
  P('※ 목차 페이지 번호는 Word에서 [참조]→[필드 업데이트]로 갱신됩니다.', { size: 17, color: '808080' }),
];

// ── 제1장 개요 ───────────────────────────────────────────────────────────────
const ch1 = [
  H('제1장  과제 개요', HeadingLevel.HEADING_1),
  H('제1절  과제명 및 연구단계', HeadingLevel.HEADING_2),
  TBL([2400, 7238], [
    ['구분', '내용'],
    ['과제명', '스마트팜 수익성 제고 및 경영성과 조사 기반 구축 연구'],
    ['최종목표', '빅데이터 및 생성형 AI 기반 작목 수익성 제고 및 경영성과 조사기반 설계'],
    ['연구단계', '1단계 2년차 (2026년)'],
    ['본 보고 범위', '공동연구기관 (주)이암허브 수행 과업'],
  ]),
  CAP('표 1. 과제 개요'),

  H('제2절  연구개발 최종목표 및 세부목표', HeadingLevel.HEADING_2),
  P('연구개발계획서상 세부목표는 다음과 같으며, 이 중 (주)이암허브는 플랫폼 구축과 AI 기반 분석·컨설팅을 중점 수행한다.', { after: 130 }),
  B('빅데이터 및 생성형 AI 기반 경영성과 제고를 위한 자료 수집'),
  B('주요 스마트팜 작목 경영성과 조사체계 기준 등 기반 설계'),
  B('스마트팜 기반 농산물소득조사분석 및 활용 기준 제시를 위한 기반 구축'),
  B('빅데이터·생성형 AI 기반 스마트팜 경영성과 수집·분석 플랫폼 구축', 1),
  B('빅데이터·생성형 AI 기반 스마트팜 대상 작목의 농가 맞춤형 경영성과 달성 방안 제시', 1),

  H('제3절  기관별 역할분담', HeadingLevel.HEADING_2),
  P('선정평가 의견(“내부 연구기관과 외부 연구기관과의 역할분담이 명확하여야 함”)을 반영하여 다음과 같이 역할을 구분하였다.', { after: 130 }),
  TBL([2200, 3719, 3719], [
    ['구분', '농촌진흥청(주관)', '(주)이암허브(공동)'],
    ['중점 역할', '조사·분석 및 수집체계 구축', 'AI 기술개발 중심'],
    ['조사 작목', '오이·멜론 각 5농가(10개소)', '딸기·방울토마토·토마토·참외 각 5농가(20개소)'],
    ['최종 산출', '경영성과 조사체계 구축', '경영성과 분석 플랫폼 구축'],
    ['협업 체계', '과제협의회 내 기능별 분과(조사설계·데이터수집·정제·AI분석) 운영', '좌동'],
  ]),
  CAP('표 2. 기관별 역할분담 (연구개발계획서 및 선정평가 의견 반영)'),
];

// ── 제2장 과업별 추진실적 ────────────────────────────────────────────────────
const m2rows = F.m2.map((r) => [
  r.crop, `${r.mape.toFixed(1)}%`, r.cv_r2 == null ? '—' : r.cv_r2.toFixed(3),
  String(r.n_train), r.model, r.label,
]);
const cropRows = Object.entries(FARMS.by_crop)
  .filter(([, n]) => n >= 20)
  .map(([k, n]) => [k, String(n)]);

const ch2 = [
  H('제2장  2026년(1단계 2년차) 과업별 추진실적', HeadingLevel.HEADING_1),
  P('연구개발계획서의 ‘(주)이암허브 1단계–2년차(2026년)’ 과업 구성에 따라 기술한다.', { after: 160 }),

  // 과업 ①
  H('제1절  과업① 2차년도 소득자료 조사 (20개소)', HeadingLevel.HEADING_2),
  P('계획 : 딸기·방울토마토·토마토·참외 각 5농가, 총 20개소. 조사내용은 농가 기본현황·총수입·수량·경영비·투입요소(자본·노동 등)이며, 스마트팜 농가의 차별성(자본용역비·감가상각비 등)을 반영한다. 조사시기는 작목의 수확 및 판매가 종료된 시점이다.', { after: 130 }),
  TODO('조사시기가 작목의 수확·판매 종료 시점이므로 본 보고 시점 기준 조사 실적을 아래 표에 확정 기재할 것.'),
  TBL([1700, 1500, 1500, 2200, 2738], [
    ['작목', '계획(농가)', '조사완료', '조사시기', '비고'],
    ['딸기', '5', '「기재」', '「기재」', '「기재」'],
    ['방울토마토', '5', '「기재」', '「기재」', '「기재」'],
    ['토마토', '5', '「기재」', '「기재」', '「기재」'],
    ['참외', '5', '「기재」', '「기재」', '「기재」'],
    ['계', '20', '「기재」', '—', '—'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.LEFT]),
  CAP('표 3. 과업① 2차년도 소득자료 조사 추진실적'),
  P('(라) 이미지 판독·RFID 등 빅데이터 및 생성형 AI 활용방안 마련', { bold: true, after: 80 }),
  B('이미지 판독 : 병해 진단 서비스로 구현하여 플랫폼에 탑재(제4절 참조).'),
  B('RFID : 미착수 — 조사 자동화 적용 범위를 확정한 후 잔여기간에 활용방안을 마련한다(제5장).'),

  // 과업 ②
  H('제2절  과업② 빅데이터 및 생성형 AI 기반 경영성과 제고 모델검증', HeadingLevel.HEADING_2),
  H('1. (가) 농가핵심 검증 데이터 확보', HeadingLevel.HEADING_3),
  P('계획서가 정의한 환경관리·생육관리·경영성과 3개 영역의 검증 데이터를 플랫폼에서 수집·산출하도록 구현하였다.', { after: 130 }),
  TBL([1700, 2600, 5338], [
    ['구분', '세부 항목', '플랫폼 구현 현황'],
    ['환경관리', '환경적합성·기후 리스크·에너지 효율성', '환경관리 전략표(생육시기×하루 4구간), 평년기상(ERA5) 대비 편차 진단, 피크시간 에너지 절감'],
    ['생육관리', '생산성·품질·자원 관리', '수확량 예측(M2)·생육(M1)·병해(M5) 모델, 관수 P1~P6 정밀제어, 자원(급액·EC) 기록'],
    ['경영성과', '이익·ROI·매출·비용', 'ERP 소득구조 분석(경영비 13항목), ROI·회수기간, KAMIS 시세 연동 매출, 손익분기(BEP)'],
  ]),
  CAP('표 4. 농가핵심 검증 데이터 확보 현황'),
  P('학습·실증 기반 데이터는 농촌진흥청 수집분을 표준화하여 적재하였다.', { after: 100 }),
  TBL([4819, 4819], [
    ['구분', '내용'],
    ['농가 수', `${FARMS.total}농가`],
    ['수집 연도', `${FARMS.years[0]}~${FARMS.years[FARMS.years.length - 1]}년`],
    ['주요 작목(20농가 이상)', cropRows.map(([k, n]) => `${k} ${n}`).join(' · ')],
  ]),
  CAP(`표 5. 적재된 학습·실증 기반 데이터 (기준일 ${(FARMS.generated_at || '').slice(0, 10)})`),
  P('※ 상기 데이터는 축적분이며, 과업①의 2026년 소득자료 조사(20개소)와는 별개이다.', { size: 18, color: '595959' }),

  H('2. (나) 작목/지역/농가별 경영성과 실증', HeadingLevel.HEADING_3),
  P('작목별 수확량 예측모델을 검증 산출물(stage2_meta.json) 기준으로 평가하고, 다지표 게이트로 서비스 적용 여부를 판정하였다. 당해연도에는 게이트 정책이 여러 모듈에 흩어져 서로 다른 임계를 쓰던 문제를 해소하고, 단일 정책 모듈(pipeline/gates.py)로 통합하여 모든 승격·서빙 경로가 이를 참조하도록 하였다.', { after: 130 }),
  TBL([2600, 1700, 5338], [
    ['판정', '조건', '조치'],
    ['검증 적용', `MAPE ≤ ${G.mape_serve}% 이고 CV R² ≥ ${G.cv_r2_min}`, '농장 맞춤 모델을 서비스에 적용'],
    ['조건부', `MAPE ${G.mape_serve}~${G.mape_fallback}% 또는 CV R² < ${G.cv_r2_min}`, '서비스하되 데이터 확충·재학습 보완'],
    ['폴백', `MAPE > ${G.mape_fallback}%`, '상위 계층(농진청 표준/광역)으로 자동 폴백'],
  ]),
  CAP('표 6. 모델 검증 게이트 판정 기준 (단일 출처: pipeline/gates.py)'),
  TBL([1500, 1300, 1300, 1300, 1800, 2438], [
    ['작목', 'MAPE', 'CV R²', '표본수(n)', '모델', '판정'],
    ...m2rows,
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER]),
  CAP('표 7. 작목별 수확량(M2) 모델 검증 결과'),
  B('딸기·오이는 MAPE 17.8~22.8%로 서비스 적용 수준을 확보하였다.'),
  B('파프리카(29.2%)·완숙토마토(28.1%)는 조건부 — 완숙토마토는 CV R² 0.099로 설명력이 부족하다.'),
  B('방울토마토(48.6%)·참외(63.9%)는 폴백 임계를 초과하여 상위 계층으로 폴백, 예측 안정성을 유지한다.'),
  B(`오이·파프리카·방울토마토·참외는 표본수가 경고 임계(n<${G.n_min}) 미만이고 학습 파이프라인이 단순 모델(Ridge)로 폴백한 상태다. 높은 CV R²에 낙관편의 소지가 있어 농장단위 LOGO 교차검증 재판정이 필요하다(제5장).`),
  TODO('지역별·농가별 경영성과 실증 결과(스마트팜 도입수준·유통방식별 비교)는 과업① 조사자료 확보 후 기재.'),

  H('3. (다) 빅데이터 AI 기반 현장실증 및 최적화', HeadingLevel.HEADING_3),
  P('선정평가 의견(“이익·ROI·매출·비용 분석의 방법론이 구체적으로 제시되지 않음”)에 대해 계획서에서 약속한 사항의 이행 현황은 다음과 같다.', { after: 130 }),
  TBL([3400, 1500, 4738], [
    ['계획·평가의견 약속 사항', '이행', '현황'],
    ['연간 손익분기(BEP) 추정', '이행', 'ERP 화면에 손익분기·고정비/변동비 구조 구현'],
    ['투자 효율(ROI)·회수기간 추정', '부분', 'ROI·회수기간·투자비 구현. CAPEX/OPEX 구분에 따른 다년 ROI 추정은 미반영'],
    ['과거 3년치 이상 경영비 기반\n이상치 분석 → 알림 서비스', '미이행', '현 이상치 탐지는 환경 센서(EC·pH·온습도) 대상이며 경영비 이상치는 미착수'],
    ['환경제어·생산성·출하 최적화', '부분', '환경 전략표·관수 P1~P6·에너지 절감 구현. 출하 타이밍 최적화는 시세 조회 수준'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT]),
  CAP('표 8. 과업②(다) 현장실증·최적화 이행 현황'),

  H('4. (라) AI 맞춤형 농가컨설팅 (현장검증단계)', HeadingLevel.HEADING_3),
  P('계획서의 5단계 컨설팅 모델에 대한 플랫폼 구현 현황은 다음과 같다.', { after: 130 }),
  TBL([1200, 2600, 1300, 4538], [
    ['단계', '계획 내용', '이행', '구현 현황'],
    ['1단계', '대상 농가 초기 진단', '이행', '온보딩 설문·현장 점검 체크리스트, 스마트팜 도입단계(역량단계) 분류'],
    ['2단계', '생육환경 데이터 수집·분석', '이행', '센서 자동 연동 + 수기입력 병행(온도·습도·광·EC·pH·CO₂), 대시보드'],
    ['3단계', '작목별 AI 기반 생육처방', '이행', '3계층 예측모델, 환경 최적조건 산출, 편차 기반 처방 생성'],
    ['4단계', '경영지표 기반 피드백·보정', '부분', 'PDCA 루프·KPI 임계 알림 구현. 실측 대비 예측 오차의 자동 재보정은 관리자 승인 방식'],
    ['5단계', '지속운영 및 리포트 제공', '부분', '컨설팅 리포트 화면 구현. 주간/일일 작업추천 시스템은 미착수'],
  ], [AlignmentType.CENTER, AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT]),
  CAP('표 9. 과업②(라) AI 맞춤형 농가컨설팅 5단계 이행 현황'),

  // 과업 ③
  H('제3절  과업③ 경영성과 조사체계 기준 등 기반 설계 (고도화)', HeadingLevel.HEADING_2),
  P('계획서상 본 과업은 1년차 조사 시 발견된 유의사항을 반영하여 조사기반을 고도화하는 것으로, 최종 조사체계 구축은 주관기관(농촌진흥청)이 중점 추진하고 이암허브는 플랫폼 반영을 담당한다.', { after: 130 }),
  B('경영비 조사 항목(13항목)을 플랫폼 입력 화면에 반영하여 조사표 기반 수집이 가능하도록 구현하였다.'),
  B('입력 이상치(환경·관수 범위 이탈) 선제 플래그로 조사·수집 데이터의 품질을 관리한다.'),
  TODO('1년차 조사 시 발견된 유의사항(총수입·경영비·소득 조사 유의사항, 조사대상·조사원·조사방법 등 조사환경 유의사항)과 그 반영 결과는 주관기관 협의 후 기재.'),

  // 과업 ④
  H('제4절  과업④ 빅데이터 및 생성형 AI 기반 경영성과 분석 플랫폼 구축', HeadingLevel.HEADING_2),
  H('1. 플랫폼 구축 현황', HeadingLevel.HEADING_3),
  P('농가용 모바일 서비스와 다농가 관제 콘솔을 단일 백엔드(FastAPI) 위에 구성하고, 예측·검증·처방을 API로 제공한다. 컨테이너(Docker) 기반으로 배포하며 공개 도메인(farmingsight.org)에서 상시 운영한다.', { after: 130 }),
  TBL([2200, 7438], [
    ['구성 요소', '내용'],
    ['프론트엔드', `모바일 HTML ${S.screens}개 화면(PWA), 다농가 관제 콘솔, 가치사슬 스테퍼`],
    ['백엔드', `FastAPI — ${S.routers}개 라우터, ${S.services}개 도메인 서비스`],
    ['AI/모델', '3계층 예측(M1·M2·M5), 검증 게이트(단일 정책 모듈), 드리프트 감시, 재학습 어드바이저'],
    ['AI 지식', `영농기술 지식베이스 ${KB.total}개 단위 + BM25 검색 → 답변 근거·출처 제시`],
    ['데이터', '농진청 표준·KAMIS 시세·기상(KMA/ERA5)·센서·농가입력'],
    ['인프라', 'Docker(TimescaleDB·Redis·API), Cloudflare 터널, Ubuntu 서버 상시 운영'],
  ]),
  CAP('표 10. 경영성과 분석 플랫폼 구성'),

  H('2. 플랫폼 내 빅데이터·생성형 AI 활용방안', HeadingLevel.HEADING_3),
  P('계획서는 대시보드를 통한 의사결정과 함께 멀티모달 상담챗봇, 주간/일일작업추천시스템 등을 통한 경영성과 향상을 제시한다. 이행 현황은 다음과 같다.', { after: 130 }),
  TBL([2800, 1300, 5538], [
    ['계획 항목', '이행', '현황'],
    ['대시보드 기반 의사결정', '이행', '농가 모바일 대시보드 + 다농가 관제 콘솔 상시 운영'],
    ['멀티모달 상담챗봇', '이행', '텍스트 상담 + 이미지 기반 병해 진단. 지식베이스 근거 결합(하단 참조)'],
    ['주간/일일 작업추천 시스템', '미이행', '미착수 — 잔여기간 추진(제5장)'],
    ['실시간 모니터링·위험 진단', '이행', '환경 이상 감지, KPI 임계 경보, 드리프트 감시'],
    ['KPI 피드백 및 전략 보정', '부분', 'PDCA 루프 구현. 자동 재보정은 관리자 승인 방식'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT]),
  CAP('표 11. 과업④ 플랫폼 내 빅데이터·생성형 AI 활용 이행 현황'),

  H('3. 생성형 AI 근거 제시 체계 (지식베이스)', HeadingLevel.HEADING_3),
  P('선정평가 의견은 “생성형 AI가 적용되는 경영성과 조사 방법의 구체화”와 “방법론의 구체적 제시”를 요구하였다. 생성형 AI 상담의 최대 위험은 근거 없는 답변(환각)이므로, 자사 보유 지식을 검색 가능한 지식베이스로 구축하고 답변이 그 근거만 인용하도록 결합하였다.', { after: 130 }),
  TBL([2600, 1300, 5738], [
    ['지식 원천', '지식 단위', '내용'],
    ['스마트농업컨설턴트 교재', `${KB.textbook}개`, '병해충 진단·환경 관리·작목별 재배 기준(449쪽을 의미 단위로 분할)'],
    ['제품 도메인 규칙', `${KB.rules}개`, '관수 P1~P6·일사 적산 트리거·PDCA 임계값·VPD 계산·작목별 권장 밴드'],
    ['합계', `${KB.total}개`, '—'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT]),
  CAP('표 12. 영농기술 지식베이스 구성'),
  B('상보성 : 교재는 병해충·환경에 강하나 관수 정밀제어 지식(배액률·dry-back·일사 적산)이 없고, 제품 규칙에는 병해충이 없다. 두 원천의 결합으로 상담 범위가 완성된다.'),
  B('단일 출처 : 제품 규칙은 규칙이 구현된 코드에서 자동 추출하여 지식과 구현이 어긋나지 않도록 하였다.'),
  B('검색 방식 : 별도 임베딩·벡터DB 없이 BM25로 구현하여 외부 LLM 서비스의 비용·장애와 무관하게 동작한다.'),
  B('근거 결합 : 질문에 해당하는 지식을 검색해 프롬프트에 근거로 제공하고, 답변에 근거 번호와 출처·쪽수를 명시하도록 강제한다. 검색 결과가 없으면 근거 없음을 밝히고 단정하지 않는다.'),
  B('안전 : 농약·방제 권고 시 등록 정보(PLS 적용작물·희석배수·안전사용기준) 확인 문구를 강제하고, 병해 진단이 확정 진단이 아님을 명시한다.'),

  H('4. 데이터 보안 조치 이행', HeadingLevel.HEADING_3),
  P('계획서 보안조치 이행계획에 따른 현황이다.', { after: 130 }),
  TBL([2600, 1300, 5738], [
    ['보안 조치 계획', '이행', '현황'],
    ['데이터 접근 통제', '이행', '사용자 권한(역할) 기반 접근 제한. 공개 데모 환경은 관리자 쓰기 전면 차단'],
    ['개인정보 비식별화·암호화', '조치 중', '「기재 필요」 — 별도 점검 결과 및 조치 계획 기재'],
    ['서버 보안', '이행', '방화벽(인바운드 최소 개방), 터널 기반 외부 노출 최소화, 접근 로그 기록'],
    ['외부 협업 시 NDA', '「기재」', '「기재 필요」'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT]),
  CAP('표 13. 보안조치 이행 현황'),
];

// ── 제3장 평가의견 반영 ──────────────────────────────────────────────────────
const ch3 = [
  H('제3장  선정평가 의견 반영 현황', HeadingLevel.HEADING_1),
  P('연구개발계획서에 기재된 (2공동) 관련 선정평가 의견에 대한 당해연도 반영 현황이다.', { after: 160 }),
  TBL([3200, 1300, 5138], [
    ['선정평가 의견', '반영', '당해연도 조치'],
    ['이익·ROI·매출·비용 분석의 방법론이 구체적으로 제시되지 않음', '부분', 'BEP·ROI·회수기간 구현. CAPEX/OPEX 구분 다년 ROI, 경영비 이상치 알림은 잔여기간 추진'],
    ['조사 항목과 경영성과의 매칭율·민감도 분석을 정량적 목표로 설정 필요', '부분', 'KPI 임계·What-if(민감도) 분석 구현. 델파이·부분상관 기반 정량화는 주관기관 협의 후 추진'],
    ['생성형 AI가 적용되는 경영성과 조사 방법의 구체화 필요', '반영', `지식베이스 ${KB.total}단위 구축, 근거·출처 제시형 상담 체계 구현`],
    ['내부·외부 연구기관의 역할분담 명확화 필요', '반영', '조사·수집체계(농진청) / AI 기술개발·플랫폼(이암허브)로 구분, 제1장 제3절'],
    ['모델 실증·데이터 확보를 위한 농가 협업 계획 제시 필요', '부분', `축적 데이터 ${FARMS.total}농가 기반 모델 검증 수행. 2026년 조사농가 협업은 과업① 진행에 따름`],
    ['협력기관 협약 자료 보완 필요', '「기재」', '「기재 필요」 — 협약 체결 현황 기재'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT]),
  CAP('표 14. 선정평가 의견 반영 현황'),
];

// ── 제4장 달성도 ─────────────────────────────────────────────────────────────
const ch4 = [
  H('제4장  목표 달성도', HeadingLevel.HEADING_1),
  TBL([2600, 1400, 3800, 1838], [
    ['과업', '목표치', '당해연도 실적', '달성도'],
    ['① 2차년도 소득자료 조사(20개소)', '20개소', '「기재 필요」', '「기재」'],
    ['② 경영성과 제고 모델검증', '「기재」', `시설 6작목 게이트 판정 완료(적용 2·조건부 2·폴백 2), 학습기반 ${FARMS.total}농가`, '부분 달성'],
    ['③ 조사체계 기준 기반 설계(고도화)', '「기재」', '조사 13항목 플랫폼 반영, 입력 품질 관리 구현', '부분 달성'],
    ['④ 경영성과 분석 플랫폼 구축', '「기재」', `화면 ${S.screens}·라우터 ${S.routers}·서비스 ${S.services}, 상시 운영`, '달성'],
    ['④-1 생성형 AI 활용(상담챗봇)', '「기재」', `지식베이스 ${KB.total}단위·출처 제시형 상담 구현`, '달성'],
    ['④-2 주간/일일 작업추천', '「기재」', '미착수', '미달성'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT, AlignmentType.CENTER]),
  CAP('표 15. 과업별 목표 달성도 (목표치는 협약서에 따라 기재)'),
  P('※ 정량적 목표치는 협약서 기준으로 「기재」 부분에 기재 후 제출한다.', { size: 18, color: '595959' }),
];

// ── 제5장 잔여계획 ───────────────────────────────────────────────────────────
const ch5 = [
  H('제5장  잔여기간 추진계획', HeadingLevel.HEADING_1),
  H('제1절  미이행 항목 조치계획', HeadingLevel.HEADING_2),
  TBL([2800, 4900, 1938], [
    ['미이행 항목', '조치계획', '시기'],
    ['경영비 이상치 탐지·알림', '과거 3년치 이상 경영비 이력 기반 이상치 분석 모듈 개발 후 알림 서비스 연계 (평가의견 약속 사항)', '「기재」'],
    ['CAPEX/OPEX 다년 ROI', '스마트팜 비용투입구조에 따른 CAPEX·OPEX 구분, 연간 손익분기 및 다년 ROI 추정 반영', '「기재」'],
    ['주간/일일 작업추천 시스템', '누적 데이터 기반 작업 추천 로직 설계·구현 (컨설팅 5단계 중 5단계 보완)', '「기재」'],
    ['RFID 활용방안', '조사 자동화 적용 범위 확정 후 활용방안 마련', '「기재」'],
  ], [AlignmentType.LEFT, AlignmentType.LEFT, AlignmentType.CENTER]),
  CAP('표 16. 미이행 항목 조치계획'),

  H('제2절  모델 고도화 계획', HeadingLevel.HEADING_2),
  B('게이트 폴백 작목(방울토마토·참외)의 실측 데이터 확충·재학습으로 정확도 제고.'),
  B(`소표본 작목(오이·파프리카·방울토마토·참외, n<${G.n_min})의 농장단위 LOGO 교차검증 재판정으로 낙관편의 제거.`),
  B('완숙토마토의 설명력(CV R² 0.099) 개선을 위한 변수 재설계.'),
  B('지식베이스 확충 : 농진청 재배지침·병해충 DB(NCPMS) 연계 및 의미 기반 검색(임베딩) 도입 검토.'),

  H('제3절  주관기관 협의 필요 사항', HeadingLevel.HEADING_2),
  B('1년차 조사 유의사항의 플랫폼 반영 범위 확정(과업③).'),
  B('조사 항목–경영성과 매칭율·민감도의 정량적 목표 설정 방식(델파이·부분상관) 협의.'),
  B('과제협의회 기능별 분과(조사설계·데이터수집·정제·AI분석) 운영 일정 협의.'),
  B('통계조사 확대 방안 및 경영의사결정지원 기술의 현장활용 확대 방안 보완.'),

  new Paragraph({ spacing: { before: 300, after: 200 },
    children: [new TextRun({ text: '※ 본 문서의 행정정보(과제번호·연구기간·연구개발비 등)와 「기재 필요」 표시 항목은 협약서 및 현장 조사 실적 확정 후 기재하여 제출하시기 바랍니다.', size: 18, color: '595959', font: FONT })] }),

  new Paragraph({ spacing: { before: 400 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '본 보고서의 저작권은 (주)이암허브와 한국스마트농업AI협회에 있음.', size: 18, color: '595959', font: FONT })] }),
];

const doc = new Document({
  creator: '(주)이암허브',
  title: '스마트팜 수익성 제고 및 경영성과 조사 기반 구축 연구 — (주)이암허브 2026년(1단계 2년차) 중간보고서',
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 30, bold: true, font: FONT, color: '1F3864' },
        paragraph: { spacing: { before: 320, after: 200 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 25, bold: true, font: FONT, color: '2E5496' },
        paragraph: { spacing: { before: 240, after: 140 }, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 22, bold: true, font: FONT, color: '404040' },
        paragraph: { spacing: { before: 180, after: 110 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [{
      reference: 'b',
      levels: [
        { level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 400, hanging: 220 } } } },
        { level: 1, format: LevelFormat.BULLET, text: '–', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 760, hanging: 220 } } } },
      ],
    }],
  },
  sections: [{
    properties: { page: { size: A4, margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN } } },
    footers: {
      default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, font: FONT })],
      })] }),
    },
    children: [...cover, ...summary, ...ch1, ...ch2, ...ch3, ...ch4, ...ch5],
  }],
});

Packer.toBuffer(doc).then((b) => {
  fs.writeFileSync(OUT, b);
  console.log(`저장: ${OUT} (${b.length.toLocaleString()} bytes)`);
});
