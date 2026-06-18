const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  Header, Footer, PageNumber, LevelFormat, TableOfContents, PageBreak,
} = require("docx");

const FONT = "맑은 고딕";
const NAVY = "1F3864", BLUE = "2E75B6", LBLUE = "D5E8F0", GREY = "F2F2F2";
const CW = 9360; // content width (US Letter, 1" margins)

const border = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
const borders = { top: border, bottom: border, left: border, right: border };

function styles() {
  return {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", next: "Normal",
        run: { size: 44, bold: true, color: NAVY, font: FONT },
        paragraph: { spacing: { after: 120 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, color: NAVY, font: FONT },
        paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: BLUE, space: 2 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, color: BLUE, font: FONT },
        paragraph: { spacing: { before: 200, after: 90 }, outlineLevel: 1 } },
    ],
  };
}
const numbering = {
  config: [
    { reference: "b", levels: [
      { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 560, hanging: 280 } } } },
      { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 1040, hanging: 280 } } } },
    ]},
  ],
};

const P = (t, o = {}) => new Paragraph({ children: Array.isArray(t) ? t : [new TextRun({ text: t, ...o })], spacing: { after: 60 }, ...(o.p || {}) });
const B = (t, lvl = 0) => new Paragraph({ numbering: { reference: "b", level: lvl }, spacing: { after: 40 }, children: Array.isArray(t) ? t : [new TextRun(t)] });
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const run = (t, o = {}) => new TextRun({ text: t, font: FONT, ...o });

function cell(text, { w, head = false, bold = false, fill, align } = {}) {
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA },
    shading: { fill: fill || (head ? BLUE : "FFFFFF"), type: ShadingType.CLEAR },
    margins: { top: 60, bottom: 60, left: 110, right: 110 },
    children: [new Paragraph({
      alignment: align || AlignmentType.LEFT,
      children: (Array.isArray(text) ? text : [text]).map((s) =>
        new TextRun({ text: String(s), font: FONT, size: 19, bold: head || bold, color: head ? "FFFFFF" : "000000" })),
    })],
  });
}
function table(headers, rows, widths) {
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, { w: widths[i], head: true, align: AlignmentType.CENTER })) }),
      ...rows.map((r, ri) => new TableRow({
        children: r.map((c, i) => cell(c, { w: widths[i], fill: ri % 2 ? GREY : "FFFFFF" })),
      })),
    ],
  });
}

function section(children) {
  return {
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [run("KAASA smartfarmingsight", { size: 16, color: "888888" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [run("- ", { size: 16, color: "888888" }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "888888" }), run(" -", { size: 16, color: "888888" })] })] }) },
    children,
  };
}

function titleBlock(title, sub, meta) {
  const out = [
    new Paragraph({ spacing: { before: 240, after: 0 }, children: [run(title, { size: 44, bold: true, color: NAVY })] }),
    new Paragraph({ spacing: { after: 200 }, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: BLUE, space: 4 } },
      children: [run(sub, { size: 24, color: BLUE })] }),
  ];
  out.push(new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [1800, 2880, 1800, 2880],
    rows: meta.map((row) => new TableRow({ children: [
      cell(row[0], { w: 1800, fill: LBLUE, bold: true }), cell(row[1], { w: 2880 }),
      cell(row[2], { w: 1800, fill: LBLUE, bold: true }), cell(row[3], { w: 2880 }),
    ] })),
  }));
  out.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
  return out;
}

// ───────────────────────── 작업내역서 ─────────────────────────
function workLog() {
  const c = [];
  c.push(...titleBlock("작업 내역서", "스마트팜 기자재·시공업체 공식 데이터 통합 / C16 장비추가 개선",
    [["문서번호", "WR-2026-0618", "작성일", "2026-06-18"],
     ["프로젝트", "KAASA smartfarmingsight", "작성자", "개발팀"],
     ["대상 범위", "기자재 참조 DB·장비추가 화면", "도메인", "farmingsight.org"]]));

  c.push(H1("1. 작업 개요"));
  c.push(P("스마트팜코리아 공식 DB(231025, 250117판)를 도입하여 기자재·시공업체 정보를 공식 분류체계로 재분류하고, 재실행 가능한 빌드 파이프라인으로 지속 업그레이드 체계를 구축하였다. 아울러 장비추가(C16) 화면의 사용성을 개선하였다."));

  c.push(H1("2. 작업 항목 및 결과"));
  c.push(H2("2.1 기자재·시공업체 공식 참조 데이터 구축"));
  c.push(table(
    ["구분", "산출물", "내용"],
    [
      ["공식 분류체계", "equipment_taxonomy.json", "스마트팜 ICT 기자재 표준(표준 장치명) 5대분류 — 감지부(센서)·제어부(구동기)·양액관수·축산설비·기타"],
      ["자사제품", "vendor_products.json", "제조사 제품 312건(활용분야·표준장치명·모델·KC인증)"],
      ["기업 디렉터리", "vendors.json", "제조·유통·시공 기업 623개(사업분야·연락처·AS인원)"],
      ["시공업체", "construction_companies.json", "온실 시공업체 도급순위 97개(상호·주소·연락처·지역)"],
      ["메타", "_meta.json", "출처·버전(250117)·집계 기록"],
    ],
    [1500, 3260, 4600]));

  c.push(H2("2.2 공식 분류체계 재분류 결과"));
  c.push(table(
    ["대분류", "제품수", "표준 장치명"],
    [
      ["제어부(구동기)", "259", "환경제어기·환풍기·냉방기·안개분무·악취제거"],
      ["축산설비", "17", "급이기·사료빈·방역기·선별기·원유냉각"],
      ["기타·미분류", "16", "기타"],
      ["양액·관수", "15", "양액기·자동급수기"],
      ["감지부(센서)", "5", "생체정보수집기·체중기"],
    ],
    [2400, 1200, 5760]));

  c.push(H2("2.3 지속 업그레이드 파이프라인"));
  c.push(B("scripts/build_equipment_reference.py — DB 엑셀(xlsx) → JSON 멱등 변환 빌더"));
  c.push(B("신규 DB 배포 시 --src 경로만 교체해 재실행하면 참조 데이터 전량 자동 갱신"));
  c.push(B([run("실행: ", { bold: true }), run("python scripts/build_equipment_reference.py --src \"<새 DB.xlsx>\"", { font: "Consolas", size: 18 })]));

  c.push(H2("2.4 장비추가(C16) 화면 개선"));
  c.push(B("장비 불러오기(📋) 버튼 추가 — 견적서 업로드 영역 이동 + 파일 선택창 즉시 오픈"));
  c.push(B("이기종 연계(통신프로토콜·주소·포트·데이터포인트 매핑)를 접힘식 '다음 단계·선택'으로 분리 → 등록 진입장벽 완화"));
  c.push(B("통신 프로토콜 필수 해제, 최종 버튼 명칭 '장비 저장' → '✓ 장비 등록'"));
  c.push(B("서비스워커 캐시 v50 → v51 갱신"));

  c.push(H1("3. 형상 관리 이력 (Git)"));
  c.push(table(
    ["커밋", "일자", "내용"],
    [
      ["18457e5", "06-18", "기자재·시공업체 공식 참조 데이터 + 재생성 파이프라인"],
      ["05598f4", "06-18", "C16 장비추가 개선 — 불러오기 버튼·이기종 연계 분리·등록 버튼"],
      ["2606f89", "06-18", "C6 입력 데이터 품질 드리프트 신호 연계"],
      ["c941ae6", "06-18", "C13 AI비서 입력 이상치 선제 알림"],
      ["a26f52c", "06-17", "입력 이상치 자동 플래그 → C17 진단 연계"],
      ["b0f9aa2", "06-17", "F4 노지 관개량 이상치 경고"],
      ["00ab17f", "06-17", "G3 관수 입력 이상치 경고(EC·pH 가드)"],
      ["efac415", "06-17", "G2 환경 입력 이상치 경고"],
    ],
    [1300, 1100, 6960]));

  c.push(H1("4. 검증"));
  c.push(B("빌드 산출: vendor_products 312 / vendors 623 / construction 97 / 분류 5 — 정상 생성 확인"));
  c.push(B("C16 화면: 로컬 200 응답, sw.js v51 서빙, 불러오기 버튼 대상(#quoteFile) 존재 확인"));
  c.push(B("master 푸시 완료(origin/master), 라이브 farmingsight.org 반영"));
  return c;
}

// ───────────────────────── 작업계획서 ─────────────────────────
function workPlan() {
  const c = [];
  c.push(...titleBlock("작업 계획서", "기자재 참조 DB의 서비스 연동 및 지속 운영 고도화",
    [["문서번호", "WP-2026-0618", "작성일", "2026-06-18"],
     ["프로젝트", "KAASA smartfarmingsight", "작성자", "개발팀"],
     ["계획 기간", "2026-06-19 ~ 2026-07-31", "선행작업", "WR-2026-0618"]]));

  c.push(H1("1. 목적"));
  c.push(P("구축된 공식 기자재·시공업체 참조 데이터(WR-2026-0618)를 실제 서비스 화면·API에 연동하여, 농가가 장비 등록 시 공식 DB 기반으로 입력·검증·연계할 수 있도록 한다. 또한 DB 갱신을 정례화하여 데이터 신선도를 지속 유지한다."));

  c.push(H1("2. 추진 과제"));
  c.push(table(
    ["단계", "과제", "세부 내용", "산출물"],
    [
      ["1", "장비추가 자동완성", "C16에서 제조사·모델 입력 시 vendor_products 기반 자동완성·표준장치명 자동분류", "C16 + reference API"],
      ["2", "시공업체 찾기", "지역·도급순위로 온실 시공업체 검색 화면 신설", "신규 화면 + API"],
      ["3", "KC인증 표시", "등록 장비의 KC인증 상태(인증/미인증) 배지 노출", "C16·G3 배지"],
      ["4", "이기종 연계 단계", "표준 장치명↔표준변수 매핑을 연동 단계(C8)로 연결", "C8 매핑 UI"],
      ["5", "DB 갱신 정례화", "분기별 공식 DB 반영(빌더 재실행)·변경 이력 관리", "운영 절차서"],
    ],
    [700, 2000, 4660, 2000]));

  c.push(H1("3. 단계별 세부 계획"));
  c.push(H2("3.1 1단계 — 장비추가 자동완성 (우선순위 ★★★)"));
  c.push(B("reference API 신설: GET /api/reference/devices?q= (자사제품 검색), /vendors, /construction"));
  c.push(B("C16 제조사·모델 입력란에 자동완성 연결, 선택 시 표준 장치명·공식 대분류 자동 채움"));
  c.push(B("기대효과: 입력 오류 감소·표준 분류 일관성 확보"));

  c.push(H2("3.2 2단계 — 시공업체 찾기"));
  c.push(B("도급순위(1~2군)·지역(시·도) 필터 검색, 상호·연락처·주소 표시"));
  c.push(B("농장 세팅(C1) 흐름에서 시공업체 추천 연계"));

  c.push(H2("3.3 3단계 — KC인증 표시 / 4단계 — 이기종 연계"));
  c.push(B("등록 장비에 KC인증 배지 표시(미인증 경고)"));
  c.push(B("이기종 연계(C8): 표준 장치명 → 표준변수(canonical) 매핑 UI로 데이터포인트 연결"));

  c.push(H2("3.4 5단계 — DB 갱신 정례화"));
  c.push(B("분기 1회 공식 DB 최신판 확보 → 빌더 재실행 → 변경분 커밋"));
  c.push(B("_meta.json 버전 비교로 신규/변경 항목 추적"));

  c.push(H1("4. 일정 (마일스톤)"));
  c.push(table(
    ["기간", "마일스톤", "산출물"],
    [
      ["6월 4주", "1단계 자동완성 완료", "reference API + C16 연동"],
      ["7월 1~2주", "2단계 시공업체 찾기", "검색 화면 배포"],
      ["7월 3주", "3·4단계 KC인증·연계", "배지·C8 매핑"],
      ["7월 4주", "5단계 운영 정례화", "갱신 절차서"],
    ],
    [1600, 3760, 4000]));

  c.push(H1("5. 기대효과"));
  c.push(B("공식 DB 기반 표준화된 기자재 등록 → 데이터 품질·신뢰도 향상"));
  c.push(B("623개 기업·97개 시공업체 디렉터리 → 농가 의사결정 지원 확대"));
  c.push(B("멱등 빌더로 유지보수 비용 최소화, 데이터 신선도 지속 확보"));

  c.push(H1("6. 위험요소 및 대응"));
  c.push(table(
    ["위험", "대응"],
    [
      ["공식 DB 컬럼 구조 변경", "빌더 헤더 매핑 방어코드(_ci) — 누락 컬럼 무시 처리"],
      ["PUBLIC_DEMO 쓰기 게이트 충돌", "reference API는 읽기전용(GET) → 게이트 영향 없음"],
      ["대용량 JSON 로딩 지연", "서버측 검색 API로 분할 제공(전량 전송 회피)"],
    ],
    [3680, 5680]));
  return c;
}

async function build(name, children) {
  const d = new Document({ styles: styles(), numbering, sections: [section(children)] });
  const buf = await Packer.toBuffer(d);
  fs.writeFileSync(name, buf);
  console.log("written:", name, buf.length, "bytes");
}
const dir = process.argv[2] || ".";
(async () => {
  await build(dir + "/KAASA_작업내역서_20260618.docx", workLog());
  await build(dir + "/KAASA_작업계획서_20260618.docx", workPlan());
})();
