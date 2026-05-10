import { useState, useEffect, useCallback } from "react";
import { colors, radius, shadow } from "../design-system/tokens";
import { HeroRecommendation, MinorRecommendation } from "../components/HeroRecommendation";
import { AiChat } from "../components/AiChat";
import { CostInputForm } from "../components/CostInputForm";
import { FarmSettings } from "../components/FarmSettings";

// ── Types ─────────────────────────────────────────────────────────────────────

interface FarmAlert {
  id: string;
  severity: "danger" | "warning" | "info";
  variable: string;
  message_ko: string;
  value: number;
  threshold: number;
  unit: string;
}
interface FarmMeta {
  farm_id: string; name: string; crop: string;
  tier: string; iot_available: boolean; area_m2: number;
  sido?: string | null; sigungu?: string | null;
  address_detail?: string | null; asos_station_id?: number | null;
}
interface Summary {
  alert_count: number; alerts: FarmAlert[];
  harvest_days_remaining: number | null; revenue_mtd_krw: number;
}
interface Recommendation {
  rank: number; action_ko: string; profit_delta: number;
  confidence: number; tier_action: "checklist" | "approval_required" | "auto";
}
interface EnvPoint {
  canonical_name: string; value: number; unit: string;
  quality_tag: string; imputed: boolean;
}
interface EnvSection {
  source: string;       // "iot" | "manual_input" | "asos" | "none"
  label_ko: string;
  editable: boolean;
  has_data: boolean;
  measurements: EnvPoint[];
}
interface EnvData {
  iot_available: boolean;
  indoor: EnvSection;
  outdoor: EnvSection;
  measurements: EnvPoint[];  // legacy
}
interface Revenue {
  kamis_price_krw_kg: number; predicted_revenue_krw: number;
  predicted_cost_krw: number; predicted_profit_krw: number;
}
interface CostItem {
  category: string; label_ko: string; amount_krw: number;
  unit_label: string; pct_of_total: number;
}
interface ManualCostInput {
  electricity_kwh_month?: number; electricity_rate?: number;
  water_m3_month?: number;        water_rate?: number;
  heating_kwh_month?: number;     heating_rate?: number;
  labor_hours_month?: number;     labor_rate?: number;
  nutrients_krw_month?: number;   pesticides_krw_month?: number;
}
interface CostBreakdown {
  items: CostItem[]; total_cost_krw: number; cost_per_m2: number;
  electricity_kwh_month: number; water_m3_month: number;
  has_manual_input: boolean; manual_input: ManualCostInput | null;
}

// ── Fetch helper ──────────────────────────────────────────────────────────────

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API ${url} → ${res.status}`);
  return res.json() as Promise<T>;
}

// ── 관측소 번호 → 지점명 ──────────────────────────────────────────────────────
const STATION_NAMES: Record<number, string> = {
  101: "춘천", 105: "강릉", 108: "서울", 112: "인천", 114: "원주",
  119: "수원", 127: "충주", 129: "서산", 131: "청주", 133: "천안",
  136: "안동", 137: "상주", 138: "포항", 140: "군산", 143: "대구",
  146: "전주", 152: "울산", 155: "창원", 156: "광주", 159: "부산",
  168: "순천", 177: "논산", 184: "제주", 189: "서귀포", 192: "진주",
  202: "여주", 203: "파주", 212: "홍천", 221: "평창", 243: "부안",
  244: "고창", 247: "남원", 261: "해남", 271: "영주", 288: "밀양",
  289: "보령",
};

// ── 관측소 배너 컴포넌트 ────────────────────────────────────────────────────────
function StationBanner({ stationId, sido, sigungu }: {
  stationId?: number | null; sido?: string | null; sigungu?: string | null;
}) {
  if (!stationId) return null;
  const name = STATION_NAMES[stationId] ?? `${stationId}번`;
  const location = [sido, sigungu].filter(Boolean).join(" ") || name;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "8px",
      padding: "8px 14px",
      background: "#f0f9ff",
      border: "1px solid #bae6fd",
      borderRadius: "8px",
      marginBottom: "12px",
      fontSize: "0.8rem",
      color: "#0369a1",
    }}>
      <span>🌤️</span>
      <span>
        기상청 ASOS <strong>{name}({stationId})</strong> 관측소 연결
        {location !== name && <span style={{ color: "#64748b", marginLeft: 6 }}>— {location}</span>}
      </span>
    </div>
  );
}

// ── 환경 변수 한글 레이블 ─────────────────────────────────────────────────────
const ENV_LABELS: Record<string, string> = {
  temp_internal:  "내부 온도",
  temp_external:  "외부 온도",
  humidity_int:   "내부 습도",
  humidity_ext:   "외부 습도",
  co2_ppm:        "CO₂ 농도",
  solar_rad:      "일사량",
  solar_rad_est:  "추정 일사량",
  ec_dsm:         "EC (양액)",
  soil_temp:      "지온",
  wind_speed_ext: "풍속",
};

const ENV_INPUT_FIELDS = [
  { key: "temp_internal", label: "내부 온도",  unit: "°C",   min: 0,   max: 50,   step: 0.1, placeholder: "예: 22.5" },
  { key: "humidity_int",  label: "내부 습도",  unit: "%",    min: 20,  max: 100,  step: 1,   placeholder: "예: 75" },
  { key: "co2_ppm",       label: "CO₂ 농도",  unit: "ppm",  min: 300, max: 2000, step: 10,  placeholder: "예: 900" },
  { key: "solar_rad",     label: "일사량",     unit: "W/m²", min: 0,   max: 1200, step: 10,  placeholder: "예: 350" },
  { key: "ec_dsm",        label: "EC (양액)",  unit: "dS/m", min: 0.5, max: 5.0,  step: 0.1, placeholder: "예: 2.1" },
  { key: "soil_temp",     label: "지온",       unit: "°C",   min: 5,   max: 35,   step: 0.1, placeholder: "예: 18.0" },
];

// ── 측정값 그리드 (실내/실외 공용) ───────────────────────────────────────────
function EnvValueGrid({ measurements }: { measurements: EnvPoint[] }) {
  if (!measurements.length) return null;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
      {measurements.map(pt => (
        <div key={pt.canonical_name} style={{
          background: "#f8fafc", borderRadius: radius.input,
          padding: "10px 12px",
          display: "flex", flexDirection: "column", gap: "2px",
        }}>
          <span style={{ fontSize: "0.72rem", color: colors.inkMuted, fontWeight: 500 }}>
            {ENV_LABELS[pt.canonical_name] ?? pt.canonical_name}
          </span>
          <span style={{ fontSize: "1.1rem", fontWeight: 600, color: colors.inkPrimary }}>
            {pt.value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}
            <span style={{ fontSize: "0.75rem", fontWeight: 400, color: colors.inkMuted, marginLeft: 3 }}>
              {pt.unit}
            </span>
          </span>
          {pt.imputed && (
            <span style={{ fontSize: "0.65rem", color: colors.chartwellBlue }}>추정값</span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── 실내 환경 수동 입력 인라인 폼 ────────────────────────────────────────────
function InlineEnvForm({ farmId, storedValues, onSaved, onCancel }: {
  farmId: string;
  storedValues: Record<string, number> | null;
  onSaved: (v: Record<string, number>) => void;
  onCancel: () => void;
}) {
  const init: Record<string, string> = {};
  ENV_INPUT_FIELDS.forEach(f => {
    init[f.key] = storedValues?.[f.key] != null ? String(storedValues[f.key]) : "";
  });
  const [vals, setVals]     = useState<Record<string, string>>(init);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [apiErr, setApiErr] = useState<string | null>(null);

  function handleChange(key: string, raw: string) {
    setVals(p => ({ ...p, [key]: raw }));
    setErrors(p => ({ ...p, [key]: "" }));
    setApiErr(null);
  }

  function validate() {
    const next: Record<string, string> = {};
    let ok = true;
    for (const f of ENV_INPUT_FIELDS) {
      const raw = vals[f.key].trim();
      if (!raw) continue;
      const num = parseFloat(raw);
      if (isNaN(num)) { next[f.key] = "숫자를 입력해주세요"; ok = false; }
      else if (num < f.min || num > f.max) { next[f.key] = `${f.min}~${f.max} ${f.unit}`; ok = false; }
    }
    setErrors(next);
    return ok;
  }

  async function handleSave() {
    if (!validate()) return;
    const payload: Record<string, number> = {};
    for (const f of ENV_INPUT_FIELDS) {
      const raw = vals[f.key].trim();
      if (raw) payload[f.key] = parseFloat(raw);
    }
    if (!Object.keys(payload).length) { setApiErr("최소 하나 이상의 값을 입력해 주세요."); return; }
    setSaving(true);
    try {
      const res = await fetch(`/api/farms/${farmId}/environment/manual`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      onSaved(payload);
    } catch (e: unknown) {
      setApiErr(e instanceof Error ? e.message : "저장에 실패했습니다.");
    } finally { setSaving(false); }
  }

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "12px" }}>
        {ENV_INPUT_FIELDS.map(f => (
          <div key={f.key}>
            <label style={{ display: "block", fontSize: "0.72rem", color: colors.inkMuted, fontWeight: 500, marginBottom: 4 }}>
              {f.label} <span style={{ color: colors.inkMuted }}>({f.unit})</span>
            </label>
            <input
              type="number" inputMode="decimal"
              min={f.min} max={f.max} step={f.step}
              placeholder={f.placeholder}
              value={vals[f.key]}
              onChange={e => handleChange(f.key, e.target.value)}
              style={{
                width: "100%", padding: "8px 10px", fontSize: "0.9rem",
                border: `1.5px solid ${errors[f.key] ? colors.dangerRed : "#e2e8f0"}`,
                borderRadius: radius.input, outline: "none",
                background: "#fff", boxSizing: "border-box",
              }}
            />
            {errors[f.key] && (
              <span style={{ fontSize: "0.68rem", color: colors.dangerRed }}>{errors[f.key]}</span>
            )}
          </div>
        ))}
      </div>
      {apiErr && <p style={{ fontSize: "0.8rem", color: colors.dangerRed, marginBottom: 8 }}>{apiErr}</p>}
      <div style={{ display: "flex", gap: "8px" }}>
        <button onClick={handleSave} disabled={saving} style={{
          flex: 1, padding: "10px", borderRadius: "9999px", border: "none",
          background: saving ? "#94a3b8" : colors.chartwellBlue,
          color: "#fff", fontWeight: 600, fontSize: "0.9rem", cursor: saving ? "not-allowed" : "pointer",
        }}>
          {saving ? "저장 중..." : "저장"}
        </button>
        <button onClick={onCancel} style={{
          padding: "10px 16px", borderRadius: "9999px",
          border: "1.5px solid #e2e8f0", background: "#fff",
          color: colors.inkMuted, fontSize: "0.9rem", cursor: "pointer",
        }}>
          취소
        </button>
      </div>
    </div>
  );
}

// ── 실내·외부 환경 2패널 ─────────────────────────────────────────────────────
function EnvTwoPanel({ envData, farmId, manualValues, onSaved }: {
  envData: EnvData | null;
  farmId: string;
  manualValues: Record<string, number> | null;
  onSaved: (v: Record<string, number>) => void;
}) {
  const [editMode, setEditMode] = useState(false);

  if (!envData) return (
    <div style={{ textAlign: "center", padding: "40px", color: colors.inkMuted }}>
      환경 데이터를 불러오는 중입니다. 잠시 후 다시 시도해 주세요.
    </div>
  );

  const { indoor, outdoor } = envData;
  const isEditable = indoor.editable;
  const hasIndoor  = indoor.has_data && indoor.measurements.length > 0;
  const hasOutdoor = outdoor.has_data && outdoor.measurements.length > 0;

  function handleSaved(v: Record<string, number>) {
    setEditMode(false);
    onSaved(v);
  }

  const sourceBadge = (source: string) => {
    const conf: Record<string, { label: string; color: string; bg: string }> = {
      iot:          { label: "IoT 센서",   color: colors.successGreen, bg: "#f0fdf4" },
      manual_input: { label: "수동 입력",  color: colors.warningAmber, bg: "#fffbeb" },
      asos:         { label: "기상청",     color: colors.chartwellBlue, bg: "#eff6ff" },
      none:         { label: "미입력",     color: colors.inkMuted, bg: "#f1f5f9" },
    };
    const c = conf[source] ?? conf.none;
    return (
      <span style={{
        fontSize: "0.68rem", fontWeight: 600, padding: "2px 8px",
        borderRadius: "9999px", background: c.bg, color: c.color,
        marginLeft: 6,
      }}>{c.label}</span>
    );
  };

  const panelStyle: React.CSSProperties = {
    background: "#fff", borderRadius: radius.card,
    boxShadow: shadow.card, padding: "16px",
    display: "flex", flexDirection: "column", gap: "14px",
  };
  const headerStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", justifyContent: "space-between",
  };
  const titleStyle: React.CSSProperties = {
    fontSize: "0.9rem", fontWeight: 700, color: colors.inkPrimary,
    display: "flex", alignItems: "center",
  };
  const editBtnStyle: React.CSSProperties = {
    fontSize: "0.78rem", fontWeight: 600, padding: "5px 14px",
    borderRadius: "9999px", border: `1.5px solid ${colors.chartwellBlue}`,
    background: "#fff", color: colors.chartwellBlue, cursor: "pointer",
  };

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
      gap: "14px",
    }}>
      {/* ── 실내 환경 패널 ─────────────────────────────────── */}
      <div style={panelStyle}>
        <div style={headerStyle}>
          <span style={titleStyle}>
            실내 환경{sourceBadge(indoor.source)}
          </span>
          {isEditable && !editMode && (
            <button style={editBtnStyle} onClick={() => setEditMode(true)}>
              {hasIndoor ? "수정" : "입력하기"}
            </button>
          )}
          {isEditable && editMode && (
            <button onClick={() => setEditMode(false)} style={{
              ...editBtnStyle,
              border: "1.5px solid #e2e8f0", color: colors.inkMuted,
            }}>취소</button>
          )}
        </div>

        {editMode ? (
          <InlineEnvForm
            farmId={farmId}
            storedValues={manualValues}
            onSaved={handleSaved}
            onCancel={() => setEditMode(false)}
          />
        ) : hasIndoor ? (
          <EnvValueGrid measurements={indoor.measurements} />
        ) : (
          <div style={{
            textAlign: "center", padding: "24px 12px",
            background: "#f8fafc", borderRadius: radius.input,
          }}>
            <div style={{ fontSize: "1.6rem", marginBottom: 8 }}>📋</div>
            <p style={{ fontSize: "0.85rem", color: colors.inkMuted, marginBottom: 12 }}>
              아직 실내 환경값이 없습니다.<br/>현재 농장 상태를 직접 입력하면 AI 추천 정확도가 높아집니다.
            </p>
            <button style={{
              ...editBtnStyle,
              background: colors.chartwellBlue, color: "#fff", border: "none",
            }} onClick={() => setEditMode(true)}>
              지금 입력하기
            </button>
          </div>
        )}
      </div>

      {/* ── 외부 기상 패널 ─────────────────────────────────── */}
      <div style={panelStyle}>
        <div style={headerStyle}>
          <span style={titleStyle}>
            외부 기상{sourceBadge(outdoor.source)}
          </span>
          <span style={{ fontSize: "0.72rem", color: colors.inkMuted }}>실시간 · 자동갱신</span>
        </div>

        {hasOutdoor ? (
          <EnvValueGrid measurements={outdoor.measurements} />
        ) : (
          <div style={{
            textAlign: "center", padding: "24px 12px",
            background: "#f8fafc", borderRadius: radius.input,
          }}>
            <p style={{ fontSize: "0.85rem", color: colors.inkMuted }}>
              기상청 ASOS 데이터를 불러올 수 없습니다.
            </p>
          </div>
        )}

        {/* 품질 설명 */}
        <div style={{
          fontSize: "0.7rem", color: colors.inkMuted, padding: "8px 10px",
          background: "#eff6ff", borderRadius: radius.input, lineHeight: 1.5,
        }}>
          기상청 ASOS 관측소 실측값 기반. 온실 내부와 외부 환경은 차이가 있을 수 있습니다.
        </div>
      </div>
    </div>
  );
}

// ── 톱니바퀴 아이콘 SVG ────────────────────────────────────────────────────────
function GearIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06
               a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09
               A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83
               l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09
               A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83
               l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09
               a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83
               l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09
               a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
  );
}

// ── Constants ─────────────────────────────────────────────────────────────────

const SEVERITY_COLORS = {
  danger:  { bg: colors.dangerBg,         text: colors.dangerRed,    border: colors.dangerRed },
  warning: { bg: colors.warningBg,        text: colors.warningAmber, border: colors.warningAmber },
  info:    { bg: colors.chartwellBlueBg,  text: colors.chartwellBlue, border: colors.chartwellBlue },
} as const;
const SEVERITY_LABEL = { danger: "위험", warning: "주의", info: "정보" } as const;

const COST_ICONS: Record<string, string> = {
  electricity: "⚡", water: "💧", heating: "🔥",
  labor: "👤", nutrients: "🌱", pesticides: "🧪",
};

type Tab = "recommendations" | "environment" | "harvest" | "revenue" | "costs" | "chat";

const TABS: { key: Tab; label: string }[] = [
  { key: "recommendations", label: "AI 추천"  },
  { key: "environment",     label: "환경"     },
  { key: "harvest",         label: "수확예측" },
  { key: "revenue",         label: "수익"     },
  { key: "costs",           label: "비용분석" },
  { key: "chat",            label: "AI 상담"  },
];

// ── Component ─────────────────────────────────────────────────────────────────

export function FarmerDashboard({ farmId = "farm_001" }: { farmId?: string }) {
  const [tab, setTab]                     = useState<Tab>("recommendations");
  const [alertPanelOpen, setAlertPanelOpen] = useState(false);
  const [meta,    setMeta]    = useState<FarmMeta | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [recs,    setRecs]    = useState<Recommendation[]>([]);
  const [envData, setEnvData] = useState<EnvData | null>(null);
  const [revenue, setRevenue] = useState<Revenue | null>(null);
  const [costs,   setCosts]   = useState<CostBreakdown | null>(null);
  const [loading, setLoading] = useState(true);
  const [manualValues, setManualValues] = useState<Record<string, number> | null>(null);
  const [showCostInput,    setShowCostInput]    = useState(false);
  const [showFarmSettings, setShowFarmSettings] = useState(false);

  // ── Fetch ──────────────────────────────────────────────────────────────────

  useEffect(() => {
    setLoading(true); setRecs([]); setEnvData(null);
    setManualValues(null); setAlertPanelOpen(false); setShowCostInput(false);
    Promise.all([
      fetchJson<FarmMeta>(`/api/farms/${farmId}/meta`),
      fetchJson<Summary>(`/api/farms/${farmId}/summary`),
    ]).then(([m, s]) => { setMeta(m); setSummary(s); })
      .catch(console.error).finally(() => setLoading(false));
  }, [farmId]);

  const refreshData = useCallback(() => {
    fetchJson<{ recommendations: Recommendation[] }>(`/api/farms/${farmId}/recommendations`)
      .then(r => setRecs(r.recommendations)).catch(console.error);
    fetchJson<EnvData>(`/api/farms/${farmId}/environment`)
      .then(r => {
        setEnvData(r);
        // Pre-populate manualValues from stored indoor measurements so the
        // edit form is not blank when re-opening on an IoT-less farm.
        if (r.indoor.source === "manual_input" && r.indoor.measurements.length > 0) {
          const fromApi: Record<string, number> = {};
          r.indoor.measurements.forEach(pt => { fromApi[pt.canonical_name] = pt.value; });
          setManualValues(prev => ({ ...fromApi, ...(prev ?? {}) }));
        }
      })
      .catch(err => {
        console.error("[env fetch]", err);
        setEnvData(null);
      });
    fetchJson<Revenue>(`/api/farms/${farmId}/revenue`)
      .then(r => setRevenue(r)).catch(console.error);
    fetchJson<CostBreakdown>(`/api/farms/${farmId}/costs`)
      .then(r => setCosts(r)).catch(console.error);
  }, [farmId]);

  useEffect(() => { refreshData(); }, [refreshData]);

  // ── Handlers ───────────────────────────────────────────────────────────────

  function handleManualSaved(saved: Record<string, number>) {
    setManualValues(prev => ({ ...(prev ?? {}), ...saved }));
    refreshData();
  }
  async function handleApply(rank: number, confirmed: boolean) {
    await fetch(`/api/farms/${farmId}/apply`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rank, confirmed }),
    });
  }

  // ── Derived ────────────────────────────────────────────────────────────────

  const heroRec    = recs[0] ?? null;
  const minorRecs  = recs.slice(1);
  const isNoIot    = meta !== null && !meta.iot_available;
  const alerts     = summary?.alerts ?? [];
  const alertCount = alerts.length;

  // ── Tab content ────────────────────────────────────────────────────────────

  function renderContent() {
    if (loading) return (
      <div className="loading-center">불러오는 중...</div>
    );

    switch (tab) {
      // ── AI 추천 ──────────────────────────────────────────────────────────
      case "recommendations": return (
        <div className="col-gap">
          {isNoIot && !envData?.indoor?.has_data && (
            <div className="warn-card">
              <WarnIcon />
              <div>
                <p className="warn-title">환경 데이터가 없습니다</p>
                <p className="warn-body">
                  AI 추천을 받으려면{" "}
                  <button className="inline-link" onClick={() => setTab("environment")}>환경 탭</button>
                  에서 현재 농장 상태를 입력해 주세요.
                </p>
              </div>
            </div>
          )}
          {heroRec && <HeroRecommendation farmId={farmId} recommendation={heroRec} onApply={handleApply} />}
          {minorRecs.map(rec => (
            <MinorRecommendation key={rec.rank} farmId={farmId} recommendation={rec} onApply={handleApply} />
          ))}
        </div>
      );

      // ── 환경 ─────────────────────────────────────────────────────────────
      case "environment": return (
        <div className="col-gap">
          <StationBanner
            stationId={meta?.asos_station_id}
            sido={meta?.sido}
            sigungu={meta?.sigungu}
          />
          <EnvTwoPanel
            envData={envData}
            farmId={farmId}
            manualValues={manualValues}
            onSaved={handleManualSaved}
          />
        </div>
      );

      // ── 수확예측 ─────────────────────────────────────────────────────────
      case "harvest": return (
        <div className="card">
          <h2 className="section-title">수확 예측</h2>
          <div className="kpi-grid">
            {[
              { label: "예상 수확일", value: "5월 21일", sub: "D-12" },
              { label: "예상 수확량", value: "0.58 kg/m²", sub: "신뢰도 71%" },
              { label: "누적 GDD",    value: "842 °C·d",   sub: "목표 1,200°C·d" },
            ].map(({ label, value, sub }) => (
              <div key={label} className="kpi-cell">
                <p className="kpi-label">{label}</p>
                <p className="kpi-value">{value}</p>
                <p className="kpi-sub">{sub}</p>
              </div>
            ))}
          </div>
        </div>
      );

      // ── 수익 ─────────────────────────────────────────────────────────────
      case "revenue": return (
        <div className="col-gap">
          <div className="card">
            <div className="row-gap8 mb16">
              <h2 className="section-title">수익 현황</h2>
              {meta?.crop && <span className="muted-sm">— {meta.crop}</span>}
            </div>
            {revenue ? (
              <div className="kpi-grid">
                {[
                  { label: "KAMIS 단가",  value: `${revenue.kamis_price_krw_kg.toLocaleString()}원/kg`, color: colors.inkPrimary },
                  { label: "예상 매출",   value: `${Math.round(revenue.predicted_revenue_krw / 10000).toLocaleString()}만원`, color: colors.chartwellBlue },
                  { label: "예상 비용",   value: `${Math.round(revenue.predicted_cost_krw / 10000).toLocaleString()}만원`, color: colors.warningAmber },
                  { label: "예상 순이익", value: `${Math.round(revenue.predicted_profit_krw / 10000).toLocaleString()}만원`, color: colors.successGreen },
                ].map(({ label, value, color }) => (
                  <div key={label} className="kpi-cell">
                    <p className="kpi-label">{label}</p>
                    <p className="kpi-value" style={{ color }}>{value}</p>
                  </div>
                ))}
              </div>
            ) : <p className="muted-sm">수익 데이터를 불러오는 중...</p>}
          </div>

          {/* 비용 간략 미리보기 */}
          {costs && (
            <div className="card">
              <div className="row-gap8 mb16">
                <h2 className="section-title">월 비용 요약</h2>
                <button className="inline-link" onClick={() => setTab("costs")}>상세 보기 →</button>
              </div>
              <div className="kpi-grid">
                <div className="kpi-cell">
                  <p className="kpi-label">월 총 비용</p>
                  <p className="kpi-value" style={{ color: colors.warningAmber }}>
                    {Math.round(costs.total_cost_krw / 10000).toLocaleString()}만원
                  </p>
                </div>
                <div className="kpi-cell">
                  <p className="kpi-label">m²당 비용</p>
                  <p className="kpi-value">{costs.cost_per_m2.toLocaleString()}원</p>
                </div>
                <div className="kpi-cell">
                  <p className="kpi-label">월 전기 사용량</p>
                  <p className="kpi-value">{costs.electricity_kwh_month.toLocaleString()}kWh</p>
                </div>
                <div className="kpi-cell">
                  <p className="kpi-label">월 용수 사용량</p>
                  <p className="kpi-value">{costs.water_m3_month.toLocaleString()}m³</p>
                </div>
              </div>
            </div>
          )}
        </div>
      );

      // ── 비용분석 ─────────────────────────────────────────────────────────
      case "costs": return (
        <div className="col-gap">

          {/* 실제값 입력 폼 — farm_005는 항상 표시, 나머지는 토글 */}
          {(isNoIot || showCostInput) ? (
            <CostInputForm
              farmId={farmId}
              initialValues={costs?.manual_input ?? null}
              onSaved={() => { setShowCostInput(false); refreshData(); }}
              onCancel={isNoIot ? undefined : () => setShowCostInput(false)}
            />
          ) : (
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                onClick={() => setShowCostInput(true)}
                style={{
                  background: costs?.has_manual_input ? colors.chartwellBlueBg : colors.surfaceMuted,
                  color: costs?.has_manual_input ? colors.chartwellBlue : colors.inkSecondary,
                  border: `1.5px solid ${costs?.has_manual_input ? colors.chartwellBlue : colors.stoneBorder}`,
                  borderRadius: radius.button,
                  padding: "8px 16px",
                  fontSize: "0.875rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {costs?.has_manual_input ? "✏️ 실제값 수정" : "✏️ 실제값 입력"}
              </button>
            </div>
          )}

          {costs ? (
            <>
              {/* 헤더 KPI */}
              <div className="card">
                <h2 className="section-title mb16">월 운영 비용 분석</h2>
                <div className="kpi-grid">
                  <div className="kpi-cell">
                    <p className="kpi-label">월 총 비용</p>
                    <p className="kpi-value" style={{ color: colors.dangerRed }}>
                      {Math.round(costs.total_cost_krw / 10000).toLocaleString()}만원
                    </p>
                  </div>
                  <div className="kpi-cell">
                    <p className="kpi-label">m²당 월 비용</p>
                    <p className="kpi-value">{costs.cost_per_m2.toLocaleString()}원/m²</p>
                  </div>
                  <div className="kpi-cell">
                    <p className="kpi-label">월 전기 사용</p>
                    <p className="kpi-value">{costs.electricity_kwh_month.toLocaleString()}kWh</p>
                    <p className="kpi-sub">탄소 {(costs.electricity_kwh_month * 0.459).toFixed(0)}kg CO₂</p>
                  </div>
                  <div className="kpi-cell">
                    <p className="kpi-label">월 용수 사용</p>
                    <p className="kpi-value">{costs.water_m3_month.toLocaleString()}m³</p>
                    <p className="kpi-sub">{(costs.water_m3_month * 1000).toLocaleString()}L</p>
                  </div>
                </div>
              </div>

              {/* 비용 항목별 바 차트 */}
              <div className="card">
                <h2 className="section-title mb16">항목별 비용 비율</h2>
                <div className="cost-bars">
                  {costs.items
                    .slice()
                    .sort((a, b) => b.amount_krw - a.amount_krw)
                    .map(item => (
                    <div key={item.category} className="cost-bar-row">
                      <div className="cost-bar-meta">
                        <span className="cost-icon">{COST_ICONS[item.category] ?? "•"}</span>
                        <span className="cost-label-ko">{item.label_ko}</span>
                        <span className="cost-unit-label">{item.unit_label}</span>
                      </div>
                      <div className="cost-bar-track">
                        <div
                          className="cost-bar-fill"
                          style={{
                            width: `${Math.round(item.pct_of_total * 100)}%`,
                            background: COST_BAR_COLOR[item.category] ?? colors.chartwellBlue,
                          }}
                        />
                      </div>
                      <div className="cost-bar-right">
                        <span className="cost-amount">
                          {Math.round(item.amount_krw / 10000).toLocaleString()}만원
                        </span>
                        <span className="cost-pct">
                          {Math.round(item.pct_of_total * 100)}%
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 절감 인사이트 */}
              <div className="card">
                <h2 className="section-title mb16">절감 인사이트</h2>
                <div className="col-gap8">
                  <CostInsightRow
                    icon="⚡"
                    title="전기 절감"
                    desc={`LED 보광 타이머 최적화로 일 ${(costs.electricity_kwh_month / 30 * 0.1).toFixed(0)}kWh 절약 가능 → 월 약 ${Math.round(costs.electricity_kwh_month / 30 * 0.1 * 30 * 105 / 10000)}만원`}
                    color={COST_BAR_COLOR.electricity}
                  />
                  <CostInsightRow
                    icon="💧"
                    title="용수 절감"
                    desc={`점적관개 + EC 정밀제어로 용수 15% 절약 → 월 약 ${Math.round(costs.water_m3_month * 0.15 * 700 / 10000)}만원`}
                    color={COST_BAR_COLOR.water}
                  />
                  <CostInsightRow
                    icon="🔥"
                    title="난방 절감"
                    desc={`보온커튼 야간 운영으로 난방 20% 절약 → 월 약 ${Math.round(costs.items.find(i => i.category === "heating")!.amount_krw * 0.2 / 10000)}만원`}
                    color={COST_BAR_COLOR.heating}
                  />
                </div>
              </div>
            </>
          ) : <p className="muted-sm">비용 데이터를 불러오는 중...</p>}
        </div>
      );

      // ── AI 상담 ──────────────────────────────────────────────────────────
      case "chat": return (
        <AiChat farmId={farmId} cropName={meta?.crop} farmName={meta?.name} />
      );

      default: return null;
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="app-shell">

      {/* ══ TOP BAR ════════════════════════════════════════════════════════ */}
      <header className="topbar">
        {/* 농장명 */}
        <div className="topbar-brand">
          <div className="topbar-name-row">
            <span className="topbar-name">{meta?.name ?? farmId}</span>
            {isNoIot && <span className="badge badge-warn">IoT 미구축</span>}
            <button
              className="gear-btn"
              onClick={() => setShowFarmSettings(s => !s)}
              title="농장 설정"
            >
              <GearIcon />
            </button>
          </div>
          {meta?.crop && <span className="topbar-crop">{meta.crop}</span>}
        </div>

        {/* Spacer (tablet·desktop에서 tab bar 표시) */}
        <nav className="topbar-tabs">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`topbar-tab ${tab === key ? "topbar-tab--active" : ""}`}
            >
              {label}
            </button>
          ))}
        </nav>

        {/* Pills */}
        <div className="pills-row">
          {alertCount > 0 && (
            <button
              onClick={() => setAlertPanelOpen(o => !o)}
              className={`pill pill-danger ${alertPanelOpen ? "pill--active" : ""}`}
            >
              <WarnIconSmall /> 알림 {alertCount}
            </button>
          )}
          {summary?.harvest_days_remaining != null && (
            <span className="pill pill-blue">수확 D-{summary.harvest_days_remaining}</span>
          )}
          {summary && (
            <span className="pill pill-green">
              {Math.round(summary.revenue_mtd_krw / 10000)}만원
            </span>
          )}
        </div>
      </header>

      {/* ══ ALERT PANEL ════════════════════════════════════════════════════ */}
      {alertPanelOpen && alerts.length > 0 && (
        <div className="alert-panel">
          <div className="alert-panel-header">
            <span className="alert-panel-title">현재 알림 {alertCount}건</span>
            <button className="close-btn" onClick={() => setAlertPanelOpen(false)}>닫기 ✕</button>
          </div>
          {alerts.map(alert => {
            const c = SEVERITY_COLORS[alert.severity as keyof typeof SEVERITY_COLORS] ?? SEVERITY_COLORS.info;
            return (
              <div key={alert.id} className="alert-item" style={{ background: c.bg, borderColor: c.border }}>
                <AlertIcon severity={alert.severity} color={c.text} />
                <div>
                  <div className="alert-item-meta">
                    <span style={{ color: c.text, fontSize: "0.65rem", fontWeight: 700, textTransform: "uppercase" }}>
                      {SEVERITY_LABEL[alert.severity as keyof typeof SEVERITY_LABEL]}
                    </span>
                    <span className="muted-xs">현재 {alert.value}{alert.unit} / 기준 {alert.threshold}{alert.unit}</span>
                  </div>
                  <p className="alert-msg">{alert.message_ko}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ══ BODY = SIDEBAR + MAIN ══════════════════════════════════════════ */}
      <div className="app-body">

        {/* ── LEFT SIDEBAR (desktop ≥1024px only) ── */}
        <aside className="sidebar">
          <div className="sidebar-farm">
            <div className="sidebar-farm-name-row">
              <span className="sidebar-farm-name">{meta?.name ?? farmId}</span>
              <button
                className="gear-btn"
                onClick={() => setShowFarmSettings(s => !s)}
                title="농장 설정"
              >
                <GearIcon />
              </button>
            </div>
            {meta?.crop && <div className="sidebar-crop">{meta.crop}</div>}
            {meta?.area_m2 && <div className="sidebar-area">{meta.area_m2.toLocaleString()}m²</div>}
          </div>
          <nav className="sidebar-nav">
            {TABS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`sidebar-item ${tab === key ? "sidebar-item--active" : ""}`}
              >
                <TabIcon name={key} active={tab === key} />
                <span>{label}</span>
              </button>
            ))}
          </nav>
          {summary && (
            <div className="sidebar-stats">
              {alertCount > 0 && (
                <button
                  onClick={() => setAlertPanelOpen(o => !o)}
                  className="sidebar-stat sidebar-stat--danger"
                >
                  <span>알림</span><span>{alertCount}건</span>
                </button>
              )}
              {summary.harvest_days_remaining != null && (
                <div className="sidebar-stat">
                  <span>수확</span><span>D-{summary.harvest_days_remaining}</span>
                </div>
              )}
              <div className="sidebar-stat sidebar-stat--green">
                <span>이번달 수익</span>
                <span>{Math.round(summary.revenue_mtd_krw / 10000)}만원</span>
              </div>
            </div>
          )}
        </aside>

        {/* ── MAIN CONTENT ── */}
        <main className="main-content">
          {/* 농장 설정 패널 (사이드바 버튼으로 토글) */}
          {showFarmSettings && (
            <div style={{ marginBottom: "16px" }}>
              <FarmSettings
                farmId={farmId}
                currentMeta={meta}
                onSaved={updated => { setMeta(prev => prev ? { ...prev, ...updated } : null); setShowFarmSettings(false); refreshData(); }}
                onCancel={() => setShowFarmSettings(false)}
              />
            </div>
          )}
          {renderContent()}
        </main>
      </div>

      {/* ══ BOTTOM NAV (mobile <640px only) ════════════════════════════════ */}
      <nav className="bottom-nav">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`bottom-nav-item ${tab === key ? "bottom-nav-item--active" : ""}`}
          >
            <TabIcon name={key} active={tab === key} />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      {/* ══ STYLES ═════════════════════════════════════════════════════════ */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        /* ── Shell ── */
        .app-shell {
          min-height: 100vh;
          background: ${colors.canvasFog};
          font-family: 'Inter', sans-serif;
          -webkit-font-smoothing: antialiased;
          display: flex; flex-direction: column;
        }

        /* ── Top bar ── */
        .topbar {
          height: 56px; background: ${colors.cloudWhite};
          border-bottom: 1px solid ${colors.stoneBorder};
          display: flex; align-items: center;
          padding: 0 16px; gap: 12px;
          position: sticky; top: 0; z-index: 50;
        }
        .topbar-brand { flex-shrink: 0; }
        .topbar-name-row { display: flex; align-items: center; gap: 8px; }
        .topbar-name  { font-weight: 800; font-size: 0.9375rem; color: ${colors.inkPrimary}; }
        .topbar-crop  { font-size: 0.7rem; color: ${colors.inkMuted}; margin-top: 1px; display: block; }

        /* topbar tabs — tablet only (640–1023px) */
        .topbar-tabs { display: none; flex: 1; overflow-x: auto; gap: 0; }
        .topbar-tabs::-webkit-scrollbar { display: none; }
        .topbar-tab {
          background: none; border: none;
          border-bottom: 2px solid transparent;
          color: ${colors.inkSecondary}; font-weight: 500;
          font-size: 0.875rem; padding: 14px 14px 12px;
          cursor: pointer; white-space: nowrap;
          transition: color 150ms;
        }
        .topbar-tab--active {
          border-bottom-color: ${colors.chartwellBlue};
          color: ${colors.chartwellBlue}; font-weight: 700;
        }

        /* pills */
        .pills-row { display: flex; gap: 6px; align-items: center; margin-left: auto; flex-shrink: 0; }
        .pill {
          border-radius: ${radius.badge}; padding: 4px 10px;
          font-size: 0.72rem; font-weight: 700; border: 1.5px solid transparent;
          white-space: nowrap;
        }
        .pill-danger { background: ${colors.dangerBg}; color: ${colors.dangerRed}; border-color: ${colors.dangerRed}; cursor: pointer; display: flex; align-items: center; gap: 4px; transition: background 150ms, color 150ms; }
        .pill-danger.pill--active { background: ${colors.dangerRed}; color: #fff; }
        .pill-blue   { background: ${colors.chartwellBlueBg}; color: ${colors.chartwellBlue}; }
        .pill-green  { background: ${colors.successBg}; color: ${colors.successGreen}; }

        /* ── Alert panel ── */
        .alert-panel {
          background: ${colors.cloudWhite};
          border-bottom: 1px solid ${colors.stoneBorder};
          padding: 12px 16px; display: flex; flex-direction: column; gap: 8px;
          position: sticky; top: 56px; z-index: 49;
          box-shadow: 0 4px 12px rgba(0,0,0,0.06);
        }
        .alert-panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
        .alert-panel-title  { font-size: 0.8125rem; font-weight: 700; color: ${colors.inkPrimary}; }
        .close-btn { background: none; border: none; cursor: pointer; color: ${colors.inkMuted}; font-size: 0.75rem; padding: 2px 6px; }
        .alert-item {
          border: 1px solid; border-radius: 8px; padding: 10px 14px;
          display: flex; align-items: flex-start; gap: 10px;
        }
        .alert-item-meta { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
        .alert-msg { font-size: 0.875rem; color: ${colors.inkPrimary}; line-height: 1.4; }

        /* ── Body layout ── */
        .app-body { display: flex; flex: 1; min-height: 0; }

        /* ── Sidebar (desktop ≥1024px) ── */
        .sidebar { display: none; }

        /* ── Main content ── */
        .main-content { flex: 1; padding: 16px; overflow-y: auto; padding-bottom: 80px; }

        /* ── Bottom nav (mobile <640px) ── */
        .bottom-nav {
          position: fixed; bottom: 0; left: 0; right: 0;
          background: ${colors.cloudWhite};
          border-top: 1px solid ${colors.stoneBorder};
          display: flex; z-index: 50;
        }
        .bottom-nav-item {
          flex: 1; background: none; border: none;
          padding: 10px 4px 8px;
          display: flex; flex-direction: column; align-items: center; gap: 3px;
          cursor: pointer; color: ${colors.inkMuted};
          font-size: 0.65rem; font-weight: 500; min-height: 52px;
          transition: color 150ms;
        }
        .bottom-nav-item--active { color: ${colors.chartwellBlue}; font-weight: 700; }

        /* ── Tablet: 640–1023px ── */
        @media (min-width: 640px) {
          .bottom-nav  { display: none !important; }
          .topbar-tabs { display: flex; }
          .main-content { padding-bottom: 16px; }
        }

        /* 톱니바퀴 버튼 (topbar·sidebar 공용) */
        .gear-btn {
          background: none; border: none;
          padding: 3px 4px; margin-left: 4px;
          cursor: pointer; border-radius: 6px;
          color: ${colors.inkMuted};
          display: inline-flex; align-items: center;
          transition: color 150ms, background 150ms;
          flex-shrink: 0;
        }
        .gear-btn:hover { color: ${colors.chartwellBlue}; background: ${colors.chartwellBlueBg}; }

        /* 사이드바 농장명 행 */
        .sidebar-farm-name-row {
          display: flex; align-items: center; gap: 2px;
        }

        /* ── Desktop: ≥1024px ── */
        @media (min-width: 1024px) {
          .topbar-brand { display: none; }
          .topbar-tabs { display: none; }

          .sidebar {
            display: flex; flex-direction: column;
            width: 220px; min-width: 220px;
            background: ${colors.cloudWhite};
            border-right: 1px solid ${colors.stoneBorder};
            position: sticky; top: 56px;
            height: calc(100vh - 56px);
            overflow-y: auto; flex-shrink: 0;
          }
          .sidebar-farm {
            padding: 20px 16px 12px;
            border-bottom: 1px solid ${colors.stoneBorder};
          }
          .sidebar-farm-name { font-weight: 800; font-size: 0.9375rem; color: ${colors.inkPrimary}; }
          .sidebar-crop { font-size: 0.8rem; color: ${colors.inkMuted}; margin-top: 2px; }
          .sidebar-area { font-size: 0.75rem; color: ${colors.inkMuted}; margin-top: 2px; }
          .sidebar-nav  { padding: 8px 0; flex: 1; }
          .sidebar-item {
            width: 100%; background: none; border: none;
            display: flex; align-items: center; gap: 10px;
            padding: 11px 16px; cursor: pointer;
            font-size: 0.9375rem; font-weight: 500;
            color: ${colors.inkSecondary}; text-align: left;
            border-radius: 0; transition: background 120ms, color 120ms;
          }
          .sidebar-item:hover { background: ${colors.canvasFog}; color: ${colors.inkPrimary}; }
          .sidebar-item--active {
            background: ${colors.chartwellBlueBg} !important;
            color: ${colors.chartwellBlue} !important; font-weight: 700;
            border-right: 3px solid ${colors.chartwellBlue};
          }
          .sidebar-stats {
            padding: 12px;
            border-top: 1px solid ${colors.stoneBorder};
            display: flex; flex-direction: column; gap: 6px;
          }
          .sidebar-stat {
            display: flex; justify-content: space-between; align-items: center;
            padding: 8px 10px; border-radius: 8px;
            background: ${colors.canvasFog};
            font-size: 0.8125rem; font-weight: 600; color: ${colors.inkSecondary};
            border: none; cursor: default; width: 100%;
          }
          .sidebar-stat--danger { background: ${colors.dangerBg}; color: ${colors.dangerRed}; cursor: pointer; }
          .sidebar-stat--green  { background: ${colors.successBg}; color: ${colors.successGreen}; }

          .main-content { padding: 24px 28px; max-width: 900px; padding-bottom: 24px; }
        }

        /* ── Reusable ── */
        .card {
          background: ${colors.cloudWhite}; border-radius: ${radius.card};
          box-shadow: ${shadow.card}; border: 1px solid ${colors.stoneBorder};
          padding: 24px;
        }
        .col-gap  { display: flex; flex-direction: column; gap: 12px; }
        .col-gap8 { display: flex; flex-direction: column; gap: 8px; }
        .row-gap8 { display: flex; align-items: baseline; gap: 8px; }
        .row-between { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .mb16 { margin-bottom: 16px; }
        .loading-center { text-align: center; padding: 48px 0; color: ${colors.inkMuted}; font-size: 1rem; }

        .section-title { font-size: 1rem; font-weight: 700; color: ${colors.inkPrimary}; }
        .kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
        .kpi-cell { padding: 14px 16px; background: ${colors.canvasFog}; border-radius: 8px; }
        .kpi-label { font-size: 0.8125rem; color: ${colors.inkSecondary}; margin-bottom: 4px; }
        .kpi-value { font-size: 1.25rem; font-weight: 800; color: ${colors.inkPrimary}; }
        .kpi-sub   { font-size: 0.7rem; color: ${colors.inkMuted}; margin-top: 2px; }

        .rank-label { font-size: 0.75rem; font-weight: 600; color: ${colors.inkMuted}; margin-right: 8px; }
        .body-md    { font-size: 1rem; font-weight: 600; color: ${colors.inkPrimary}; }
        .profit-num { font-size: 1rem; font-weight: 800; white-space: nowrap; }
        .muted-sm   { font-size: 0.8rem; color: ${colors.inkMuted}; }
        .muted-xs   { font-size: 0.7rem; color: ${colors.inkMuted}; }
        .inline-link {
          background: none; border: none; padding: 0;
          color: ${colors.chartwellBlue}; font-weight: 700;
          font-size: inherit; cursor: pointer; text-decoration: underline;
        }

        .badge { border-radius: ${radius.badge}; padding: 2px 7px; font-size: 0.65rem; font-weight: 700; }
        .badge-warn { background: ${colors.warningBg}; color: ${colors.warningAmber}; }

        /* ── Warning card ── */
        .warn-card {
          background: ${colors.warningBg}; border: 1.5px solid ${colors.warningAmber};
          border-radius: ${radius.card}; padding: 20px 24px;
          display: flex; align-items: flex-start; gap: 12px;
        }
        .warn-title { font-weight: 700; color: ${colors.inkPrimary}; font-size: 1rem; }
        .warn-body  { color: ${colors.inkSecondary}; font-size: 0.9rem; margin-top: 4px; line-height: 1.6; }

        /* ── Cost bars ── */
        .cost-bars { display: flex; flex-direction: column; gap: 14px; }
        .cost-bar-row {}
        .cost-bar-meta {
          display: flex; align-items: center; gap: 6px; margin-bottom: 6px;
        }
        .cost-icon       { font-size: 0.9rem; flex-shrink: 0; }
        .cost-label-ko   { font-size: 0.875rem; font-weight: 700; color: ${colors.inkPrimary}; }
        .cost-unit-label { font-size: 0.7rem; color: ${colors.inkMuted}; margin-left: auto; text-align: right; }
        .cost-bar-track  { height: 8px; background: ${colors.canvasFog}; border-radius: 4px; overflow: hidden; margin-bottom: 4px; }
        .cost-bar-fill   { height: 100%; border-radius: 4px; transition: width 400ms ease; }
        .cost-bar-right  { display: flex; justify-content: space-between; }
        .cost-amount     { font-size: 0.875rem; font-weight: 700; color: ${colors.inkPrimary}; }
        .cost-pct        { font-size: 0.75rem; color: ${colors.inkMuted}; }

        /* ── Cost insight ── */
        .cost-insight {
          display: flex; align-items: flex-start; gap: 12px;
          padding: 12px 14px; border-radius: 8px;
          background: ${colors.canvasFog};
        }
        .cost-insight-icon { font-size: 1.1rem; flex-shrink: 0; margin-top: 1px; }
        .cost-insight-title { font-size: 0.875rem; font-weight: 700; color: ${colors.inkPrimary}; margin-bottom: 2px; }
        .cost-insight-desc  { font-size: 0.8125rem; color: ${colors.inkSecondary}; line-height: 1.5; }

        /* ── Focus & a11y ── */
        button:focus-visible { outline: 3px solid ${colors.chartwellBlueBg}; outline-offset: 2px; }
        input:focus { outline: none; border-color: ${colors.chartwellBlue} !important; box-shadow: 0 0 0 3px ${colors.chartwellBlueBg}; }
        input[type=number]::-webkit-inner-spin-button,
        input[type=number]::-webkit-outer-spin-button { opacity: 1; }
        @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
      `}</style>
    </div>
  );
}

// ── 비용 바 색상 ──────────────────────────────────────────────────────────────

const COST_BAR_COLOR: Record<string, string> = {
  electricity: "#f59e0b",   // amber
  water:       "#3ba6f1",   // blue
  heating:     "#ef4444",   // red
  labor:       "#8b5cf6",   // purple
  nutrients:   "#16a34a",   // green
  pesticides:  "#6b7280",   // gray
};

// ── 절감 인사이트 행 ──────────────────────────────────────────────────────────

function CostInsightRow({ icon, title, desc, color }: {
  icon: string; title: string; desc: string; color: string;
}) {
  return (
    <div className="cost-insight" style={{ borderLeft: `3px solid ${color}` }}>
      <span className="cost-insight-icon">{icon}</span>
      <div>
        <p className="cost-insight-title">{title}</p>
        <p className="cost-insight-desc">{desc}</p>
      </div>
    </div>
  );
}

// ── Tab icons ─────────────────────────────────────────────────────────────────

function TabIcon({ name, active }: { name: Tab; active: boolean }) {
  const c = active ? colors.chartwellBlue : colors.inkMuted;
  switch (name) {
    case "recommendations":
      return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2">
        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
      </svg>;
    case "environment":
      return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2">
        <path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/>
      </svg>;
    case "harvest":
      return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
        <line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
      </svg>;
    case "revenue":
      return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2">
        <line x1="12" y1="1" x2="12" y2="23"/>
        <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
      </svg>;
    case "costs":
      return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
      </svg>;
    case "chat":
      return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2">
        <path d="M12 2a9 9 0 0 1 9 9c0 4-2.5 7-6 8.5V22l-3-2-3 2v-2.5C5.5 18 3 15 3 11a9 9 0 0 1 9-9z"/>
        <circle cx="9" cy="11" r="1" fill={c}/><circle cx="15" cy="11" r="1" fill={c}/>
      </svg>;
    default: return null;
  }
}

// ── Inline SVG helpers ────────────────────────────────────────────────────────

function WarnIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
    stroke={colors.warningAmber} strokeWidth="2.5" style={{ flexShrink: 0, marginTop: 2 }}>
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
    <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
  </svg>;
}
function WarnIconSmall() {
  return <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2.5">
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
    <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
  </svg>;
}
function AlertIcon({ severity, color }: { severity: string; color: string }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
    stroke={color} strokeWidth="2.5" style={{ flexShrink: 0, marginTop: 1 }}>
    {severity === "info"
      ? <><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></>
      : <><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></>}
  </svg>;
}
