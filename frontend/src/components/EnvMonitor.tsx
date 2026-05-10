
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

// Simple icon map using inline SVG paths
const ICONS: Record<string, JSX.Element> = {
  temp_internal: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z" />
    </svg>
  ),
  humidity_int: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" />
    </svg>
  ),
  co2_ppm: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" /><path d="M8 12h8M12 8v8" />
    </svg>
  ),
  default: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
      <h2 style={{ fontSize: "1rem", fontWeight: 700, color: colors.inkPrimary, marginBottom: "12px" }}>
        실시간 환경
      </h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "12px" }}>
        {measurements.map((m) => (
          <div
            key={m.canonical_name}
            style={{
              background: colors.cloudWhite,
              borderRadius: radius.card,
              boxShadow: shadow.card,
              border: `1px solid ${colors.stoneBorder}`,
              padding: "16px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px", color: colors.chartwellBlue, marginBottom: "8px" }}>
              {getIcon(m.canonical_name)}
              <span style={{ fontSize: "0.875rem", color: colors.inkSecondary, fontWeight: 500 }}>
                {LABELS_KO[m.canonical_name] || m.canonical_name}
              </span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: "4px" }}>
              <span style={{ fontSize: "1.5rem", fontWeight: 800, color: colors.inkPrimary }}>
                {m.value.toFixed(1)}
              </span>
              <span style={{ fontSize: "0.875rem", color: colors.inkMuted }}>{m.unit}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "4px", marginTop: "6px" }}>
              <span style={{
                fontSize: "0.7rem", fontWeight: 600,
                color: qualityColor(m.quality_tag),
                background: `${qualityColor(m.quality_tag)}18`,
                padding: "2px 6px", borderRadius: "9999px",
              }}>
                {qualityLabel(m.quality_tag)}
              </span>
              {m.imputed && (
                <span style={{ fontSize: "0.7rem", color: colors.warningAmber }}>보완</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
