
import { colors, radius, shadow } from "../design-system/tokens";

interface EnvPoint {
  canonical_name: string;
  value: number;
  unit: string;
  quality_tag: string;
  imputed: boolean;
}

interface Props {
  measurements: EnvPoint[];
}

const LABELS_KO: Record<string, string> = {
  temp_internal:  "내부 온도",
  temp_external:  "외부 온도",
  humidity_int:   "내부 습도",
  co2_ppm:        "CO₂ 농도",
  solar_rad:      "일사량",
  ec_dsm:         "EC",
  soil_temp:      "토양 온도",
  wind_speed_ext: "풍속",
};

// 변수별 고유 컬러 (직관적 연상 기반)
const VAR_COLOR: Record<string, string> = {
  temp_internal:  "#ef4444",  // 빨강 — 온도·열
  temp_external:  "#ef4444",  // 빨강 — 온도·열
  humidity_int:   "#3ba6f1",  // 파랑 — 습도·물
  co2_ppm:        "#16a34a",  // 초록 — CO₂·식물
  solar_rad:      "#f59e0b",  // 앰버 — 일사량·햇빛
  ec_dsm:         "#8b5cf6",  // 보라 — EC·영양
  soil_temp:      "#d97706",  // 갈색 — 토양
  wind_speed_ext: "#64748b",  // 슬레이트 — 바람
};

function varColor(name: string): string {
  return VAR_COLOR[name] ?? colors.chartwellBlue;
}

// 아이콘 (24×24으로 확대)
const ICONS: Record<string, JSX.Element> = {
  temp_internal: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z" />
    </svg>
  ),
  temp_external: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z" />
    </svg>
  ),
  humidity_int: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" />
    </svg>
  ),
  co2_ppm: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" /><path d="M8 12h8M12 8v8" />
    </svg>
  ),
  solar_rad: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  ),
  ec_dsm: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 6l3 6 3-6 3 6 3-6 3 6" /><path d="M3 18h18" />
    </svg>
  ),
  soil_temp: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M2 22c2-4 6-6 10-6s8 2 10 6" /><path d="M12 16V8" /><circle cx="12" cy="6" r="2" />
    </svg>
  ),
  wind_speed_ext: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M17.7 7.7a2.5 2.5 0 1 1 1.8 4.3H2" /><path d="M9.6 4.6A2 2 0 1 1 11 8H2" /><path d="M12.6 19.4A2 2 0 1 0 14 16H2" />
    </svg>
  ),
  default: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
    </svg>
  ),
};

function getIcon(name: string): JSX.Element {
  return ICONS[name] || ICONS.default;
}

function qualityColor(tag: string): string {
  switch (tag) {
    case "FINETUNED":   return colors.successGreen;
    case "TRANSFER":    return colors.chartwellBlue;
    case "SIMULATION":  return colors.warningAmber;
    default:            return colors.inkMuted;
  }
}

function qualityLabel(tag: string): string {
  switch (tag) {
    case "FINETUNED":   return "실측";
    case "TRANSFER":    return "이전학습";
    case "SIMULATION":  return "시뮬";
    default:            return tag;
  }
}

export function EnvMonitor({ measurements }: Props) {
  return (
    <div>
      <h2 style={{ fontSize: "1rem", fontWeight: 700, color: colors.inkPrimary, marginBottom: "14px" }}>
        실시간 환경
      </h2>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
        gap: "16px",
      }}>
        {measurements.map((m) => {
          const color = varColor(m.canonical_name);
          return (
            <div
              key={m.canonical_name}
              style={{
                background: `${color}08`,        // 아주 연한 컬러 tint
                borderRadius: radius.card,
                boxShadow: shadow.card,
                border: `1px solid ${color}30`,  // 테두리도 컬러 반영
                borderLeft: `4px solid ${color}`, // 좌측 강조 컬러 바
                padding: "20px",
              }}
            >
              {/* 아이콘 + 라벨 */}
              <div style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                color: color,
                marginBottom: "10px",
              }}>
                {getIcon(m.canonical_name)}
                <span style={{
                  fontSize: "1rem",
                  color: colors.inkPrimary,
                  fontWeight: 600,
                }}>
                  {LABELS_KO[m.canonical_name] || m.canonical_name}
                </span>
              </div>

              {/* 측정값 + 단위 */}
              <div style={{ display: "flex", alignItems: "baseline", gap: "5px" }}>
                <span style={{
                  fontSize: "2rem",
                  fontWeight: 800,
                  color: colors.inkPrimary,
                  lineHeight: 1.1,
                }}>
                  {m.value.toFixed(1)}
                </span>
                <span style={{
                  fontSize: "1rem",
                  color: colors.inkSecondary,
                  fontWeight: 500,
                }}>
                  {m.unit}
                </span>
              </div>

              {/* 품질 배지 */}
              <div style={{ display: "flex", alignItems: "center", gap: "5px", marginTop: "8px" }}>
                <span style={{
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  color: qualityColor(m.quality_tag),
                  background: `${qualityColor(m.quality_tag)}18`,
                  padding: "2px 8px",
                  borderRadius: "9999px",
                }}>
                  {qualityLabel(m.quality_tag)}
                </span>
                {m.imputed && (
                  <span style={{ fontSize: "0.8rem", color: colors.warningAmber, fontWeight: 500 }}>
                    보완값
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
