/* 농진청 연구개발과제 중간보고서 (.docx) 생성
 *
 * ★ 왜 스크립트로 두는가: 2026-07-16 최초본은 임시 스크립트로 만들어 레포에 남지 않았고,
 *   갱신하려 할 때 원본 구조를 docx 에서 역추출해야 했다. 보고서는 수치가 코드·아티팩트와
 *   함께 낡으므로 반드시 재생성 가능해야 한다.
 *
 * ★ 수치 단일 출처: 표4(모델 검증 결과)와 게이트 기준은 손으로 적지 않는다.
 *   scripts/_report_facts.py 가 pipeline/gates.py + stage2_meta.json(권위)에서 뽑아
 *   out/_report_facts.json 으로 덤프하고, 이 스크립트가 그것을 읽는다.
 *   (과거 사고: registry.json(동결값)을 인용해 표4가 틀렸다 — 권위는 stage2_meta 뿐이다.)
 *
 * 사용:
 *   PYTHONPATH=C:/smart_farm python scripts/_report_facts.py     # 사실 덤프 선행
 *   NODE_PATH="C:/smart_farm/node_modules" node scripts/_build_interim_report.js
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
const FACTS = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', '_report_facts.json'), 'utf8'));
const OUT = path.join(ROOT, 'out', 'KAASA_농진청_중간보고서.docx');

// ── 레이아웃 상수 (US Letter 아님 — 국내 공문서는 A4) ─────────────────────────
const A4 = { width: 11906, height: 16838 };
const MARGIN = 1134;                       // 2cm
const CONTENT_W = A4.width - MARGIN * 2;   // 9638

const FONT = '맑은 고딕';
const border = { style: BorderStyle.SINGLE, size: 1, color: 'BFBFBF' };
const BORDERS = { top: border, bottom: border, left: border, right: border };
const CELL_M = { top: 60, bottom: 60, left: 100, right: 100 };
const HEAD_FILL = 'DCE6F1';

const P = (text, opts = {}) => new Paragraph({
  spacing: { after: opts.after ?? 100, line: 300 },
  alignment: opts.align,
  indent: opts.indent,
  children: [new TextRun({ text, bold: opts.bold, size: opts.size ?? 20, color: opts.color, font: FONT })],
});

const H = (text, level) => new Paragraph({
  heading: level,
  spacing: { before: level === HeadingLevel.HEADING_1 ? 320 : 220, after: 160 },
  pageBreakBefore: !!(level === HeadingLevel.HEADING_1),
  children: [new TextRun({ text, font: FONT })],
});

const BULLET = (text, level = 0) => new Paragraph({
  numbering: { reference: 'bullets', level },
  spacing: { after: 70, line: 300 },
  children: [new TextRun({ text, size: 20, font: FONT })],
});

const cell = (text, { head = false, w, align } = {}) => new TableCell({
  borders: BORDERS, margins: CELL_M, verticalAlign: VerticalAlign.CENTER,
  width: { size: w, type: WidthType.DXA },
  shading: head ? { fill: HEAD_FILL, type: ShadingType.CLEAR } : undefined,
  children: [new Paragraph({
    alignment: align ?? (head ? AlignmentType.CENTER : AlignmentType.LEFT),
    children: [new TextRun({ text: String(text), bold: head, size: 18, font: FONT })],
  })],
});

/** rows[0] = 헤더. widths 합 = CONTENT_W */
const TBL = (widths, rows, aligns) => new Table({
  width: { size: CONTENT_W, type: WidthType.DXA },
  columnWidths: widths,
  rows: rows.map((r, ri) => new TableRow({
    tableHeader: ri === 0,
    children: r.map((c, ci) => cell(c, { head: ri === 0, w: widths[ci], align: aligns?.[ci] })),
  })),
});

const CAPTION = (t) => new Paragraph({
  spacing: { before: 70, after: 220 },
  alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: t, size: 17, color: '595959', font: FONT })],
});

// ── 표지 ─────────────────────────────────────────────────────────────────────
const coverInfo = [
  ['과제번호', '「기재 필요」'],
  ['연구개발기간', '「기재 필요」'],
  ['연구단계 / 당해연도', '「기재 필요」'],
  ['주관연구기관', '(주)이암허브 (Iamhub Inc.)'],
  ['협동연구기관', '한국스마트농업AI협회'],
  ['연구책임자', '「기재 필요」'],
  ['총연구개발비 / 당해연도', '「기재 필요」'],
];

const cover = [
  new Paragraph({ spacing: { before: 900, after: 120 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '연구개발과제 중간보고서', bold: true, size: 44, font: FONT })] }),
  new Paragraph({ spacing: { after: 900 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '(Interim Report)', size: 24, color: '595959', font: FONT })] }),
  new Paragraph({ spacing: { after: 100 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '빅데이터 및 생성형 AI 기반 주요 스마트팜 작목', bold: true, size: 32, font: FONT })] }),
  new Paragraph({ spacing: { after: 100 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '경영성과 제고 모델검증 플랫폼 구축 및', bold: true, size: 32, font: FONT })] }),
  new Paragraph({ spacing: { after: 800 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '경영성과 달성 방안 제시', bold: true, size: 32, font: FONT })] }),
  TBL([3400, 6238], [['구분', '내용'], ...coverInfo]),
  new Paragraph({ spacing: { before: 900, after: 100 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: FACTS.report_month, size: 24, font: FONT })] }),
  new Paragraph({ spacing: { after: 700 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '주관연구기관 : (주)이암허브 · 협동 : 한국스마트농업AI협회', size: 20, font: FONT })] }),
  new Paragraph({ alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '농 촌 진 흥 청', bold: true, size: 30, font: FONT })] }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── 요약문 ───────────────────────────────────────────────────────────────────
const S = FACTS.stack;
const G = FACTS.gate;
const summary = [
  new Paragraph({ spacing: { after: 260 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '국 문 요 약 문', bold: true, size: 30, font: FONT })] }),
  P('본 과제는 빅데이터와 생성형 AI를 결합하여 주요 스마트팜 작목의 경영성과를 제고하는 ‘모델검증 플랫폼’을 구축하고, 실증 데이터에 근거한 경영성과 달성 방안을 제시하는 것을 목적으로 한다. 당해연도에는 시설원예·노지 13개 작목을 대상으로 3계층(농진청 표준→광역 학습→농장 맞춤) 예측·처방 체계를 설계·구현하고, 모델 성능을 자동 검증·승격·폴백하는 파이프라인과 이를 농가가 현장에서 사용하는 모바일·관제 플랫폼(farmingsight.org)을 실증 운영하였다.', { after: 180 }),
  P(`핵심 성과로 ① ${S.screens}개 화면·${S.routers}개 API 라우터·${S.services}개 도메인 서비스로 구성된 통합 플랫폼을 완성하고, ② 주요 시설작목의 수확량 예측 모델을 검증하여 딸기·오이에서 MAPE 17.8~22.8%의 실용 정확도를 확보하였으며(일부 작목은 소표본·표준기상 의존으로 상위 계층 폴백), ③ 다지표 게이트(MAPE·CV R²·표본수·과적합 가드)와 드리프트 감시·재학습 어드바이저로 이어지는 모델 신뢰성 검증 체계를 단일 정책 모듈(pipeline/gates.py)로 통합하였다.`, { after: 180 }),
  P(`또한 ④ Priva·Grodan·Plant Empowerment 벤치마크에 기반한 환경관리 전략표(G2)와 P1~P6 정밀 관수 제어로 경영성과 달성 방안을 구체화하고, ⑤ 생성형 AI 컨설팅의 근거 신뢰성을 확보하기 위해 영농기술 지식베이스(${FACTS.kb.total}개 지식 단위)를 구축하여 답변에 출처·쪽수를 명시하는 근거 제시형 상담 체계를 구현하였다.`, { after: 180 }),
  P('본 보고서는 상기 당해연도 추진 내용과 정량·정성 성과, 목표 달성도, 그리고 차년도 연구·확산 계획을 기술한다.', { after: 260 }),
  P('주제어 : 스마트팜, 생성형 AI, 빅데이터, 수확량 예측, 모델검증, 경영성과, 정밀관수, 환경관리 전략, 디지털 컨설팅, 지식베이스, 근거 제시형 AI', { size: 19 }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { after: 200 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '목       차', bold: true, size: 30, font: FONT })] }),
  new TableOfContents('목차', { hyperlink: true, headingStyleRange: '1-3' }),
  P('※ 목차 페이지 번호는 Word에서 [참조]→[필드 업데이트]로 갱신됩니다.', { size: 17, color: '808080' }),
];

// ── 제1장 ────────────────────────────────────────────────────────────────────
const ch1 = [
  H('제1장  연구개발과제의 개요', HeadingLevel.HEADING_1),
  H('제1절  연구개발의 필요성', HeadingLevel.HEADING_2),
  BULLET('스마트팜 보급 확대에도 불구하고 수집 데이터가 ‘환경 모니터링’에 머물러, 실제 농가 소득으로 이어지는 경영성과(수확량·품질·수익) 예측과 처방으로 연결되지 못하는 한계가 상존함.'),
  BULLET('작목·농장별 재배 편차가 커 단일 표준모델의 정확도가 낮고, 농가는 예측 결과를 신뢰하기 어려워 의사결정에 활용하지 못함 → 모델의 ‘검증’과 ‘설명’이 전제되어야 현장 수용성이 확보됨.'),
  BULLET('생성형 AI의 등장으로 복잡한 환경·생육·시세 데이터를 농가가 이해할 수 있는 처방 언어로 변환하는 것이 가능해졌으나, 근거 없는 답변(환각) 위험을 통제하는 도메인 지식 결합·규칙 기반 폴백 설계가 필요함.'),
  BULLET('따라서 ‘빅데이터 기반 예측 + 모델 자동검증 + 생성형 AI 처방 + 경영성과 관리’를 하나의 폐루프로 통합하는 플랫폼과, 이를 통한 경영성과 달성 방안의 제시가 요구됨.'),

  H('제2절  연구개발의 목적 및 목표', HeadingLevel.HEADING_2),
  P('목적 : 주요 스마트팜 작목을 대상으로 빅데이터·생성형 AI 기반 경영성과 제고 ‘모델검증 플랫폼’을 구축하고, 실증 데이터에 근거한 경영성과 달성 방안을 제시한다.', { bold: true, after: 160 }),
  P('정성적 목표', { bold: true, after: 80 }),
  BULLET('작목별 3계층 예측·처방 모델 체계 설계 및 자동 검증·승격·폴백 파이프라인 구축'),
  BULLET('환경·관수·생육·경영 KPI 통합 진단과 생성형 AI 처방 제공'),
  BULLET('농가용 모바일 서비스 + 다농가 관제 콘솔 실증 운영'),
  P('정량적 목표 (당해연도)', { bold: true, after: 80 }),
  TBL([3200, 2200, 4238], [
    ['세부 목표 지표', '목표치', '비고'],
    ['대상 작목 수(예측·처방)', '「목표 기재」', '협약서 기준'],
    ['수확량 예측 정확도(MAPE)', '「목표 기재」', `게이트 MAPE≤${G.mape_serve}%·CV R²≥${G.cv_r2_min}`],
    ['모델검증 파이프라인 구축', '「목표 기재」', '검증·드리프트·재학습'],
    ['플랫폼 화면·기능 구현', '「목표 기재」', '모바일+콘솔'],
    ['생성형 AI 상담 근거 체계', '「목표 기재」', '지식베이스·출처 인용'],
    ['실증 농가·운영 지표', '「목표 기재」', '실증 서비스'],
  ]),
  CAPTION('표 1. 당해연도 정량적 목표(목표치는 협약서에 따라 기재) — 달성 실적은 제4장 참조'),

  H('제3절  연구개발의 범위 및 추진체계', HeadingLevel.HEADING_2),
  BULLET('데이터 : 농진청 표준생육·소득조사 자료, 기상(KMA/ERA5), 시세(KAMIS), 센서(환경·관수·생육) 및 농가 입력 데이터'),
  BULLET('작목 범위 : 시설원예 6종(딸기·방울토마토·완숙토마토·오이·파프리카·참외) + 제주 노지 7종 = 총 13종'),
  BULLET('모델 범위 : M1(생육)·M2(수확량)·M5(병해) 3종, 각 작목별 3계층(표준→학습→맞춤) 구조'),
  BULLET('지식 범위 : 스마트농업컨설턴트 교재(재배·병해충·환경) 및 제품 도메인 규칙(관수 P1~P6·임계값)의 지식베이스화'),
  BULLET('플랫폼 범위 : 농가 모바일 서비스, 다농가 관제 콘솔, 예측·검증·처방 API, 배포·운영 인프라'),
  BULLET('추진체계 : 주관 (주)이암허브(플랫폼·모델·서비스 개발) — 협동 한국스마트농업AI협회(도메인 지식·실증·검증) 협업체계로 수행함.'),
];

// ── 제2장 ────────────────────────────────────────────────────────────────────
const ch2 = [
  H('제2장  국내외 기술개발 현황', HeadingLevel.HEADING_1),
  H('제1절  국외 현황', HeadingLevel.HEADING_2),
  BULLET('환경·관수 정밀제어 : Priva(광연동 승온), Grodan(슬랩 함수율·EC 기반 관수), Plant Empowerment(VPD 밴드·6단계 관수전략) 등이 데이터 기반 재배전략을 상용화하였으나, 예측·경영성과 연계는 제한적임.'),
  BULLET('생육·수확 예측 : Hoogendoorn·Autonomous Greenhouse Challenge 등에서 AI 재배 자동화가 시도되나, 고비용·대형 유리온실 중심으로 국내 중소농 적용성이 낮음.'),
  BULLET('생성형 AI : 대규모 언어모델의 농업 상담 적용이 확산되고 있으나, 도메인 데이터 결합·검증 없는 답변의 신뢰성 문제가 대두됨. 검색 증강(RAG)으로 근거를 제시하는 방식이 표준으로 자리잡는 추세임.'),

  H('제2절  국내 현황', HeadingLevel.HEADING_2),
  BULLET('농진청 표준생육·소득조사 체계가 작목별 기준값을 제공하나, 농장 맞춤 예측과 실시간 처방으로의 연결은 미흡함.'),
  BULLET('스마트팜 혁신밸리·통신사 플랫폼이 환경 모니터링·원격제어를 제공하나, 경영성과(수익) 관점의 진단·컨설팅 기능은 부족함.'),

  H('제3절  시사점 및 본 과제의 차별성', HeadingLevel.HEADING_2),
  BULLET('표준→학습→맞춤 3계층 설계로 데이터가 적은 초기에도 농진청 표준을 폴백으로 활용 — 정확도·신뢰성 양립.'),
  BULLET('모델 자동 ‘검증’(게이트)·드리프트 감시·재학습을 내장 — 예측을 신뢰 가능한 의사결정 근거로 승격.'),
  BULLET('생성형 AI 처방을 자사 교재·도메인 규칙 지식베이스에 정합시키고 답변에 출처·쪽수를 명시 — 환각 통제, 근거 제시형 컨설팅.'),
  BULLET('예측·검증·처방·경영관리·유통을 하나의 가치사슬로 연속화 — 경영성과까지 이어지는 폐루프.'),
];

// ── 제3장 ────────────────────────────────────────────────────────────────────
const m2rows = FACTS.m2.map(r => [
  r.crop, `${r.mape.toFixed(1)}%`, r.cv_r2 == null ? '—' : r.cv_r2.toFixed(3),
  String(r.n_train), r.model, r.label,
]);

const ch3 = [
  H('제3장  연구개발 수행 내용 및 결과', HeadingLevel.HEADING_1),

  H('제1절  경영성과 제고 모델검증 플랫폼 구축', HeadingLevel.HEADING_2),
  H('1. 시스템 아키텍처', HeadingLevel.HEADING_3),
  P('농가용 모바일 서비스와 다농가 관제 콘솔을 단일 백엔드(FastAPI) 위에 구성하고, 예측·검증·처방을 API로 제공한다. 컨테이너(Docker) 기반으로 배포하며, 공개 도메인(farmingsight.org)에서 실증 운영한다.'),
  TBL([2200, 7438], [
    ['구성 요소', '내용'],
    ['프론트엔드', `모바일 HTML ${S.screens}개 화면(PWA), 다농가 관제 콘솔, 가치사슬 스테퍼`],
    ['백엔드', `FastAPI — ${S.routers}개 라우터(농가·관리자·인증·연합학습 등), ${S.services}개 도메인 서비스`],
    ['AI/모델', '3계층 예측(M1·M2·M5), 검증 게이트(단일 정책 모듈), 드리프트 감시, 재학습 어드바이저'],
    ['AI 지식', `영농기술 지식베이스 ${FACTS.kb.total}개 단위 + BM25 검색 → 답변 근거·출처 제시`],
    ['데이터', '농진청 표준·KAMIS 시세·기상·센서·농가입력(작물 registry, 진단·장비 DB)'],
    ['인프라·배포', 'Docker(TimescaleDB·Redis·API), Cloudflare 터널, Ubuntu 서버 실증 운영'],
  ]),
  CAPTION('표 2. 플랫폼 시스템 아키텍처 구성'),

  H('2. 3계층 AI 모델 체계', HeadingLevel.HEADING_3),
  P('데이터 축적 단계에 따라 정확도와 신뢰성을 양립시키기 위해 3계층 구조를 채택하였다.'),
  TBL([1400, 2600, 5638], [
    ['계층', '명칭', '설명'],
    ['0계층', '농진청 표준', '작목별 표준생육·소득 기준값(초기·폴백 기준)'],
    ['1계층', 'KAASA 광역 학습', '다농가 빅데이터 학습 모델(지역·작기 일반화)'],
    ['2계층', '내 농장 맞춤', '농장 실측 누적 시 개인화(정확도 자동 향상)'],
  ]),
  CAPTION('표 3. 3계층 모델 구조 (M1 생육·M2 수확량·M5 병해에 공통 적용)'),

  H('3. 모델 검증·드리프트·재학습 체계 (핵심)', HeadingLevel.HEADING_3),
  P('당해연도에는 검증 정책이 여러 모듈에 흩어져 서로 다른 임계를 쓰던 문제를 해소하기 위해, 게이트 판정을 단일 정책 모듈(pipeline/gates.py)로 통합하고 모든 승격·서빙 경로가 이를 참조하도록 하였다. 판정 기준은 다음과 같다.', { after: 140 }),
  TBL([2600, 1700, 5338], [
    ['판정', '조건', '조치'],
    ['검증 적용(serve)', `MAPE ≤ ${G.mape_serve}% 이고 CV R² ≥ ${G.cv_r2_min}`, '2계층(농장 맞춤) 모델을 서비스에 적용'],
    ['조건부(conditional)', `MAPE ${G.mape_serve}~${G.mape_fallback}% 또는 CV R² < ${G.cv_r2_min}`, '서비스하되 데이터 확충·재학습 보완 대상'],
    ['폴백(fallback)', `MAPE > ${G.mape_fallback}%`, '상위 계층(농진청 표준/광역)으로 자동 폴백'],
  ]),
  CAPTION(`표 4. M2 수확량 모델 검증 게이트 판정 기준 (단일 출처: pipeline/gates.py)`),
  BULLET(`과적합 가드 : |train R² − CV R²| > ${G.overfit_gap} 이면 조건부로 강등하여 과적합 모델의 서비스 적용을 차단한다.`),
  BULLET(`소표본 경고 : n_train < ${G.n_min} 인 작목은 경고 플래그를 부여하고 농장단위 LOGO(Leave-One-Group-Out) 교차검증으로 재판정 대상에 포함한다. 소표본은 CV R²가 낙관적으로 나오는 편의가 있어 지표만으로 승격하지 않는다.`),
  BULLET('교차검증(CV) : 작목별 CV R²로 일반화 성능을 확인하고, 표준기상 과의존 등 과적합 모델을 배제한다.'),
  BULLET('드리프트 감시 : 입력 분포·오차 변화를 모니터링하여 성능 저하(RED) 시 경보·재학습 후보로 표시.'),
  BULLET('재학습 어드바이저 : 임계 초과 시 재학습을 ‘제안’하고 관리자 승인으로 반영(공개 데모 환경은 쓰기 차단으로 무결성 보장).'),
  BULLET('지표 권위 : 동일 지표가 registry·pipeline_meta·모델 내부에 중복 존재하여 값이 어긋나는 문제가 있었고, 검증 산출물(stage2_meta.json)을 유일한 권위로 확정하여 보고·서빙이 같은 값을 쓰도록 정리하였다.'),

  H('4. 작목별 수확량(M2) 모델 검증 결과', HeadingLevel.HEADING_3),
  P('주요 시설작목의 수확량 예측 모델을 검증 권위 파일(stage2_meta) 기준으로 평가하고, 상기 게이트로 판정한 결과는 다음과 같다.'),
  TBL([1500, 1300, 1300, 1300, 1800, 2438], [
    ['작목', 'MAPE', 'CV R²', '표본수(n)', '모델', '판정'],
    ...m2rows,
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER]),
  CAPTION('표 5. 주요 시설작목 M2 수확량 모델 검증 결과 (models/artifacts/*/stage2_meta.json 권위값 기준)'),
  BULLET('딸기·오이는 MAPE 17.8~22.8%로 실용 수준을 확보 — 현장 수확량 예측·의사결정 활용 가능.'),
  BULLET('파프리카(29.2%)·완숙토마토(28.1%)는 경계 수준으로 조건부 적용(완숙은 CV R² 0.099로 설명력 부족) → 데이터 확충·재학습 보완 대상.'),
  BULLET('방울토마토(48.6%)·참외(63.9%)는 소표본(n<50)에서 상대오차가 확대되어 폴백 임계를 초과 → 상위 계층(농진청 표준/광역)으로 폴백하여 예측 안정성을 유지.'),
  BULLET('오이·파프리카·방울토마토·참외는 표본수가 게이트 경고 임계(n<60) 미만으로, 높은 CV R²에 낙관편의 소지가 있어 LOGO 교차검증 재판정을 차년도 과제로 둔다.'),

  H('제2절  경영성과 달성 방안', HeadingLevel.HEADING_2),
  H('1. 환경관리 전략표(G2) 기반 처방', HeadingLevel.HEADING_3),
  P('생육시기(정식 기준)×하루 4구간(야간·일출·주간·일몰전)의 2축 전략표에 온도·습도·CO₂ 목표(VPD 자동 계산)를 정의하고, 실측 편차를 진단해 AI 처방을 생성한다. Priva 광연동 승온, HNT 24시간 평균, Plant Empowerment VPD 밴드를 벤치마크로 반영한다.'),
  P('당해연도에는 스마트농업컨설턴트 교재의 작목별 환경 제어값 기준표를 근거로 완숙토마토·방울토마토·오이·파프리카 4개 작목의 생육단계별 24시간 평균기온·VPD 권장 밴드를 확정하여 전략표에 반영하였다. 기준표 24행을 검증한 결과 22행은 정합하였고 2행은 원본 손상으로 확인되어 적용에서 제외하였다.'),
  TBL([2000, 3819, 3819], [
    ['작목', '적용 범위', '비고'],
    ['완숙토마토', '착과·개화기, 수확기', '활착·생장기 값은 원본 손상으로 제외'],
    ['방울토마토', '활착기~수확기 전 단계', '—'],
    ['오이', '활착기~수확기 전 단계', '—'],
    ['파프리카', '활착기~수확기 전 단계', '—'],
    ['딸기', '적용 보류', '교재(일반재배)와 제품 기준(겨울 촉성)의 전제가 달라 도메인 검토 후 반영'],
  ]),
  CAPTION('표 6. 교재 기준 작목별 환경 권장 밴드 적용 현황'),

  H('2. 정밀 관수 P1~P6 Period 제어', HeadingLevel.HEADING_3),
  P('Priva·Grodan 기준의 6단계 관수 Period를 정의하고, 일사 적산(J/cm²)을 우선 트리거로 사용한다.'),
  TBL([1100, 3300, 5238], [
    ['구간', '시간대', '핵심 지표'],
    ['P1', '일출 전(05:00~07:00)', 'EC/pH 기준값, 야간 dry-back 10~20%'],
    ['P2', '첫 관수·재포화(일출+2~3h)', '급액량 슬랩 4~6%, 배액 前'],
    ['P3', '오전 첫 배액(≈400 J/cm²)', '배액률 20~30%, VPD'],
    ['P4', '정오 고부하(12:00~15:00)', '함수율 64~65%, 12%↓ 즉시 추가'],
    ['P5', '오후 dry-down(15:00~일몰)', 'dry-back 2~5%, EC 상향'],
    ['P6', '야간 dry-back(일몰~05:00)', 'dry-back 10~20%, 무관수 기본'],
  ], [AlignmentType.CENTER]),
  CAPTION('표 7. P1~P6 관수 Period 정의 (트리거: 일사 적산 우선, 시각은 폴백)'),

  H('3. 핵심 경영·생육 KPI 체계', HeadingLevel.HEADING_3),
  BULLET('DLI : PAR 계수 4.57(mol/m²·d) 적용 — 광량 기반 생육 진단'),
  BULLET('VPD 밴드 : 0.4 kPa(하한)~0.6 kPa(상한) — 증산·병해 관리'),
  BULLET('배액률 : 정상 20~35%, 위험 15/45% — 근권 수분·양분 관리'),
  TBL([2400, 1800, 2600, 2838], [
    ['항목', '단위', '정상', '경보'],
    ['급액 EC', 'dS/m', '2.5~3.5', '>4.0 또는 <2.0'],
    ['배액 EC', 'dS/m', '3.0~4.5', '>5.0'],
    ['배액률', '%', '20~30', '<15 또는 >40'],
    ['급액 pH', '—', '5.5~6.5', '<5.0 또는 >7.0'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER]),
  CAPTION('표 8. G3 관수 센서 정상·경보 범위'),

  H('4. 생성형 AI 컨설팅 — 근거 제시형 상담 체계', HeadingLevel.HEADING_3),
  P('생성형 AI 상담의 최대 위험은 근거 없는 답변(환각)이다. 당해연도에는 이를 통제하기 위해 자사 보유 지식을 검색 가능한 지식베이스로 구축하고, 답변이 그 근거만 인용하도록 결합하였다.', { after: 140 }),
  TBL([2600, 1300, 5738], [
    ['지식 원천', '지식 단위', '내용'],
    ['스마트농업컨설턴트 교재', `${FACTS.kb.textbook}개`, '병해충 진단·환경 관리·작목별 재배 기준(449쪽을 의미 단위로 분할)'],
    ['제품 도메인 규칙', `${FACTS.kb.rules}개`, 'P1~P6 관수 Period·일사 적산 트리거·PDCA 임계값·VPD 계산·작목별 권장 밴드'],
    ['합계', `${FACTS.kb.total}개`, '—'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT]),
  CAPTION('표 9. 영농기술 지식베이스 구성'),
  BULLET('상보성 : 교재는 병해충·환경에 강하나 관수 정밀제어 지식(배액률·dry-back·일사 적산·P1~P6)이 전혀 없고, 제품 규칙에는 병해충이 없다. 두 원천을 결합해야 상담 범위가 완성된다.'),
  BULLET('단일 출처 원칙 : 제품 규칙은 손으로 옮겨 적지 않고 규칙이 사는 코드에서 자동 추출한다. 코드가 바뀌면 재생성만으로 지식베이스가 따라오므로 지식과 구현이 어긋나지 않는다.'),
  BULLET('검색 : 별도 임베딩·벡터DB 없이 BM25 방식으로 구현하여 외부 LLM 서비스 장애·비용과 무관하게 동작한다. 한국어 조사 문제는 문자 단위 색인으로 해소하였다.'),
  BULLET('근거 결합 : 질문에 해당하는 지식을 검색해 AI 프롬프트에 근거로 제공하고, 답변에 근거 번호와 출처·쪽수를 명시하도록 강제한다. 검색 결과가 없으면 근거가 없음을 밝히고 단정하지 않는다.'),
  BULLET('정직성 : 답변에 표기되는 출처는 실제로 사용한 근거만으로 한정한다. 무관한 질의에는 자료를 붙이지 않도록 최소 관련도 기준을 두었다.'),
  BULLET('안전 : 농약·방제 권고 시 등록 정보(PLS 적용작물·희석배수·안전사용기준) 확인 문구를 강제하고, 병해 진단이 확정 진단이 아님을 명시한다.'),
  BULLET('연속성 : LLM 미설정·오류 시에도 규칙 기반 응답과 지식베이스 원문 발췌를 제공하여 상담 서비스가 중단되지 않는다.'),

  H('5. 경영관리·가치사슬 연속화', HeadingLevel.HEADING_3),
  BULLET('ERP 소득구조 : 농가 조사표 13항목 비용 상세·소득구조 폭포수 분석으로 수익성 진단.'),
  BULLET('PDCA 적기적작 : 적기적작 3대 지수·PDCA 루프·임계 알림으로 운영 개선.'),
  BULLET('벤치마킹·공동경영 : 농가 간 성과 비교 및 공동출하(pool·joint)로 유통 단계 경영성과 제고.'),
  BULLET('가치사슬 연속화 : 생산→경영→유통 단계를 자동 제안·넘김으로 연결 → 예측이 경영성과 실행으로 이어짐.'),

  H('제3절  실증 서비스 운영', HeadingLevel.HEADING_2),
  BULLET('공개 도메인 farmingsight.org에서 모바일 서비스·관제 콘솔을 상시 운영(PWA·오프라인 대응·자동 복구).'),
  BULLET('당해연도 중 운영 환경을 상시 가동 서버(Ubuntu·컨테이너)로 이전하여 가용성을 확보하고, Cloudflare 터널 기반 무중단 운영 체계를 구축.'),
  BULLET('공개 데모 모드에서는 관리자 쓰기(재학습·알림·설정)를 차단하여 데이터 무결성과 시연 안정성을 동시 확보.'),
  BULLET('운영 중 예측 서빙 경로를 점검하여 모델 산출물이 실제로 적재·서빙되는지 검증하는 절차를 배포 과정에 포함시켰다(산출물 누락 시 조용한 폴백을 방지).'),
];

// ── 제4장 ────────────────────────────────────────────────────────────────────
const ch4 = [
  H('제4장  목표 달성도 및 기여도', HeadingLevel.HEADING_1),
  H('제1절  정량적 목표 달성도', HeadingLevel.HEADING_2),
  TBL([2800, 1600, 3400, 1838], [
    ['세부 목표', '목표치', '당해연도 실적', '달성도'],
    ['모델검증 플랫폼 구축', '「기재」', `화면${S.screens}·라우터${S.routers}·서비스${S.services} 완성`, '달성'],
    ['수확량 예측 정확도(MAPE)', '「기재」', '딸기17.8·오이22.8%(적용)', '부분 달성'],
    ['모델 자동검증 파이프라인', '「기재」', '게이트 단일화·드리프트·재학습', '달성'],
    ['대상 작목', '「기재」', '13종(시설6+노지7)', '달성'],
    ['생성형 AI 상담 근거 체계', '「기재」', `지식베이스 ${FACTS.kb.total}단위·출처 인용`, '달성'],
    ['실증 서비스 운영', '「기재」', 'farmingsight.org 상시운영', '달성'],
  ], [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.LEFT, AlignmentType.CENTER]),
  CAPTION('표 10. 정량적 목표 달성도(목표치는 협약서에 따라 기재, 실적은 당해연도 실측)'),

  H('제2절  정성적 성과 및 기여도', HeadingLevel.HEADING_2),
  BULLET('기술적 : 3계층·게이트·드리프트·재학습으로 이어지는 ‘검증된 예측’ 체계와, 출처를 제시하는 근거 기반 AI 상담 체계를 실증 — 스마트팜 AI의 현장 신뢰성 문제 해결에 기여.'),
  BULLET('경제적 : 환경·관수·경영 처방과 공동경영으로 수량·품질·수익 제고 경로 제시 — 농가 경영성과 달성 방안 구체화.'),
  BULLET('산업적 : 중소농도 사용 가능한 모바일·PWA 플랫폼과 외부 LLM 비용에 의존하지 않는 지식 검색 구조로 스마트농업 AI의 보급·확산 기반 마련.'),
  BULLET('지식자산화 : 자사 교재·현장 규칙을 검색 가능한 지식 자산으로 전환하고 코드와 동기화되도록 설계 — 지속 축적 가능한 컨설팅 기반 확보.'),
];

// ── 제5장 ────────────────────────────────────────────────────────────────────
const ch5 = [
  H('제5장  연구개발 결과의 활용계획', HeadingLevel.HEADING_1),
  H('제1절  차년도(후속) 연구계획', HeadingLevel.HEADING_2),
  BULLET('게이트 미통과 작목(방울토마토·참외)의 실측 데이터 확충·재학습으로 정확도 제고, M1 토마토 계열 과적합 개선(ERA5 실측 확보).'),
  BULLET('소표본 작목(오이·파프리카·방울토마토·참외)의 농장단위 LOGO 교차검증 재판정으로 낙관편의 제거.'),
  BULLET('지식베이스 확충 : 농진청 재배지침·병해충 DB(NCPMS) 등 공공 지식 연계와 의미 기반 검색(임베딩) 도입으로 검색 정확도 제고.'),
  BULLET('딸기 환경 권장 밴드의 재배형(겨울 촉성 vs 일반재배) 전제 정리 후 반영 — 도메인 전문가 검토 필요.'),
  BULLET('실증 농가 확대를 통한 2계층(농장맞춤) 개인화 성능 검증 및 경영성과(수량·수익) 개선 효과 계량화.'),

  H('제2절  실증·확산 및 사업화 방안', HeadingLevel.HEADING_2),
  BULLET('주요 작목·지역 실증 농가 확대 및 공동경영(공동출하) 연계로 유통 단계 성과 실증.'),
  BULLET('농진청 표준체계·소득조사 연계 표준화로 정책·보급 사업 활용.'),
  BULLET('SaaS형 서비스(플랜·구독) 및 컨설팅 리포트 제공으로 사업화 추진.'),
  BULLET('지식베이스 기반 상담·교육 콘텐츠를 협동기관(한국스마트농업AI협회) 교육과정과 연계하여 확산.'),

  new Paragraph({ spacing: { before: 300, after: 200 },
    children: [new TextRun({ text: '※ 본 문서의 행정정보(과제번호·기간·연구비·연구책임자 등)와 정량 목표치는 협약서 기준으로 「」 표시 부분에 기재 후 제출하시기 바랍니다.', size: 18, color: '595959', font: FONT })] }),

  H('참고문헌', HeadingLevel.HEADING_1),
  P('[1] 농촌진흥청, 작목별 표준영농·소득조사 자료.'),
  P('[2] Priva, Plant Empowerment: The Basic Principles / Next Generation Growing.'),
  P('[3] Grodan, Precision Growing — Root-zone Water Content & EC Strategy.'),
  P('[4] aT KAMIS, 농산물 도·소매 가격정보.'),
  P('[5] 기상청(KMA)·ECMWF ERA5 재분석 자료.'),
  P('[6] (주)이암허브·한국스마트농업AI협회, 스마트농업컨설턴트 양성 교재, 2025.'),
  P('[7] Robertson & Zaragoza, The Probabilistic Relevance Framework: BM25 and Beyond, 2009.'),

  new Paragraph({ spacing: { before: 400 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '본 보고서의 저작권은 (주)이암허브와 한국스마트농업AI협회에 있음.', size: 18, color: '595959', font: FONT })] }),
];

// ── 문서 ─────────────────────────────────────────────────────────────────────
const doc = new Document({
  creator: '(주)이암허브 · 한국스마트농업AI협회',
  title: '빅데이터 및 생성형 AI 기반 주요 스마트팜 작목 경영성과 제고 모델검증 플랫폼 구축 및 경영성과 달성 방안 제시 — 중간보고서',
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
      reference: 'bullets',
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

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(`저장: ${OUT} (${buf.length.toLocaleString()} bytes)`);
});
