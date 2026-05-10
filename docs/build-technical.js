const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, LevelFormat, TableOfContents, PageBreak
} = require('docx');
const fs = require('fs');

const CONTENT_WIDTH = 9360;
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const hdrBorder = { style: BorderStyle.SINGLE, size: 8, color: "1F4E8C" };
const hdrBorders = { top: hdrBorder, bottom: hdrBorder, left: hdrBorder, right: hdrBorder };

function h1(text) { return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)] }); }
function h2(text) { return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] }); }
function h3(text) { return new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] }); }
function p(text, opts = {}) {
  return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text, font: "Arial", size: 22, ...opts })] });
}
function note(text) {
  return new Paragraph({
    spacing: { after: 80 }, indent: { left: 400 },
    children: [new TextRun({ text, font: "Arial", size: 20, color: "555555", italics: true })]
  });
}
function code(text) {
  return new Paragraph({
    spacing: { after: 40 },
    shading: { fill: "F0F4FA", type: ShadingType.CLEAR },
    indent: { left: 400, right: 400 },
    children: [new TextRun({ text, font: "Courier New", size: 18, color: "333333" })]
  });
}
function blank() { return new Paragraph({ spacing: { after: 80 }, children: [] }); }
function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children: [new TextRun({ text, font: "Arial", size: 22 })]
  });
}
function arrow(text) {
  return new Paragraph({
    numbering: { reference: "arrows", level: 0 },
    children: [new TextRun({ text, font: "Arial", size: 22 })]
  });
}

function tbl(headers, rows, colWidths, headerColor = "1F4E8C") {
  const total = colWidths.reduce((a, b) => a + b, 0);
  const hb = { style: BorderStyle.SINGLE, size: 8, color: headerColor };
  const hbs = { top: hb, bottom: hb, left: hb, right: hb };
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((h, i) => new TableCell({
          borders: hbs,
          width: { size: colWidths[i], type: WidthType.DXA },
          shading: { fill: headerColor, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: h, bold: true, color: "FFFFFF", font: "Arial", size: 20 })] })]
        }))
      }),
      ...rows.map((row, ri) => new TableRow({
        children: row.map((cell, i) => new TableCell({
          borders,
          width: { size: colWidths[i], type: WidthType.DXA },
          shading: { fill: ri % 2 === 0 ? "EFF4FB" : "FFFFFF", type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: cell, font: "Arial", size: 20 })] })]
        }))
      }))
    ]
  });
}

function sectionBox(label) {
  return new Paragraph({
    spacing: { before: 200, after: 100 },
    shading: { fill: "E8F0FE", type: ShadingType.CLEAR },
    indent: { left: 200, right: 200 },
    children: [new TextRun({ text: label, bold: true, font: "Arial", size: 22, color: "1F4E8C" })]
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: "1F4E8C" },
        paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "2E75B6", space: 4 } } }
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "2E75B6" },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 }
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "444444" },
        paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 2 }
      }
    ]
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial" } } }]
      },
      {
        reference: "arrows",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "→", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial" } } }]
      },
      {
        reference: "steps",
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial" } } }]
      }
    ]
  },
  sections: [{
    properties: {
      page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "2E75B6", space: 4 } },
          children: [new TextRun({ text: "스마트팜 수익성 향상 플랫폼 — 개발 진행 가이드", font: "Arial", size: 18, color: "666666" })]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 4 } },
          children: [
            new TextRun({ text: "v2.1  |  2026-04-29  |  ", font: "Arial", size: 18, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: "888888" }),
            new TextRun({ text: " 페이지", font: "Arial", size: 18, color: "888888" })
          ]
        })]
      })
    },
    children: [
      // Cover
      blank(), blank(),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 160 },
        children: [new TextRun({ text: "스마트팜 수익성 향상 플랫폼", font: "Arial", size: 56, bold: true, color: "1F4E8C" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 200 },
        children: [new TextRun({ text: "개발 진행 가이드 (개발팀용)", font: "Arial", size: 36, color: "2E75B6" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 120 },
        children: [new TextRun({ text: "1인 바이브코딩 프로젝트  |  무엇을 먼저 만들어야 하는가", font: "Arial", size: 22, color: "555555" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 400 },
        children: [new TextRun({ text: "2026-04-29  |  v2.1", font: "Arial", size: 20, color: "888888" })]
      }),
      blank(),
      new Paragraph({ children: [new PageBreak()] }),

      // TOC
      new TableOfContents("목차", { hyperlink: true, headingStyleRange: "1-2" }),
      new Paragraph({ children: [new PageBreak()] }),

      // 전체 구조
      h1("전체 시스템 구조 (큰 그림)"),
      p("이 플랫폼은 크게 3개 층으로 구성됩니다."),
      blank(),
      code("[ 화면층 ]  농가 대시보드 / 모바일 앱 / 관리 화면"),
      code("               |  데이터 주고받기"),
      code("[ 서버층 ]  AI 계산 + 데이터 처리 (예측 서버 7개 + 수집·전처리 서버)"),
      code("               |  저장·읽기"),
      code("[ 저장층 ]  센서 DB / 파일 저장소 / 빠른 캐시 공간"),
      blank(),
      h2("사용하는 주요 기술 모음"),
      tbl(
        ["용도", "기술 이름", "쉬운 설명"],
        [
          ["AI 모델 만들기", "PyTorch, XGBoost", "AI가 학습하는 엔진"],
          ["서버 만들기", "FastAPI", "화면과 AI를 연결하는 중간 서버"],
          ["데이터 자동 수집", "Airflow", "정해진 시간에 데이터를 자동으로 가져오는 스케줄러"],
          ["실시간 센서 연결", "MQTT", "IoT 센서 데이터를 받아오는 통신 방식"],
          ["시계열 데이터베이스", "TimescaleDB", "시간 순서대로 센서 데이터를 저장하는 데이터베이스"],
          ["파일 저장소", "AWS S3 / NHN OBS", "사진·AI 모델 파일을 보관하는 클라우드 창고"],
          ["빠른 임시 저장", "Redis", "AI 결과를 빠르게 꺼내기 위한 메모리 캐시"],
          ["AI 실험 기록", "MLflow", "어떤 AI 모델이 얼마나 잘했는지 기록·비교하는 도구"],
          ["데이터 버전 관리", "DVC", "데이터가 언제 어떻게 바뀌었는지 이력을 관리하는 도구"],
          ["서비스 모니터링", "Prometheus + Grafana", "서버가 잘 돌아가는지 실시간으로 보여주는 모니터"],
          ["프로그램 패키징", "Docker Compose", "여러 서버 프로그램을 한꺼번에 실행·관리하는 도구"],
          ["화면 (웹)", "React 18 + TypeScript", "대시보드 웹페이지를 만드는 프레임워크"],
          ["화면 (앱)", "React Native", "iOS·Android 앱을 하나의 코드로 만드는 도구"],
          ["GPU 서버", "NVIDIA A10G", "AI 모델 학습에 쓰는 고성능 그래픽 카드"],
        ],
        [2200, 2400, 4760]
      ),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // 개발 순서
      h1("개발 순서 한눈에 보기"),
      p("아래 순서대로 만들어 나가면 됩니다. 앞 단계가 완성돼야 다음 단계로 넘어갈 수 있습니다."),
      blank(),
      tbl(
        ["순서", "할 일", "기간", "비고"],
        [
          ["1단계", "인프라 & 개발환경 구축", "1~2주", "가장 먼저, 토대 만들기"],
          ["2단계", "데이터 자동 수집 연결", "2~6주", "데이터 흘러들어오게 만들기"],
          ["3단계", "데이터 정제 & 가공", "3~5주", "AI가 쓸 수 있도록 데이터 다듬기"],
          ["4단계", "병해 진단 AI (M5)", "4~10주", "가장 빠른 성과, 먼저 출시"],
          ["5단계", "생육 예측 AI (M1)", "6~12주", "핵심, 다른 AI들의 기반"],
          ["6단계", "생산량 + 수확시기 AI (M2·M3)", "8~16주", "M1 완성 후 연결"],
          ["7단계", "API 서버 구축", "4~8주", "화면과 AI를 연결하는 다리"],
          ["8단계", "농가 대시보드 베타 출시", "8~20주", "농가가 실제로 쓰는 화면"],
          ["9단계", "매출 추정 AI (M4)", "12~20주", "Phase 2 시작"],
          ["10단계", "에너지 절감 AI (M6)", "16~28주", "Phase 2~3"],
          ["11단계", "운영 자동화", "16~24주", "AI 스스로 재학습"],
          ["12단계", "모바일 앱", "16~28주", "스마트폰 앱"],
          ["13단계", "품질 예측 AI (M7)", "24~36주", "실측 데이터 쌓인 후"],
          ["14단계", "농가 확장 & 고도화", "30주+", ""],
        ],
        [1200, 3200, 1400, 3560]
      ),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 1
      h1("1단계. 인프라 & 개발환경 구축"),
      p("Phase 1  |  1~2주  |  가장 먼저 해야 할 일"),
      note("집을 짓기 전에 땅을 다지고 기초를 놓는 단계입니다. 이 단계가 없으면 아무것도 실행되지 않습니다."),
      blank(),
      h2("서버 & 실행 환경"),
      bullet("GPU 서버 준비 (AI 학습에 쓸 고성능 컴퓨터)"),
      bullet("Docker Compose*로 서버 프로그램들 한꺼번에 실행 설정"),
      bullet("NHN Cloud 또는 AWS에 서버 환경 구성 (국내 개인정보 규정 준수)"),
      bullet("GitHub Actions*으로 코드 바뀌면 자동 배포 설정"),
      blank(),
      h2("데이터 저장 공간 만들기"),
      bullet("TimescaleDB: 센서 데이터 저장용 데이터베이스 설치 및 테이블 구조 생성"),
      blank(),
      tbl(
        ["테이블명", "저장 내용"],
        [
          ["센서기록", "농가ID, 측정시각, 온도, 습도, CO2, 일사량, EC, pH"],
          ["생육기록", "농가ID, 작목, 날짜, 초장, 잎면적, 착과수, 건물중"],
          ["수확기록", "농가ID, 작목, 수확일, 무게(kg), 등급"],
          ["단가이력", "작목, 날짜, 경락가, 도매가"],
        ],
        [2400, 6960]
      ),
      blank(),
      bullet("파일 저장소(S3): 원본 데이터 → 가공 데이터 → AI 모델 파일 순서로 분류 보관"),
      bullet("Redis: AI 예측 결과를 빠르게 화면에 전달하기 위한 임시 보관 공간"),
      blank(),
      h2("AI 개발 도구 설치"),
      bullet("Python 3.11+ 및 AI 라이브러리 환경 설정"),
      bullet("MLflow: AI 모델 성능 기록·비교 서버 구축"),
      bullet("DVC: 학습 데이터가 언제 어떻게 바뀌었는지 이력 관리 설정"),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 2
      h1("2단계. 데이터 자동 수집 연결"),
      p("Phase 1  |  2~6주  |  즉시 착수"),
      note("데이터가 없으면 AI를 만들 수 없습니다. 파이프라인*을 먼저 열어 놓아야 합니다."),
      blank(),
      tbl(
        ["데이터", "어디서", "무엇을", "얼마나 자주", "어떻게"],
        [
          ["온실 센서", "5개 농가 IoT 기기", "온도·습도·CO2·일사량·EC·pH", "10분마다", "MQTT*로 실시간 수신"],
          ["농진청 생육 데이터", "농진청 공개 API", "4개 작목 환경·생육·생산량", "매일 오전 9시", "스케줄러 자동 수집"],
          ["시장 단가", "KAMIS 농산물유통정보", "경락가·도매가 (과거 5년 포함)", "매일 오전 6시", "스케줄러 자동 수집"],
          ["기상 데이터", "기상청", "지역별 연간 기상", "계절마다", "파일 다운로드 → 변환"],
          ["병해 이미지", "AI Hub", "딸기·토마토·참외 병든 작물 사진", "최초 1회", "다운로드 후 7:1.5:1.5 분류"],
          ["방울토마토 데이터", "WUR 네덜란드 연구소", "방울토마토 생육 데이터", "최초 1회", "다운로드 → 전처리"],
        ],
        [1600, 2000, 2200, 1400, 2160]
      ),
      blank(),
      h2("현장 데이터 추가 수집"),
      bullet("수확 기록 표준 양식 농가에 배포 (날짜·무게·등급 기록)"),
      bullet("데이터 문제 발생 시 신고 채널: 카카오톡 채널 운영"),
      bullet("Phase 3에 추가할 센서: 당도계 (굴절당도계), 전력계 (스마트전력계), 엽온센서"),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 3
      h1("3단계. 데이터 정제 & 가공"),
      p("Phase 1  |  3~5주"),
      note("수집된 날 것의 데이터에는 오류, 누락, 이상값이 많습니다. AI가 제대로 배울 수 있도록 데이터를 다듬는 단계입니다."),
      blank(),
      h2("데이터 정제 흐름"),
      arrow("이상값 제거 — 온도 0~60℃, 습도 0~100% 범위 밖이면 제거"),
      arrow("빈 값 채우기 — 30분 이내: 앞뒤 값으로 직선 보간 / 30분 초과: 비슷한 패턴의 데이터로 채우기 (KNN*)"),
      arrow("시간 단위 통합 — 10분 단위 → 시간 단위 → 일 단위로 합산"),
      arrow("시차 변수 만들기 — 7일 전 값, 14일 전 값, 온도 누적합 (GDD*) 계산"),
      arrow("값 범위 통일 (정규화*) — 작목별로 0~1 사이 값으로 변환해 AI가 비교하기 쉽게 만들기"),
      arrow("학습/검증/테스트 분리 — 8:1:1 비율 (마지막 작기는 반드시 테스트용으로 고정)"),
      arrow("S3 저장소에 버전 태그 달아서 보관"),
      blank(),
      h2("데이터가 부족할 때 보완 방법"),
      bullet("TOMGRO* 또는 EnergyPlus*로 가상 데이터 생성 (시뮬레이션)"),
      bullet("온도 ±2℃, 일사량 ±20% 범위에서 변형해 다양한 상황 데이터 생성"),
      bullet("TimeGAN*으로 시계열 데이터 추가 생성"),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 4
      h1("4단계. 병해 진단 AI (M5)"),
      p("Phase 1  |  4~10주  |  가장 먼저 출시 가능한 기능"),
      note("AI Hub에서 이미 학습된 모델을 가져와 우리 작목에 맞게 추가 학습만 하면 됩니다. 가장 빠르게 농가에 보여줄 수 있는 기능입니다."),
      blank(),
      h2("만드는 순서"),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "AI Hub에서 병해 진단 AI 모델 (EfficientNet-B4*) 다운로드", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "딸기·토마토·참외 병해 사진으로 추가 학습 (작목당 200장 이상)", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "환경 조건 기반 위험도 규칙 추가 (온도·습도가 일정 수준 넘으면 경보)", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "처방 내용 자동 생성 로직 구현 (방제 시기, 예상 손실률)", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "서버 컨테이너*로 패키징 후 배포", font: "Arial", size: 22 })] }),
      blank(),
      h2("입력 → 출력"),
      tbl(["입력", "출력"], [
        ["스마트폰으로 찍은 작물 사진", "병해 종류와 발생 확률"],
        ["온도·습도 최근 측정값", "방제 시기 권고"],
        ["", "예상 수확 손실률"],
        ["", "환경 위험도 신호등"],
      ], [4680, 4680]),
      blank(),
      h2("출시 기준 (이 기준을 넘어야 실제 농가에 배포)"),
      tbl(["기준", "목표"], [
        ["병해 감지 정확도 (F1*)", "88% 이상"],
        ["병이 있는데 못 잡는 비율 (위음성*)", "5% 이하"],
        ["전체 정확도", "92% 이상"],
      ], [4680, 4680]),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 5
      h1("5단계. 생육 예측 AI (M1) — 핵심 모듈"),
      p("Phase 1  |  6~12주  |  1순위"),
      note("다른 AI들(생산량·수확시기·품질)이 모두 이 모듈의 결과를 입력으로 사용합니다. 가장 공을 들여야 하는 핵심입니다."),
      blank(),
      h2("학습 순서 (이 순서를 반드시 지켜야 합니다)"),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "물리 모델 먼저 만들기: TOMGRO* (토마토·방울토마토·참외), DSSAT CROPGRO-Strawberry (딸기). 국내 품종에 맞게 수치 보정 (Optuna* 사용)", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "WUR 데이터로 AI 기초 학습 (사전학습*): LSTM* 2겹 구조, Dropout* 0.3 적용, 7일 전·14일 전 값·온도 누적합 변수 포함", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "5개 농가 데이터로 추가 학습 (파인튜닝*): 농가 1곳씩 빼고 학습, 빠진 농가로 검증 (Leave-one-out*)", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "예측 신뢰구간 계산 (MC Dropout*): 80%·95% 확률로 예측값이 들어오는 범위 산출", font: "Arial", size: 22 })] }),
      blank(),
      h2("입력 → 출력"),
      tbl(["입력", "출력"], [
        ["온도·습도·CO2·일사량·EC·pH", "초장·잎면적·착과수·건물중 예측값"],
        ["7일 전·14일 전 같은 값들", "생육 이상 점수"],
        ["온도 누적합 (GDD*)", "80%·95% 신뢰 범위"],
      ], [4680, 4680]),
      blank(),
      h2("출시 기준"),
      tbl(["Phase", "정확도 (R2*)", "오차율 (MAPE*)"], [
        ["Phase 1", "0.62 이상", "15% 이하"],
        ["Phase 3", "0.85 이상", "12% 이하"],
      ], [3120, 3120, 3120]),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 6
      h1("6단계. 생산량 + 수확시기 AI (M2·M3)"),
      p("Phase 1~2  |  8~16주  |  M1 완성 후 즉시 착수"),
      note("M1이 '지금 작물 상태가 이렇다'고 알려주면, M2·M3가 '그러면 언제 얼마나 수확되겠다'를 계산합니다."),
      blank(),
      h2("M2 — 생산량 예측"),
      tbl(["항목", "내용"], [
        ["방법", "XGBoost* + TOMGRO* 물리모델 조합"],
        ["입력", "M1 결과값 (잎면적·건물중·착과수), 누적 일사량, 정식 후 경과일"],
        ["출력", "주별 수확량 (kg/m2), 총 생산량 (kg), 증가·감소 방향 + 신뢰 범위"],
        ["출시 기준", "Phase 1: 오차율 25% 이하, 방향 예측 정확도 70% 이상"],
        ["데이터 부족하면", "TOMGRO 시뮬레이션 결과 사용 (±25% 오차임을 농가에 고지)"],
      ], [2400, 6960]),
      blank(),
      h2("M3 — 수확시기 예측"),
      tbl(["항목", "내용"], [
        ["방법", "딸기·참외: 온도 누적합(GDD*) + 생존분석* / 토마토: LSTM* 시계열"],
        ["입력", "착과 확인일, 온도 누적합, M1 생육 상태"],
        ["출력", "수확 예정일, 신뢰 범위 (±일), 수확 확률 분포"],
        ["출시 기준", "딸기·참외: ±5일 이내 (Phase 1) → ±2일 이내 (Phase 3)"],
        ["데이터 없으면", "문헌 기준 사용 (딸기 600~800 GDD, 토마토 착과 후 40~55일)"],
      ], [2400, 6960]),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 7
      h1("7단계. API 서버 구축"),
      p("Phase 1  |  4~8주  |  모델 개발과 병행 가능"),
      note("화면(앱·웹)과 AI 사이를 연결하는 중간 서버입니다. 먼저 빈 연결 구멍만 뚫어 놓고, AI가 완성되면 하나씩 연결합니다."),
      blank(),
      h2("구현 내용"),
      bullet("FastAPI*로 REST API* 서버 구축"),
      bullet("JWT* 인증: 로그인 없이는 데이터 접근 불가"),
      bullet("역할별 접근 제어: 농가 계정 / 관리자 계정 구분"),
      bullet("7개 AI 모듈별 연결 엔드포인트* 구현"),
      bullet("Swagger* 자동 문서 생성"),
      blank(),
      h2("데이터 신뢰도 표시 뱃지"),
      tbl(["뱃지", "색상", "의미"], [
        ["FINETUNED", "초록", "우리 농가 데이터로 직접 학습 완료 → 가장 신뢰"],
        ["TRANSFER", "파랑", "WUR 해외 데이터 기반 전이학습 → 비교적 신뢰"],
        ["SIMULATION", "노랑", "시뮬레이션 계산값 → 참고용"],
        ["LITERATURE", "회색", "논문·문헌 기준값 → 참고용"],
      ], [2400, 1600, 5360]),
      blank(),
      h2("서버 프로그램 목록"),
      tbl(["서버 이름", "하는 일"], [
        ["data-collector", "센서·농진청·KAMIS·기상청 데이터 자동 수집"],
        ["preprocessor", "데이터 정제·가공·시차변수 계산"],
        ["growth-predictor", "M1 생육 예측 AI 실행"],
        ["yield-predictor", "M2 생산량 + M3 수확시기 AI 실행"],
        ["revenue-estimator", "M4 매출 추정 AI 실행"],
        ["disease-detector", "M5 병해 진단 AI 실행"],
        ["notification-svc", "알람·경보 발송 (앱 푸시·이메일·카카오톡)"],
        ["retraining-svc", "AI 자동 재학습 스케줄러"],
      ], [3200, 6160]),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 8
      h1("8단계. 농가 대시보드 베타 출시"),
      p("Phase 1~2  |  8~20주"),
      note("AI가 붙는 순서대로 화면을 하나씩 추가합니다. M5 병해 → M1 생육 → M2/M3 수확 순서로 붙여나갑니다."),
      blank(),
      bullet("React 18 + TypeScript로 웹 대시보드 개발"),
      bullet("온실 환경 현황 실시간 표시 (10분마다 갱신)"),
      bullet("수확 예정일·생산량 예측 표시"),
      bullet("신뢰 범위 + 데이터 품질 뱃지 함께 표시"),
      bullet("병해 위험도 신호등 (초록·노랑·빨강)"),
      bullet("태블릿·모바일 화면 대응"),
      blank(),

      // Step 9
      h1("9단계. 매출 추정 AI (M4)"),
      p("Phase 2  |  12~20주"),
      blank(),
      tbl(["항목", "내용"], [
        ["방법", "Prophet* + SARIMA*로 단가 예측 → M2 생산량과 곱해서 매출 계산"],
        ["입력", "KAMIS 과거 5년 경락가, M2 생산량 예측, 소득자료집 경영비"],
        ["출력", "낙관적 전망(P75) / 보통 전망(P50) / 비관적 전망(P25) 3가지 + 순소득 추정"],
        ["출시 기준", "단가 예측 오차 20% 이하, 실제 단가가 예측 범위 안에 들어오는 비율 80% 이상"],
        ["데이터 없으면", "KAMIS 과거 계절 평균값으로 범위 추정"],
      ], [2400, 6960]),
      blank(),

      // Step 10
      h1("10단계. 에너지 절감 AI (M6)"),
      p("Phase 2~3  |  16~28주"),
      blank(),
      tbl(["Phase", "방법", "목표 오차"], [
        ["Phase 1~2", "EnergyPlus* 시뮬레이션으로 에너지 소비 계산", "±20%"],
        ["Phase 3", "스마트전력계 실측값으로 보정", "±8%"],
        ["Phase 4", "PhysicsNeMo*로 빠른 계산 모델로 교체", "±5%"],
      ], [2000, 5360, 2000]),
      blank(),
      tbl(["항목", "내용"], [
        ["입력", "온실 구조 (면적·피복재·설비), 기상청 기상 데이터, 설정 온도 범위"],
        ["출력", "월간 에너지 소비량 (kWh), 냉난방 부하 (kW), 절감 시나리오 비교"],
      ], [2400, 6960]),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 11
      h1("11단계. 운영 자동화"),
      p("Phase 2  |  16~24주"),
      note("AI가 오래 쓰이면 성능이 점점 떨어집니다. 자동으로 재학습하고 새 모델로 교체하는 시스템을 만듭니다."),
      blank(),
      h2("자동 재학습 흐름"),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "새 AI 학습 (챌린저*)", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "현재 AI (챔피언*)와 성능 비교", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "새 AI가 더 좋으면 자동 교체 후 Slack 알림", font: "Arial", size: 22 })] }),
      new Paragraph({ numbering: { reference: "steps", level: 0 }, children: [new TextRun({ text: "기준 미달이면 기존 AI 유지, 담당자에게 경고", font: "Arial", size: 22 })] }),
      blank(),
      p("정기 실행: 매월 1회 자동   |   긴급 실행: AI 오차율이 기준치보다 5%p 초과하면 즉시"),
      blank(),
      h2("이상 감지 알람"),
      tbl(["언제", "어떻게"], [
        ["AI 오차율이 기준보다 5%p 초과", "즉시 재학습 자동 실행"],
        ["센서 데이터가 3일 연속 50% 이상 빈칸", "현장 점검 알람"],
        ["API 응답이 2초 이상 걸릴 때", "서버 자동 증설"],
        ["병해를 한 주에 3번 이상 놓쳤을 때", "M5 긴급 재학습"],
      ], [4680, 4680]),
      blank(),

      // Step 12
      h1("12단계. 모바일 앱"),
      p("Phase 2  |  16~28주"),
      blank(),
      bullet("React Native로 iOS·Android 동시 개발"),
      bullet("카메라로 작물 촬영 → 병해 진단 결과 즉시 표시"),
      bullet("앱 알림 (병해 경보·수확 임박·이상 감지)"),
      bullet("하루 요약 리포트 (어제 대비 변화)"),
      bullet("인터넷 연결 끊겨도 기본 기능 사용 가능"),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Step 13
      h1("13단계. 품질 예측 AI (M7)"),
      p("Phase 3~4  |  24~36주  |  실측 데이터가 쌓인 후 시작"),
      note("굴절당도계 실측 데이터가 3작기 이상 쌓이기 전까지는 정확한 수치 예측이 불가능합니다. 그 전까지는 방향성 안내만 제공합니다."),
      blank(),
      tbl(["Phase", "제공 내용"], [
        ["Phase 1~2", "논문 기반 방향성 처방만 제공 (\"일사량 늘리면 당도 올라간다\" 수준)"],
        ["Phase 3+", "실제 당도·등급 수치 예측 (실측 데이터 3작기 이상 쌓인 후)"],
      ], [2400, 6960]),
      blank(),
      tbl(["항목", "내용"], [
        ["입력", "일사량·야간온도·EC·pH·착과일수·수확 전 급수 중단일"],
        ["출력", "당도 예측 (Brix), 등급 확률 (특/상/보통), 품질 높이는 처방"],
        ["출시 기준", "당도 R2* 0.70 이상, 등급 F1* 0.80 이상 (실측 쌓인 후)"],
      ], [2400, 6960]),
      blank(),

      // Step 14
      h1("14단계. 고도화 & 확장"),
      p("Phase 3~4  |  30주+"),
      blank(),
      h2("농가 확장"),
      bullet("신규 농가 온보딩 4주 프로세스: 계약 → 센서 설치 → 데이터베이스 연결 → 교육"),
      bullet("Phase 2: 10~15곳 → Phase 3: 20~30곳 → Phase 4: 50곳+"),
      blank(),
      h2("데이터 공유 없이 AI 함께 키우기 (연합학습*)"),
      bullet("농가마다 자기 원본 데이터는 내부에만 보관"),
      bullet("AI 학습 결과값만 서로 공유 → 개인정보 노출 없이 성능 향상"),
      bullet("PySyft 또는 Flower 프레임워크 사용"),
      blank(),
      h2("관리자 화면 (Phase 2~3)"),
      bullet("AI별 정확도 지표 실시간 모니터링"),
      bullet("재학습 수동 실행 버튼"),
      bullet("A/B 테스트* 결과 비교"),
      blank(),
      h2("WUR 국제 대회 참가 (Phase 3~4)"),
      bullet("WUR Autonomous Greenhouse Challenge 2026 참가 목표"),
      bullet("방울토마토 AI 자동 제어 알고리즘 개발"),
      bullet("우승 팀과 데이터 공유 MOU 체결 추진"),
      blank(),
      h2("서버 고도화 (Phase 4)"),
      bullet("Docker Compose → Kubernetes* 전환 (더 많은 농가를 안정적으로 지원)"),
      bullet("PhysicsNeMo*로 에너지 예측 속도 향상"),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // 품질·검증·보안
      h1("품질·검증·보안 기준"),

      h2("AI 출시 기준 (배포 게이트)"),
      tbl(
        ["AI 모듈", "측정 기준", "Phase 1 목표", "Phase 3 목표", "기준 미달 시"],
        [
          ["M1 생육 예측", "정확도(R2) / 오차율(MAPE)", "R2≥0.62, 오차≤20%", "R2≥0.85, 오차≤12%", "자동 재학습 + 담당자 알람"],
          ["M2 생산량", "오차율 / 방향 정확도", "오차≤25%, 방향≥70%", "오차≤15%", "재학습 + 수치 재보정"],
          ["M3 수확시기", "날짜 오차 (일)", "±5일 이내", "±2일 이내", "GDD 기준값 재조정"],
          ["M5 병해 진단", "F1 / 위음성율", "F1≥0.88, 위음성≤5%", "—", "즉시 재학습"],
          ["M4 매출 추정", "단가 오차", "오차≤20%, 포함율≥80%", "—", "Prophet 재학습"],
        ],
        [1600, 2000, 1800, 1800, 2160]
      ),
      blank(),

      h2("서버 운영 기준"),
      tbl(["항목", "목표"], [
        ["AI 예측 응답 속도", "2초 이내 (상위 95% 기준)"],
        ["단순 조회 응답 속도", "0.5초 이내"],
        ["월간 서비스 가동률", "99.5% 이상"],
        ["센서 데이터 일별 빈칸 비율", "10% 미만"],
      ], [4680, 4680]),
      blank(),

      h2("보안 기준"),
      tbl(["항목", "기준"], [
        ["API 접근", "로그인(JWT) 필수, 무인증 접근 0건"],
        ["저장 데이터 암호화", "AES-256 암호화"],
        ["전송 데이터 암호화", "HTTPS (TLS 1.3 이상)"],
        ["비밀키 교체 주기", "90일 이내"],
        ["AI 결과 설명", "XGBoost 기반 예측은 SHAP*으로 근거 제공"],
        ["불확실성 표시", "모든 예측값에 신뢰 범위 + 뱃지 100% 표시"],
      ], [4680, 4680]),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // 용어 주석
      h1("용어 주석"),
      p("본 문서에서 사용한 전문 용어 설명 모음입니다. * 표시가 있는 단어는 이 표를 참고하세요."),
      blank(),
      tbl(
        ["용어", "설명"],
        [
          ["Docker Compose", "여러 서버 프로그램을 설정 파일 하나로 한꺼번에 실행·관리하는 도구"],
          ["GitHub Actions", "코드가 바뀌면 자동으로 배포·테스트를 진행하는 자동화 도구"],
          ["파이프라인 (Pipeline)", "데이터가 수집 → 정제 → 저장 → 사용 순서로 흐르는 자동화된 처리 경로"],
          ["MQTT", "IoT 기기(센서)에서 데이터를 가볍고 빠르게 전송하는 통신 규격"],
          ["결측 보간", "빠진 데이터 값을 앞뒤 값을 참고해서 채워 넣는 처리"],
          ["KNN", "비슷한 상황의 데이터를 찾아 빈 값을 채우는 방법"],
          ["GDD (Growing Degree Days)", "작물 생장에 필요한 온도 누적합. 온도가 높을수록 빠르게 쌓임"],
          ["정규화 (Normalization)", "서로 단위가 다른 값들을 0~1 사이로 통일해 AI가 비교하기 쉽게 만드는 과정"],
          ["TOMGRO / 파라미터", "작물 성장을 수학 수식으로 표현한 물리 모델. 파라미터는 모델 안의 조절 가능한 수치들"],
          ["EnergyPlus", "건물(온실)의 에너지 소비를 시뮬레이션하는 미국 에너지부 공인 프로그램"],
          ["TimeGAN", "시계열 데이터(시간 순서 데이터)를 인공으로 생성하는 AI 기법"],
          ["EfficientNet-B4", "이미지 분류에 강한 경량 AI 모델. 병해 사진 분류에 적합"],
          ["F1-score", "정밀도(틀린 경보 없이 맞추기)와 재현율(빠짐 없이 잡기)의 균형 지표. 1에 가까울수록 좋음"],
          ["위음성 (False Negative)", "실제로 병이 있는데 AI가 정상이라고 잘못 판단하는 오류"],
          ["Optuna", "AI 모델의 설정값을 자동으로 최적화해주는 라이브러리"],
          ["사전학습 / 파인튜닝", "사전학습: 대량 데이터로 기초 학습. 파인튜닝: 기초 모델을 우리 데이터에 맞게 추가 학습"],
          ["LSTM", "시간 순서가 있는 데이터(온도 변화, 생육 변화 등)를 학습하는 AI 구조"],
          ["Dropout", "학습 중 일부 연결을 무작위로 끊어 AI가 특정 데이터에만 치우치지 않도록 하는 기법"],
          ["Leave-one-out 교차검증", "농가 5곳 중 1곳씩 순서대로 빼고 학습한 후 빠진 농가로 검증하는 방식"],
          ["MC Dropout", "Dropout을 예측 시에도 여러 번 적용해 결과의 불확실성을 수치로 나타내는 기법"],
          ["R2 (결정계수)", "AI 예측이 실제 값을 얼마나 잘 설명하는지 나타내는 지표. 1에 가까울수록 좋음"],
          ["MAPE", "예측값이 실제값에서 평균적으로 몇 % 벗어났는지 나타내는 오차율"],
          ["XGBoost", "여러 결정 트리를 조합해 높은 예측 성능을 내는 AI 알고리즘"],
          ["생존분석", "언제 수확될 확률이 가장 높은가를 확률 분포로 예측하는 통계 기법"],
          ["FastAPI", "Python으로 빠르게 REST API 서버를 만드는 프레임워크"],
          ["REST API", "앱·웹이 서버에 데이터를 요청하고 받는 표준 통신 방식"],
          ["JWT", "로그인 상태를 암호화된 토큰으로 확인하는 인증 방식"],
          ["엔드포인트 (Endpoint)", "API에서 특정 기능을 요청하는 주소 (예: /predict/growth)"],
          ["Swagger", "API 명세를 자동으로 웹 페이지로 보여주는 문서화 도구"],
          ["컨테이너 (Container)", "프로그램과 실행 환경을 하나로 묶어 어디서나 동일하게 실행되도록 패키징하는 기술"],
          ["Prophet / SARIMA", "시계열 예측 모델. 계절성이 있는 단가 예측에 적합"],
          ["PhysicsNeMo", "NVIDIA가 만든 물리 기반 AI 프레임워크. 시뮬레이션을 AI로 빠르게 대체"],
          ["챌린저 / 챔피언", "현재 서비스 중인 AI(챔피언)와 새로 학습한 AI(챌린저)를 비교해 더 좋은 것을 사용"],
          ["연합학습 (Federated Learning)", "원본 데이터를 공유하지 않고 각자 학습한 AI의 파라미터만 모아 함께 성능을 높이는 방법"],
          ["A/B 테스트", "두 가지 버전을 실제 사용자에게 동시에 제공해 어느 쪽이 더 효과적인지 비교하는 실험"],
          ["Kubernetes", "많은 수의 컨테이너를 자동으로 배포·확장·관리하는 오케스트레이션 도구"],
          ["SHAP", "AI가 왜 이런 예측을 했는지 각 입력값의 영향도를 수치로 보여주는 설명 가능 AI 기법"],
        ],
        [3200, 6160]
      ),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("C:/smart_farm/docs/technical-spec.docx", buffer);
  console.log("technical-spec.docx 생성 완료");
});
