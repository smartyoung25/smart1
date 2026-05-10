import { useState } from "react";
import { colors, radius, shadow } from "../design-system/tokens";

// ---- Stub data ------------------------------------------------------------

const STUB_KPI = {
  connected_farms: 5,
  avg_model_r2: 0.71,
  data_completeness_pct: 88.5,
  income_improvement_pct: 14.2,
};

const STUB_MODELS = [
  { module_id: "M1", metric_name: "R²",    metric_value: 0.73, threshold: 0.62, passed: true,  last_trained: "2026-05-09" },
  { module_id: "M2", metric_name: "MAPE",  metric_value: 18.4, threshold: 25.0, passed: true,  last_trained: "2026-05-09" },
  { module_id: "M3", metric_name: "일 오차", metric_value: 3.2, threshold: 5.0,  passed: true,  last_trained: "2026-05-08" },
  { module_id: "M4", metric_name: "오차%", metric_value: 16.1, threshold: 20.0, passed: true,  last_trained: "2026-05-08" },
  { module_id: "M5", metric_name: "F1",    metric_value: 0.85, threshold: 0.88, passed: false, last_trained: "2026-05-07" },
];

const STUB_SOURCES = [
  { source_id: "iot_sensor",  label_ko: "IoT 센서",     connected: true,  completeness_pct: 94 },
  { source_id: "rda_api",     label_ko: "농진청 API",   connected: true,  completeness_pct: 80 },
  { source_id: "kamis",       label_ko: "KAMIS 가격",   connected: true,  completeness_pct: 100 },
  { source_id: "wur_dataset", label_ko: "WUR 데이터셋", connected: false, completeness_pct: 0 },
  { source_id: "manual",      label_ko: "수동 입력",    connected: true,  completeness_pct: 60 },
];

const STUB_REGISTRY = [
  { canonical_name: "temp_internal", display_name_ko: "내부 온도", unit: "°C",    impute: "locf", sources: ["iot_sensor","rda_api","wur_dataset"] },
  { canonical_name: "ec_dsm",        display_name_ko: "EC",        unit: "dS/m",  impute: "knn",  sources: ["iot_sensor(×0.1)","wur_dataset"] },
  { canonical_name: "co2_ppm",       display_name_ko: "CO₂ 농도", unit: "ppm",   impute: "knn",  sources: ["iot_sensor","wur_dataset"] },
  { canonical_name: "humidity_int",  display_name_ko: "내부 습도", unit: "%",     impute: "locf", sources: ["iot_sensor","rda_api"] },
  { canonical_name: "yield_kg_m2",   display_name_ko: "수확량",    unit: "kg/m²", impute: "none", sources: ["rda_api","wur_dataset","manual"] },
  { canonical_name: "kamis_price",   display_name_ko: "KAMIS 단가",unit: "원/kg", impute: "locf", sources: ["kamis"] },
];

const STUB_RUNS = [
  { run_id: "run_001", trigger: "scheduled", started_at: "2026-05-09 06:00", duration: "5분 12초", status: "success",  r2_before: 0.70, r2_after: 0.73, deployed: true },
  { run_id: "run_002", trigger: "manual",    started_at: "2026-05-09 11:30", duration: "—",        status: "running",  r2_before: null, r2_after: null, deployed: null },
];

// ---- Component ------------------------------------------------------------

type Section = "overview" | "models" | "sources" | "registry" | "pipeline";

const NAV_ITEMS: { key: Section; label: string }[] = [
  { key: "overview",  label: "전체 현황" },
  { key: "models",    label: "AI 모델" },
  { key: "sources",   label: "데이터 소스" },
  { key: "registry",  label: "변수 레지스트리" },
  { key: "pipeline",  label: "학습 파이프라인" },
];

export function AdminDashboard() {
  const [section, setSection] = useState<Section>("overview");
  const [triggering, setTriggering] = useState(false);
  const [triggered, setTriggered] = useState(false);

  async function handleTrigger() {
    setTriggering(true);
    await fetch("/api/admin/pipeline/trigger", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "manual" }) });
    setTriggering(false);
    setTriggered(true);
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: "'Inter', sans-serif", background: colors.canvasFog, WebkitFontSmoothing: "antialiased" }}>

      {/* ── Sidebar ── */}
      <aside style={{
        width: "220px", flexShrink: 0,
        background: colors.cloudWhite,
        borderRight: `1px solid ${colors.stoneBorder}`,
        display: "flex", flexDirection: "column",
        position: "sticky", top: 0, height: "100vh",
      }}>
        <div style={{ padding: "20px 16px 16px", borderBottom: `1px solid ${colors.stoneBorder}` }}>
          <p style={{ fontSize: "0.7rem", fontWeight: 600, color: colors.inkMuted, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "4px" }}>플랫폼 관리</p>
          <p style={{ fontSize: "1rem", fontWeight: 800, color: colors.inkPrimary }}>Smart Farm</p>
        </div>
        <nav style={{ padding: "8px" }}>
          {NAV_ITEMS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setSection(key)}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "10px 12px", marginBottom: "2px",
                borderRadius: "8px", border: "none",
                background: section === key ? colors.chartwellBlueBg : "none",
                color: section === key ? colors.chartwellBlue : colors.inkSecondary,
                fontWeight: section === key ? 700 : 500,
                fontSize: "0.9375rem", cursor: "pointer",
                transition: "background 150ms, color 150ms",
              }}
            >
              {label}
            </button>
          ))}
        </nav>
      </aside>

      {/* ── Main ── */}
      <main style={{ flex: 1, padding: "24px", overflow: "auto" }}>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 800, color: colors.inkPrimary, marginBottom: "20px" }}>
          {NAV_ITEMS.find(n => n.key === section)?.label}
        </h1>

        {/* OVERVIEW */}
        {section === "overview" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "16px" }}>
            {[
              { label: "연결 농가",       value: `${STUB_KPI.connected_farms}개`,       color: colors.chartwellBlue },
              { label: "평균 R²",         value: STUB_KPI.avg_model_r2.toFixed(2),      color: colors.successGreen },
              { label: "데이터 완전성",   value: `${STUB_KPI.data_completeness_pct}%`,  color: colors.warningAmber },
              { label: "소득 향상률",     value: `+${STUB_KPI.income_improvement_pct}%`,color: colors.successGreen },
            ].map(({ label, value, color }) => (
              <div key={label} style={{ background: colors.cloudWhite, borderRadius: radius.card, boxShadow: shadow.card, border: `1px solid ${colors.stoneBorder}`, padding: "20px" }}>
                <p style={{ fontSize: "0.875rem", color: colors.inkSecondary, marginBottom: "8px" }}>{label}</p>
                <p style={{ fontSize: "1.875rem", fontWeight: 800, color }}>{value}</p>
              </div>
            ))}
          </div>
        )}

        {/* MODELS */}
        {section === "models" && (
          <div style={{ background: colors.cloudWhite, borderRadius: radius.card, boxShadow: shadow.card, border: `1px solid ${colors.stoneBorder}`, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: colors.canvasFog, borderBottom: `1px solid ${colors.stoneBorder}` }}>
                  {["모듈", "지표", "현재값", "기준값", "상태", "학습일"].map(h => (
                    <th key={h} style={{ padding: "12px 16px", textAlign: "left", fontSize: "0.75rem", fontWeight: 700, color: colors.inkSecondary, letterSpacing: "0.04em", textTransform: "uppercase" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {STUB_MODELS.map((m, i) => (
                  <tr key={m.module_id} style={{ borderBottom: i < STUB_MODELS.length - 1 ? `1px solid ${colors.stoneBorder}` : "none" }}>
                    <td style={{ padding: "14px 16px", fontWeight: 700, color: colors.inkPrimary }}>{m.module_id}</td>
                    <td style={{ padding: "14px 16px", color: colors.inkSecondary }}>{m.metric_name}</td>
                    <td style={{ padding: "14px 16px", fontWeight: 700, color: m.passed ? colors.successGreen : colors.dangerRed }}>{m.metric_value}</td>
                    <td style={{ padding: "14px 16px", color: colors.inkMuted }}>{m.threshold}</td>
                    <td style={{ padding: "14px 16px" }}>
                      <span style={{
                        display: "inline-block", padding: "3px 10px", borderRadius: radius.badge,
                        fontSize: "0.75rem", fontWeight: 700,
                        background: m.passed ? colors.successBg : colors.dangerBg,
                        color: m.passed ? colors.successGreen : colors.dangerRed,
                      }}>
                        {m.passed ? "통과" : "미통과"}
                      </span>
                    </td>
                    <td style={{ padding: "14px 16px", color: colors.inkMuted, fontSize: "0.875rem" }}>{m.last_trained}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* DATA SOURCES */}
        {section === "sources" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {STUB_SOURCES.map(s => (
              <div key={s.source_id} style={{ background: colors.cloudWhite, borderRadius: radius.card, boxShadow: shadow.card, border: `1px solid ${colors.stoneBorder}`, padding: "16px 20px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <span style={{
                      width: "8px", height: "8px", borderRadius: "50%",
                      background: s.connected ? colors.successGreen : colors.inkMuted,
                      display: "inline-block", flexShrink: 0,
                    }} />
                    <span style={{ fontWeight: 700, fontSize: "1rem", color: colors.inkPrimary }}>{s.label_ko}</span>
                    <span style={{ fontSize: "0.75rem", color: s.connected ? colors.successGreen : colors.inkMuted }}>
                      {s.connected ? "연결됨" : "연결 안됨"}
                    </span>
                  </div>
                  <span style={{ fontSize: "0.875rem", fontWeight: 700, color: s.completeness_pct >= 80 ? colors.successGreen : colors.warningAmber }}>
                    {s.completeness_pct}%
                  </span>
                </div>
                {/* Progress bar */}
                <div style={{ height: "6px", background: colors.canvasFog, borderRadius: "9999px", overflow: "hidden" }}>
                  <div style={{
                    height: "100%",
                    width: `${s.completeness_pct}%`,
                    background: s.completeness_pct >= 80 ? colors.successGreen : colors.warningAmber,
                    borderRadius: "9999px",
                    transition: "width 600ms",
                  }} />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* VARIABLE REGISTRY */}
        {section === "registry" && (
          <div style={{ background: colors.cloudWhite, borderRadius: radius.card, boxShadow: shadow.card, border: `1px solid ${colors.stoneBorder}`, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: colors.canvasFog, borderBottom: `1px solid ${colors.stoneBorder}` }}>
                  {["정규명", "표시명", "단위", "결측처리", "연결 소스"].map(h => (
                    <th key={h} style={{ padding: "12px 16px", textAlign: "left", fontSize: "0.75rem", fontWeight: 700, color: colors.inkSecondary, letterSpacing: "0.04em", textTransform: "uppercase" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {STUB_REGISTRY.map((v, i) => (
                  <tr key={v.canonical_name} style={{ borderBottom: i < STUB_REGISTRY.length - 1 ? `1px solid ${colors.stoneBorder}` : "none" }}>
                    <td style={{ padding: "12px 16px", fontFamily: "monospace", fontSize: "0.875rem", color: colors.chartwellBlue }}>{v.canonical_name}</td>
                    <td style={{ padding: "12px 16px", color: colors.inkPrimary }}>{v.display_name_ko}</td>
                    <td style={{ padding: "12px 16px", color: colors.inkMuted, fontFamily: "monospace" }}>{v.unit}</td>
                    <td style={{ padding: "12px 16px" }}>
                      <span style={{ background: colors.canvasFog, borderRadius: "4px", padding: "2px 8px", fontSize: "0.75rem", fontFamily: "monospace", color: colors.inkSecondary }}>{v.impute}</span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                        {v.sources.map(src => (
                          <span key={src} style={{ background: colors.chartwellBlueBg, color: colors.chartwellBlue, borderRadius: radius.badge, padding: "2px 8px", fontSize: "0.7rem", fontWeight: 600 }}>{src}</span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* PIPELINE */}
        {section === "pipeline" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                onClick={handleTrigger}
                disabled={triggering || triggered}
                style={{
                  background: triggered ? colors.successGreen : colors.chartwellBlue,
                  color: colors.cloudWhite, border: "none",
                  borderRadius: radius.button, padding: "10px 24px",
                  fontSize: "0.9375rem", fontWeight: 700, cursor: triggering || triggered ? "not-allowed" : "pointer",
                  minHeight: "44px", transition: "background 200ms",
                }}
              >
                {triggered ? "✓ 대기 중" : triggering ? "처리 중..." : "수동 재학습 트리거"}
              </button>
            </div>
            <div style={{ background: colors.cloudWhite, borderRadius: radius.card, boxShadow: shadow.card, border: `1px solid ${colors.stoneBorder}`, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ background: colors.canvasFog, borderBottom: `1px solid ${colors.stoneBorder}` }}>
                    {["실행 ID", "트리거", "시작 시각", "소요시간", "상태", "R² 변화", "배포"].map(h => (
                      <th key={h} style={{ padding: "12px 16px", textAlign: "left", fontSize: "0.75rem", fontWeight: 700, color: colors.inkSecondary, letterSpacing: "0.04em", textTransform: "uppercase" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {STUB_RUNS.map((r, i) => (
                    <tr key={r.run_id} style={{ borderBottom: i < STUB_RUNS.length - 1 ? `1px solid ${colors.stoneBorder}` : "none" }}>
                      <td style={{ padding: "14px 16px", fontFamily: "monospace", fontSize: "0.875rem", color: colors.inkMuted }}>{r.run_id}</td>
                      <td style={{ padding: "14px 16px", color: colors.inkSecondary }}>{r.trigger === "scheduled" ? "자동" : "수동"}</td>
                      <td style={{ padding: "14px 16px", color: colors.inkSecondary, fontSize: "0.875rem" }}>{r.started_at}</td>
                      <td style={{ padding: "14px 16px", color: colors.inkSecondary }}>{r.duration}</td>
                      <td style={{ padding: "14px 16px" }}>
                        <span style={{
                          display: "inline-block", padding: "3px 10px", borderRadius: radius.badge,
                          fontSize: "0.75rem", fontWeight: 700,
                          background: r.status === "success" ? colors.successBg : r.status === "running" ? colors.chartwellBlueBg : colors.dangerBg,
                          color: r.status === "success" ? colors.successGreen : r.status === "running" ? colors.chartwellBlue : colors.dangerRed,
                        }}>
                          {r.status === "success" ? "완료" : r.status === "running" ? "실행 중" : "실패"}
                        </span>
                      </td>
                      <td style={{ padding: "14px 16px", color: r.r2_after != null && r.r2_before != null && r.r2_after > r.r2_before ? colors.successGreen : colors.inkMuted }}>
                        {r.r2_before != null ? `${r.r2_before} → ${r.r2_after}` : "—"}
                      </td>
                      <td style={{ padding: "14px 16px" }}>
                        {r.deployed === null ? <span style={{ color: colors.inkMuted }}>—</span>
                          : r.deployed
                            ? <span style={{ color: colors.successGreen, fontWeight: 700 }}>배포됨</span>
                            : <span style={{ color: colors.dangerRed }}>미배포</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        button:focus-visible { outline: 3px solid ${colors.chartwellBlueBg}; outline-offset: 2px; }
        @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
      `}</style>
    </div>
  );
}
