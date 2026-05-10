const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, LevelFormat, TableOfContents, PageBreak
} = require('docx');
const fs = require('fs');

const CONTENT_WIDTH = 9360;
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const headerBorder = { style: BorderStyle.SINGLE, size: 8, color: "2D7D46" };
const headerBorders = { top: headerBorder, bottom: headerBorder, left: headerBorder, right: headerBorder };

function heading1(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)] });
}
function heading2(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] });
}
function heading3(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] });
}
function body(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 120 },
    children: [new TextRun({ text, ...opts })]
  });
}
function blank() {
  return new Paragraph({ spacing: { after: 80 }, children: [] });
}
function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children: [new TextRun(text)]
  });
}
function checkbox(text) {
  return new Paragraph({
    numbering: { reference: "checkboxes", level: 0 },
    children: [new TextRun(text)]
  });
}

function makeTable(headers, rows, colWidths) {
  const total = colWidths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((h, i) => new TableCell({
          borders: headerBorders,
          width: { size: colWidths[i], type: WidthType.DXA },
          shading: { fill: "2D7D46", type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: h, bold: true, color: "FFFFFF", font: "Arial", size: 20 })] })]
        }))
      }),
      ...rows.map((row, ri) => new TableRow({
        children: row.map((cell, i) => new TableCell({
          borders,
          width: { size: colWidths[i], type: WidthType.DXA },
          shading: { fill: ri % 2 === 0 ? "F0F7F2" : "FFFFFF", type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: cell, font: "Arial", size: 20 })] })]
        }))
      }))
    ]
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: "1A5C2D" },
        paragraph: { spacing: { before: 320, after: 160 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "2D7D46", space: 4 } } }
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "2D7D46" },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 }
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "444444" },
        paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2 }
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
        reference: "checkboxes",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "□", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial" } } }]
      }
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "2D7D46", space: 4 } },
          children: [new TextRun({ text: "스마트팜 수익성 향상 플랫폼 — 프로젝트 개요", font: "Arial", size: 18, color: "666666" })]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 4 } },
          children: [
            new TextRun({ text: "v1.0  |  2026-04-29  |  페이지 ", font: "Arial", size: 18, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: "888888" })
          ]
        })]
      })
    },
    children: [
      // Cover
      blank(), blank(),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 200 },
        children: [new TextRun({ text: "스마트팜 수익성 향상 플랫폼", font: "Arial", size: 56, bold: true, color: "1A5C2D" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 200 },
        children: [new TextRun({ text: "프로젝트 개요 보고서", font: "Arial", size: 36, color: "2D7D46" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 120 },
        children: [new TextRun({ text: "딸기 · 토마토 · 방울토마토 · 참외  |  5개 농가 기반 → 50개+ 농가 확장  |  Phase 1~4", font: "Arial", size: 22, color: "555555" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 400 },
        children: [new TextRun({ text: "2026-04-29  |  v1.0", font: "Arial", size: 20, color: "888888" })]
      }),
      blank(),
      new Paragraph({ children: [new PageBreak()] }),

      // TOC
      new TableOfContents("목차", { hyperlink: true, headingStyleRange: "1-2" }),
      new Paragraph({ children: [new PageBreak()] }),

      // Section 1
      heading1("1. 프로젝트 개요"),

      heading2("1.1 목적"),
      body("스마트팜 농가의 환경 데이터, 생육 데이터, 시장 단가를 통합 분석하여 수확 예측, 병해 진단, 매출 추정을 자동화하는 AI 기반 수익성 향상 플랫폼 구축"),
      blank(),

      heading2("1.2 대상 작목"),
      makeTable(
        ["작목", "적용 모델 / 비고"],
        [
          ["딸기", "DSSAT CROPGRO-Strawberry 물리모델 적용"],
          ["토마토", "TOMGRO 물리모델 + LSTM 시계열"],
          ["방울토마토", "WUR AGC 공개 데이터 전이학습"],
          ["참외", "GDD 기반 수확시기 예측"],
        ],
        [2800, 6560]
      ),
      blank(),

      heading2("1.3 초기 규모 및 확장 계획"),
      bullet("Phase 1: 5개 농가 기반 데이터 수집 및 모델 학습"),
      bullet("Phase 2: 10~15개 농가로 확장"),
      bullet("Phase 4: 50개+ 농가 달성 목표"),
      bullet("데이터 소스: 현장 IoT 센서, 농진청 API, KAMIS 단가 API, AI Hub 병해 데이터, WUR 공개 데이터셋"),
      blank(),

      heading2("1.4 핵심 AI 모듈 (7개)"),
      makeTable(
        ["모듈", "기능", "착수 시기", "우선순위"],
        [
          ["M1", "환경 → 생육 예측", "Phase 1", "1순위 (핵심)"],
          ["M2", "생산량 예측", "Phase 1", "1순위"],
          ["M3", "수확시기 예측", "Phase 1", "1순위"],
          ["M4", "매출 추정", "Phase 2", "2순위"],
          ["M5", "병해 진단", "Phase 1", "1순위 (즉시)"],
          ["M6", "에너지 효율", "Phase 2~3", "3순위"],
          ["M7", "품질 예측 (당도·등급)", "Phase 3~4", "4순위"],
        ],
        [1200, 3800, 2000, 2360]
      ),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Section 2
      heading1("2. Phase별 실행 일정"),

      heading2("Phase 1 — 기반 구축 + 베타 출시 (0~3개월)"),
      bullet("5농가 데이터 표준 스키마 DB 구축 및 정제"),
      bullet("농진청·KAMIS·AI Hub 외부 데이터 연동 파이프라인 구축"),
      bullet("M1(생육 예측)·M3(수확시기)·M5(병해 진단) 우선 개발"),
      bullet("FastAPI 기반 API Gateway + 농가 대시보드 베타 출시"),
      bullet("인프라: GPU 서버(NVIDIA A10G), TimescaleDB, Docker Compose 환경"),
      blank(),

      heading2("Phase 2 — 정밀화 + 매출 추정 (3~6개월)"),
      bullet("M4 매출 추정 모듈 출시 — KAMIS 단가 × 생산량 3-way 시나리오 (낙관/중립/비관)"),
      bullet("M6 에너지 효율 — EnergyPlus 시뮬레이션 기반"),
      bullet("Airflow 자동 재학습 파이프라인 구동"),
      bullet("Prometheus + Grafana 운영 모니터링 구축"),
      bullet("모바일 앱 베타 출시 (iOS/Android)"),
      bullet("연계 농가 10개 이상으로 확장"),
      blank(),

      heading2("Phase 3 — 실측 보강 + 품질 모듈 (6~12개월)"),
      bullet("5농가 굴절당도계·스마트전력계 설치 → 실측 데이터 3작기 이상 축적"),
      bullet("M7 품질 예측 모듈 출시 (당도·등급 분류)"),
      bullet("에너지 실측 ML 보정 달성 (±8%)"),
      bullet("WUR 연구진 데이터 공유 MOU 체결 (목표)"),
      bullet("연계 농가 20개 이상"),
      blank(),

      heading2("Phase 4 — 확장 + 자동화 (12개월+)"),
      bullet("Kubernetes 기반 오케스트레이션 전환"),
      bullet("연합학습(Federated Learning) 파일럿 — 농가 원시 데이터 비공유 방식"),
      bullet("WUR Autonomous Greenhouse Challenge 2026 참가"),
      bullet("PhysicsNeMo 에너지 서로게이트 모델 구축"),
      bullet("연계 농가 50개+ 달성"),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Section 3
      heading1("3. Phase별 KPI 목표치"),
      makeTable(
        ["지표", "Phase 1\n(0~3개월)", "Phase 2\n(3~6개월)", "Phase 3\n(6~12개월)", "Phase 4\n(12개월+)"],
        [
          ["환경→생육 R²", "≥ 0.62", "≥ 0.75", "≥ 0.85", "≥ 0.90"],
          ["생산량 MAPE", "≤ 25%", "≤ 18%", "≤ 12%", "≤ 8%"],
          ["수확시기 예측 오차", "± 5일", "± 3일", "± 2일", "± 1일"],
          ["병해 진단 정확도", "≥ 92%", "≥ 93%", "≥ 95%", "≥ 96%"],
          ["매출 추정 오차", "± 30%", "± 22%", "± 15%", "± 10%"],
          ["에너지 예측 오차", "시뮬 ± 20%", "± 15%", "± 8%", "± 5%"],
          ["품질 예측 F1", "문헌 처방만", "≥ 0.60", "≥ 0.75", "≥ 0.85"],
          ["연계 농가 수", "5개", "10~15개", "20~30개", "50개+"],
        ],
        [2800, 1640, 1640, 1640, 1640]
      ),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Section 4
      heading1("4. 주요 마일스톤 체크리스트"),

      heading2("Phase 1 완료 기준"),
      checkbox("5농가 데이터 표준 스키마 DB 적재 완료"),
      checkbox("농진청 API 자동 수집 파이프라인 가동"),
      checkbox("WUR 방울토마토 데이터 전이학습 완료"),
      checkbox("TOMGRO 파라미터 국내 품종 보정 완료"),
      checkbox("환경→생육 예측 모델 배포 게이트 통과 (R² ≥ 0.62)"),
      checkbox("병해 진단 서비스 베타 출시 (F1 ≥ 0.88)"),
      checkbox("API Gateway REST API 7개 엔드포인트 구현"),
      checkbox("농가 대시보드 베타 웹앱 배포"),
      checkbox("모델 불확실성 뱃지 UI 구현"),
      blank(),

      heading2("Phase 2 완료 기준"),
      checkbox("KAMIS 단가 API 연동 + Prophet 모델 학습"),
      checkbox("매출 추정 3-way 시나리오 서비스 출시"),
      checkbox("EnergyPlus 5농가 온실 모델 구축 완료"),
      checkbox("Airflow 자동 재학습 파이프라인 구동"),
      checkbox("Prometheus + Grafana 모니터링 구축"),
      checkbox("모바일 앱 베타 출시 (iOS/Android)"),
      checkbox("연계 농가 10개 이상으로 확장"),
      checkbox("생산량 MAPE ≤ 18% 달성"),
      blank(),

      heading2("Phase 3 완료 기준"),
      checkbox("5농가 굴절당도계 측정 3작기 이상 데이터 축적"),
      checkbox("스마트 전력계 5농가 설치 완료"),
      checkbox("품질 예측 모듈 출시 (등급 F1 ≥ 0.75)"),
      checkbox("에너지 실측 기반 ML 모델 보정 (± 8%)"),
      checkbox("WUR 연구진 접촉 및 데이터 공유 MOU 체결"),
      checkbox("연계 농가 20개 이상"),
      checkbox("환경→생육 R² ≥ 0.85 달성"),
      blank(),

      heading2("Phase 4 완료 기준"),
      checkbox("Kubernetes 기반 오케스트레이션 전환"),
      checkbox("연합학습(Federated Learning) 파일럿 완료"),
      checkbox("WUR AGC 2026 참가 완료"),
      checkbox("PhysicsNeMo 에너지 서로게이트 모델 구축"),
      checkbox("연계 농가 50개+ 달성"),
      checkbox("환경→생육 R² ≥ 0.90 달성"),
      checkbox("전 모듈 MAPE ≤ 10% 달성"),
      blank(),

      new Paragraph({ children: [new PageBreak()] }),

      // Section 5
      heading1("5. 확장 로드맵"),

      heading2("5.1 농가 확장 계획 (Phase 2~3)"),
      bullet("온보딩 프로세스 표준화: 계약 → 센서 설치 → DB 연동 → 교육 (총 4주 프로세스)"),
      bullet("온실 구조 정보 수집 표준 양식 배포"),
      bullet("확장 시 모델 재보정 프로세스 적용"),
      blank(),

      heading2("5.2 연합학습 도입 (Phase 4)"),
      bullet("PySyft 또는 Flower 프레임워크 도입 검토"),
      bullet("농가 원시 데이터 비공유 + 모델 파라미터만 공유"),
      bullet("계절별 작목 클러스터 구성"),
      bullet("프라이버시 보호 검증 및 농가 동의 절차 수립"),
      blank(),

      heading2("5.3 WUR AGC 2026 참가 (Phase 3~4)"),
      bullet("WUR Autonomous Greenhouse Challenge 2026 사전 등록"),
      bullet("방울토마토 AI 제어 알고리즘 개발"),
      bullet("WUR 연구진 접촉 및 데이터 공유 MOU 논의"),
      bullet("글로벌 데이터·모델 접근 기회 확보"),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("C:/smart_farm/docs/project-overview.docx", buffer);
  console.log("project-overview.docx 생성 완료");
});
