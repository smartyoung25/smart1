import { useState, useEffect } from "react";
import { colors, radius, shadow } from "../design-system/tokens";

// ── Types ──────────────────────────────────────────────────────────────────────

interface Overview {
  connected_farms: number;
  iot_farms: number;
  avg_model_r2: number;
  models_loaded: number;
  data_completeness_pct: number;
  income_improvement_pct: number;
}

interface CropModel {
  crop_ko: string;
  crop_en: string;
  status: "loaded" | "no_model";
  model_type: string | null;
  train_r2: number | null;
  train_mape: number | null;
  test_r2: number | null;
  test_mape: number | null;
  feature_count: number | null;
  n_train: number | null;
  n_test: number | null;
  opt_temp: number | null;
  opt_humid: number | null;
  opt_co2: number | null;
  income_6m_krw: number | null;
}

interface DataSource {
  source_id: string;
  label_ko: string;
  connected: boolean;
  completeness_pct: number;
}

interface VariableRow {
  canonical_name: string;
  display_name_ko: string;
  unit: string;
  impute_strategy: string;
  sources: { source_id: string; source_field: string; transform_expr?: string }[];
}

interface PipelineRun {
  run_id: string;
  trigger: string;
  status: string;
  metrics_after: {
    train_r2: number | null;
    train_mape: number | null;
    test_r2: number | null;
    n_train: number | null;
    n_test: number | null;
  } | null;
  deployed: boolean | null;
}

// ── Fetch helper ──────────────────────────────────────────────────────────────

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json() as Promise<T>;
}

// ── Component ─────────────────────────────────────────────────────────────────

type Section = "overview" | "models" | "sources" | "registry" | "pipeline";

const NAV_ITEMS: { key: Section; label: string }[] = [
  { key: "overview",  label: "전체 현황" },
  { key: "models",    label: "AI 모델" },
  { key: "sources",   label: "데이터 소스" },
  { key: "registry",  label: "변수 레지스트리" },
  { key: "pipeline",  label: "학습 파이프라인" },
];

// R² 신호등 색상
function r2Color(v: number | null): string {
  if (v === null) return colors.inkMuted;
  if (v >= 0.90) return colors.successGreen;
  if (v >= 0.70) return colors.warningAmber;
  return colors.dangerRed;
}

// 배지 스타일
function badge(ok: boolean) {
  return {
    display: "inline-block", padding: "3px 10px", borderRadius: radius.badge,
    fontSize: "0.72rem", fontWeight: 700,
    background: ok ? colors.successBg : colors.dangerBg,
    color:      ok ? colors.successGreen : colors.dangerRed,
  } as React.CSSProperties;
}

export function AdminDashboard() {
  const [section,    setSection]    = useState<Section>("overview");
  const [overview,   setOverview]   = useState<Overview | null>(null);
  const [cropModels, setCropModels] = useState<CropModel[]>([]);
  const [sources,    setSources]    = useState<DataSource[]>([]);
  const [registry,   setRegistry]   = useState<VariableRow[]>([]);
  const [runs,       setRuns]       = useState<PipelineRun[]>([]);
  const [triggering, setTriggering] = useState(false);
  const [triggered,  setTriggered]  = useState(false);
  const [err,        setErr]        = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetchJson<Overview>("/api/admin/overview"),
      fetchJson<{ crops: CropModel[] }>("/api/admin/models/crops"),
      fetchJson<{ sources: DataSource[] }>("/api/admin/data-sources"),
      fetchJson<{ variables: VariableRow[] }>("/api/admin/variable-registry"),
      fetchJson<{ runs: PipelineRun[] }>("/api/admin/pipeline/runs"),
    ]).then(([ov, cm, sr, vr, pr]) => {
      setOverview(ov);
      setCropModels(cm.crops);
      setSources(sr.sources);
      setRegistry(vr.variables);
      setRuns(pr.runs);
    }).catch(e => setErr(String(e)));
  }, []);

  async function handleTrigger() {
    setTriggering(true);
    try {
      await fetch("/api/admin/pipeline/trigger", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "manual" }),
      });
      setTriggered(true);
    } finally { setTriggering(false); }
  }

  // ── Shared styles ────────────────────────────────────────────────────────────

  const card: React.CSSProperties = {
    background: colors.cloudWhite, borderRadius: radius.card,
    boxShadow: shadow.card, border: `1px solid ${colors.stoneBorder}`,
  };
  const th: React.CSSProperties = {
    padding: "12px 16px", textAlign: "left",
    fontSize: "0.72rem", fontWeight: 700,
    color: colors.inkSecondary, letterSpacing: "0.04em", textTransform: "uppercase",
  };
  const td: React.CSSProperties = { padding: "13px 16px", fontSize: "0.875rem" };

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: "'Inter', sans-serif", background: colors.canvasFog, WebkitFontSmoothing: "antialiased" as any }}>

      {/* Sidebar */}
      <aside style={{
        width: 220, flexShrink: 0, background: colors.cloudWhite,
        borderRight: `1px solid ${colors.stoneBorder}`,
        display: "flex", flexDirection: "column",
        position: "sticky", top: 0, height: "100vh",
      }}>
        <div style={{ padding: "20px 16px 16px", borderBottom: `1px solid ${colors.stoneBorder}` }}>
          <p style={{ fontSize: "0.7rem", fontWeight: 600, color: colors.inkMuted, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 4 }}>플랫폼 관리</p>
          <p style={{ fontSize: "1rem", fontWeight: 800, color: colors.inkPrimary }}>Smart Farm</p>
        </div>
        <nav style={{ padding: 8 }}>
          {NAV_ITEMS.map(({ key, label }) => (
            <button key={key} onClick={() => setSection(key)} style={{
              display: "block", width: "100%", textAlign: "left",
              padding: "10px 12px", marginBottom: 2,
              borderRadius: 8, border: "none",
              background: section === key ? colors.chartwellBlueBg : "none",
              color: section === key ? colors.chartwellBlue : colors.inkSecondary,
              fontWeight: section === key ? 700 : 500,
              fontSize: "0.9375rem", cursor: "pointer",
              transition: "background 150ms, color 150ms",
            }}>{label}</button>
          ))}
        </nav>

        {/* 농가 현황 미니 패널 */}
        {overview && (
          <div style={{ marginTop: "auto", padding: "12px", borderTop: `1px solid ${colors.stoneBorder}` }}>
            <div style={{ fontSize: "0.72rem", color: colors.inkMuted, marginBottom: 6 }}>연결 현황</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem" }}>
                <span style={{ color: colors.inkSecondary }}>전체 농가</span>
                <span style={{ fontWeight: 700, color: colors.inkPrimary }}>{overview.connected_farms}개</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem" }}>
                <span style={{ color: colors.inkSecondary }}>IoT 구축</span>
                <span style={{ fontWeight: 700, color: colors.successGreen }}>{overview.iot_farms}개</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem" }}>
                <span style={{ color: colors.inkSecondary }}>모델 로드</span>
                <span style={{ fontWeight: 700, color: colors.chartwellBlue }}>{overview.models_loaded}개</span>
              </div>
            </div>
          </div>
        )}
      </aside>

      {/* Main */}
      <main style={{ flex: 1, padding: 24, overflow: "auto" }}>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 800, color: colors.inkPrimary, marginBottom: 20 }}>
          {NAV_ITEMS.find(n => n.key === section)?.label}
        </h1>

        {err && (
          <div style={{ background: colors.dangerBg, border: `1px solid ${colors.dangerRed}`, borderRadius: 8, padding: "12px 16px", marginBottom: 16, color: colors.dangerRed, fontSize: "0.85rem" }}>
            API 오류: {err}
          </div>
        )}

        {/* ── OVERVIEW ─────────────────────────────────────────────────── */}
        {section === "overview" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 16 }}>
              {overview ? [
                { label: "연결 농가",     value: `${overview.connected_farms}개`,               color: colors.chartwellBlue },
                { label: "IoT 구축",      value: `${overview.iot_farms}개`,                     color: colors.successGreen  },
                { label: "평균 훈련 R²", value: overview.avg_model_r2.toFixed(3),              color: r2Color(overview.avg_model_r2) },
                { label: "로드된 모델",   value: `${overview.models_loaded}개`,                 color: colors.chartwellBlue },
                { label: "데이터 완전성", value: `${overview.data_completeness_pct}%`,          color: colors.warningAmber  },
                { label: "소득 향상률",   value: `+${overview.income_improvement_pct.toFixed(1)}%`, color: colors.successGreen },
              ].map(({ label, value, color }) => (
                <div key={label} style={{ ...card, padding: 20 }}>
                  <p style={{ fontSize: "0.82rem", color: colors.inkSecondary, marginBottom: 8 }}>{label}</p>
                  <p style={{ fontSize: "1.75rem", fontWeight: 800, color }}>{value}</p>
                </div>
              )) : (
                <div style={{ gridColumn: "1/-1", textAlign: "center", padding: 40, color: colors.inkMuted }}>불러오는 중…</div>
              )}
            </div>

            {/* 작목별 모델 요약 미니 테이블 */}
            {cropModels.length > 0 && (
              <div style={{ ...card, overflow: "hidden" }}>
                <div style={{ padding: "16px 20px", borderBottom: `1px solid ${colors.stoneBorder}` }}>
                  <span style={{ fontWeight: 700, color: colors.inkPrimary }}>작목별 모델 요약</span>
                </div>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ background: colors.canvasFog, borderBottom: `1px solid ${colors.stoneBorder}` }}>
                      {["작목", "상태", "훈련 R²", "훈련 MAPE", "학습 데이터"].map(h => (
                        <th key={h} style={th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {cropModels.map((m, i) => (
                      <tr key={m.crop_ko} style={{ borderBottom: i < cropModels.length - 1 ? `1px solid ${colors.stoneBorder}` : "none" }}>
                        <td style={{ ...td, fontWeight: 700, color: colors.inkPrimary }}>{m.crop_ko}</td>
                        <td style={td}>
                          <span style={badge(m.status === "loaded")}>{m.status === "loaded" ? "로드됨" : "없음"}</span>
                        </td>
                        <td style={{ ...td, fontWeight: 700, color: r2Color(m.train_r2) }}>
                          {m.train_r2 != null ? m.train_r2.toFixed(3) : "—"}
                        </td>
                        <td style={{ ...td, color: colors.inkSecondary }}>
                          {m.train_mape != null ? `${m.train_mape.toFixed(1)}%` : "—"}
                        </td>
                        <td style={{ ...td, color: colors.inkMuted }}>
                          {m.n_train != null ? `${m.n_train.toLocaleString()}행` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── AI 모델 (작목별 상세) ─────────────────────────────────────── */}
        {section === "models" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {cropModels.length === 0
              ? <div style={{ textAlign: "center", padding: 40, color: colors.inkMuted }}>불러오는 중…</div>
              : cropModels.map(m => (
              <div key={m.crop_ko} style={{ ...card, overflow: "hidden" }}>
                {/* 헤더 */}
                <div style={{
                  padding: "14px 20px", borderBottom: `1px solid ${colors.stoneBorder}`,
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ fontWeight: 800, fontSize: "1rem", color: colors.inkPrimary }}>{m.crop_ko}</span>
                    <span style={{ fontSize: "0.72rem", color: colors.inkMuted, fontFamily: "monospace" }}>{m.crop_en}</span>
                    <span style={badge(m.status === "loaded")}>{m.status === "loaded" ? "로드됨" : "모델 없음"}</span>
                    {m.model_type && (
                      <span style={{ fontSize: "0.72rem", background: colors.chartwellBlueBg, color: colors.chartwellBlue, borderRadius: radius.badge, padding: "2px 8px", fontWeight: 600 }}>
                        {m.model_type === "xgb_lgb_ensemble" ? "XGB+LGB" : m.model_type}
                      </span>
                    )}
                  </div>
                  {m.feature_count != null && (
                    <span style={{ fontSize: "0.78rem", color: colors.inkMuted }}>피처 {m.feature_count}개</span>
                  )}
                </div>

                {m.status === "loaded" && (
                  <div style={{ padding: "16px 20px", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
                    {[
                      { label: "훈련 R²",   value: m.train_r2?.toFixed(3),   color: r2Color(m.train_r2) },
                      { label: "훈련 MAPE", value: m.train_mape != null ? `${m.train_mape.toFixed(1)}%` : null, color: colors.inkPrimary },
                      { label: "검증 R²",   value: m.test_r2?.toFixed(3),    color: r2Color(m.test_r2) },
                      { label: "검증 MAPE", value: m.test_mape != null ? `${m.test_mape.toFixed(1)}%` : null, color: colors.inkPrimary },
                      { label: "학습 행수", value: m.n_train?.toLocaleString(), color: colors.inkPrimary },
                      { label: "검증 행수", value: m.n_test?.toLocaleString(),  color: colors.inkPrimary },
                    ].map(({ label, value, color }) => (
                      <div key={label} style={{ background: colors.canvasFog, borderRadius: 8, padding: "10px 12px" }}>
                        <p style={{ fontSize: "0.72rem", color: colors.inkMuted, marginBottom: 4 }}>{label}</p>
                        <p style={{ fontSize: "1rem", fontWeight: 800, color }}>{value ?? "—"}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* 최적 환경 조합 */}
                {m.status === "loaded" && m.opt_temp != null && (
                  <div style={{
                    margin: "0 20px 16px", padding: "12px 14px",
                    background: "#f0fdf4", borderRadius: 8,
                    border: "1px solid #86efac",
                    fontSize: "0.82rem", color: colors.inkSecondary,
                    display: "flex", flexWrap: "wrap", gap: "0 24px",
                  }}>
                    <span>🌡️ 최적 온도 <strong style={{ color: colors.inkPrimary }}>{m.opt_temp}°C</strong></span>
                    <span>💧 최적 습도 <strong style={{ color: colors.inkPrimary }}>{m.opt_humid}%</strong></span>
                    <span>🌿 최적 CO₂ <strong style={{ color: colors.inkPrimary }}>{m.opt_co2} ppm</strong></span>
                    {m.income_6m_krw != null && (
                      <span>💰 6개월 예측 소득 <strong style={{ color: colors.successGreen }}>{Math.round(m.income_6m_krw / 10000).toLocaleString()}만원</strong></span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* ── 데이터 소스 ───────────────────────────────────────────────── */}
        {section === "sources" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {sources.length === 0
              ? <div style={{ textAlign: "center", padding: 40, color: colors.inkMuted }}>불러오는 중…</div>
              : sources.map(s => (
              <div key={s.source_id} style={{ ...card, padding: "16px 20px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: "50%",
                      background: s.connected ? colors.successGreen : colors.inkMuted,
                      display: "inline-block", flexShrink: 0,
                    }} />
                    <span style={{ fontWeight: 700, fontSize: "1rem", color: colors.inkPrimary }}>{s.label_ko}</span>
                    <span style={{ fontSize: "0.75rem", color: s.connected ? colors.successGreen : colors.inkMuted }}>
                      {s.connected ? "연결됨" : "미연결"}
                    </span>
                  </div>
                  <span style={{ fontSize: "0.875rem", fontWeight: 700, color: s.completeness_pct >= 80 ? colors.successGreen : colors.warningAmber }}>
                    {s.completeness_pct}%
                  </span>
                </div>
                <div style={{ height: 6, background: colors.canvasFog, borderRadius: 9999, overflow: "hidden" }}>
                  <div style={{
                    height: "100%", borderRadius: 9999, transition: "width 600ms",
                    width: `${s.completeness_pct}%`,
                    background: s.completeness_pct >= 80 ? colors.successGreen : colors.warningAmber,
                  }} />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── 변수 레지스트리 ───────────────────────────────────────────── */}
        {section === "registry" && (
          <div style={{ ...card, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: colors.canvasFog, borderBottom: `1px solid ${colors.stoneBorder}` }}>
                  {["정규명", "표시명", "단위", "결측처리", "연결 소스"].map(h => (
                    <th key={h} style={th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {registry.length === 0
                  ? <tr><td colSpan={5} style={{ padding: 40, textAlign: "center", color: colors.inkMuted }}>불러오는 중…</td></tr>
                  : registry.map((v, i) => (
                  <tr key={v.canonical_name} style={{ borderBottom: i < registry.length - 1 ? `1px solid ${colors.stoneBorder}` : "none" }}>
                    <td style={{ ...td, fontFamily: "monospace", color: colors.chartwellBlue }}>{v.canonical_name}</td>
                    <td style={{ ...td, color: colors.inkPrimary, fontWeight: 500 }}>{v.display_name_ko}</td>
                    <td style={{ ...td, fontFamily: "monospace", color: colors.inkMuted }}>{v.unit}</td>
                    <td style={td}>
                      <span style={{ background: colors.canvasFog, borderRadius: 4, padding: "2px 8px", fontSize: "0.75rem", fontFamily: "monospace", color: colors.inkSecondary }}>
                        {v.impute_strategy}
                      </span>
                    </td>
                    <td style={td}>
                      <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                        {v.sources.map(src => (
                          <span key={src.source_id + src.source_field} style={{
                            background: colors.chartwellBlueBg, color: colors.chartwellBlue,
                            borderRadius: radius.badge, padding: "2px 8px",
                            fontSize: "0.7rem", fontWeight: 600,
                          }}>
                            {src.source_id}
                            {src.transform_expr && <span style={{ opacity: 0.7, marginLeft: 3 }}>({src.transform_expr})</span>}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* ── 학습 파이프라인 ───────────────────────────────────────────── */}
        {section === "pipeline" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button onClick={handleTrigger} disabled={triggering || triggered} style={{
                background: triggered ? colors.successGreen : colors.chartwellBlue,
                color: colors.cloudWhite, border: "none",
                borderRadius: radius.button, padding: "10px 24px",
                fontSize: "0.9375rem", fontWeight: 700,
                cursor: triggering || triggered ? "not-allowed" : "pointer",
                minHeight: 44, transition: "background 200ms",
              }}>
                {triggered ? "✓ 대기 중" : triggering ? "처리 중…" : "수동 재학습 트리거"}
              </button>
            </div>

            <div style={{ ...card, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ background: colors.canvasFog, borderBottom: `1px solid ${colors.stoneBorder}` }}>
                    {["실행 ID", "트리거", "상태", "훈련 R²", "검증 R²", "학습행", "검증행", "배포"].map(h => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.length === 0
                    ? <tr><td colSpan={8} style={{ padding: 40, textAlign: "center", color: colors.inkMuted }}>불러오는 중…</td></tr>
                    : runs.map((r, i) => {
                      const m = r.metrics_after;
                      return (
                        <tr key={r.run_id} style={{ borderBottom: i < runs.length - 1 ? `1px solid ${colors.stoneBorder}` : "none" }}>
                          <td style={{ ...td, fontFamily: "monospace", fontSize: "0.8rem", color: colors.inkMuted }}>{r.run_id}</td>
                          <td style={{ ...td, color: colors.inkSecondary }}>
                            {r.trigger === "scheduled" ? "자동" : r.trigger === "scripted" ? "스크립트" : "수동"}
                          </td>
                          <td style={td}>
                            <span style={badge(r.status === "success")}>
                              {r.status === "success" ? "완료" : r.status === "running" ? "실행 중" : "실패"}
                            </span>
                          </td>
                          <td style={{ ...td, fontWeight: 700, color: r2Color(m?.train_r2 ?? null) }}>
                            {m?.train_r2 != null ? m.train_r2.toFixed(3) : "—"}
                          </td>
                          <td style={{ ...td, fontWeight: 700, color: r2Color(m?.test_r2 ?? null) }}>
                            {m?.test_r2 != null ? m.test_r2.toFixed(3) : "—"}
                          </td>
                          <td style={{ ...td, color: colors.inkMuted }}>
                            {m?.n_train != null ? m.n_train.toLocaleString() : "—"}
                          </td>
                          <td style={{ ...td, color: colors.inkMuted }}>
                            {m?.n_test != null ? m.n_test.toLocaleString() : "—"}
                          </td>
                          <td style={td}>
                            {r.deployed === null ? <span style={{ color: colors.inkMuted }}>—</span>
                              : r.deployed
                                ? <span style={{ color: colors.successGreen, fontWeight: 700 }}>배포됨</span>
                                : <span style={{ color: colors.dangerRed }}>미배포</span>}
                          </td>
                        </tr>
                      );
                    })}
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
