import { useState, useEffect } from "react";
import { colors, radius, shadow } from "../design-system/tokens";

// ── Types ─────────────────────────────────────────────────────────────────────

interface FarmMeta {
  farm_id: string;
  name: string;
  crop: string;
  area_m2: number;
  sido?: string | null;
  sigungu?: string | null;
  address_detail?: string | null;
  asos_station_id?: number | null;
}

interface FarmSettingsProps {
  farmId: string;
  currentMeta: FarmMeta | null;
  onSaved: (updated: FarmMeta) => void;
  onCancel: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FarmSettings({ farmId, currentMeta, onSaved, onCancel }: FarmSettingsProps) {
  const [name,          setName]          = useState(currentMeta?.name ?? "");
  const [crop,          setCrop]          = useState(currentMeta?.crop ?? "");
  const [areaM2,        setAreaM2]        = useState(String(currentMeta?.area_m2 ?? ""));
  const [sido,          setSido]          = useState(currentMeta?.sido ?? "");
  const [sigungu,       setSigungu]       = useState(currentMeta?.sigungu ?? "");
  const [addressDetail, setAddressDetail] = useState(currentMeta?.address_detail ?? "");
  const [sidoList,      setSidoList]      = useState<string[]>([]);
  const [sigunguList,   setSigunguList]   = useState<string[]>([]);
  const [saving,        setSaving]        = useState(false);
  const [success,       setSuccess]       = useState(false);
  const [stationId,     setStationId]     = useState<number | null>(currentMeta?.asos_station_id ?? null);

  // 시도 목록 로드
  useEffect(() => {
    fetch(`/api/farms/${farmId}/meta/regions`)
      .then(r => r.json())
      .then(d => setSidoList(d.sido_list ?? []))
      .catch(console.error);
  }, [farmId]);

  // 시도 변경 → 시군구 목록 로드
  useEffect(() => {
    if (!sido) { setSigunguList([]); return; }
    fetch(`/api/farms/${farmId}/meta/regions?sido=${encodeURIComponent(sido)}`)
      .then(r => r.json())
      .then(d => setSigunguList(d.sigungu_list ?? []))
      .catch(console.error);
    setSigungu(""); // 시도 바뀌면 시군구 초기화
  }, [sido, farmId]);

  async function handleSave() {
    if (!name.trim()) { alert("농장명을 입력해 주세요."); return; }
    const area = parseFloat(areaM2);
    if (isNaN(area) || area <= 0) { alert("면적을 올바르게 입력해 주세요."); return; }

    setSaving(true);
    try {
      const res = await fetch(`/api/farms/${farmId}/meta`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          crop: crop.trim() || undefined,
          area_m2: area,
          sido:  sido  || undefined,
          sigungu: sigungu || undefined,
          address_detail: addressDetail.trim() || undefined,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated: FarmMeta = await res.json();
      setStationId(updated.asos_station_id ?? null);
      setSuccess(true);
      setTimeout(() => { setSuccess(false); onSaved(updated); }, 900);
    } catch {
      alert("저장 중 오류가 발생했습니다.");
    } finally {
      setSaving(false);
    }
  }

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "9px 12px",
    border: `1.5px solid ${colors.stoneBorder}`,
    borderRadius: radius.input,
    fontSize: "0.9375rem",
    color: colors.inkPrimary,
    background: colors.canvasFog,
    outline: "none",
  };
  const selectStyle: React.CSSProperties = { ...inputStyle, cursor: "pointer" };
  const labelStyle: React.CSSProperties = {
    fontSize: "0.8rem", fontWeight: 600, color: colors.inkSecondary,
    marginBottom: "5px", display: "block",
  };

  return (
    <div style={{
      background: colors.cloudWhite,
      border: `1.5px solid ${colors.chartwellBlue}`,
      borderRadius: radius.card,
      padding: "22px",
      boxShadow: shadow.card,
    }}>
      {/* 헤더 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <h3 style={{ fontSize: "1rem", fontWeight: 800, color: colors.inkPrimary }}>
          🏡 농장 기본 정보
        </h3>
        <button onClick={onCancel} style={{
          background: "none", border: "none", cursor: "pointer",
          color: colors.inkMuted, fontSize: "0.8rem",
        }}>닫기 ✕</button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
        {/* 농장명 */}
        <div>
          <label style={labelStyle}>농장명</label>
          <input style={inputStyle} value={name}
            onChange={e => setName(e.target.value)} placeholder="예: 한솔 딸기 농장" />
        </div>

        {/* 작목 + 면적 */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
          <div>
            <label style={labelStyle}>작목</label>
            <select style={inputStyle} value={crop} onChange={e => setCrop(e.target.value)}>
              <option value="">작목 선택</option>
              <option value="딸기">딸기</option>
              <option value="방울토마토">방울토마토</option>
              <option value="완숙토마토">완숙토마토</option>
              <option value="참외">참외</option>
              <option value="오이">오이</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>재배 면적 (m²)</label>
            <input style={inputStyle} type="number" value={areaM2}
              onChange={e => setAreaM2(e.target.value)} placeholder="예: 1500" min={1} />
          </div>
        </div>

        {/* 구분선 */}
        <div style={{ borderTop: `1px solid ${colors.stoneBorder}`, paddingTop: "14px" }}>
          <p style={{ fontSize: "0.78rem", color: colors.inkMuted, marginBottom: "12px" }}>
            📍 주소를 입력하면 가장 가까운 기상청 관측소가 자동으로 연결됩니다.
          </p>

          {/* 시도 */}
          <div style={{ marginBottom: "12px" }}>
            <label style={labelStyle}>시도</label>
            <select style={selectStyle} value={sido} onChange={e => setSido(e.target.value)}>
              <option value="">— 선택 —</option>
              {sidoList.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          {/* 시군구 */}
          <div style={{ marginBottom: "12px" }}>
            <label style={labelStyle}>시군구</label>
            <select style={selectStyle} value={sigungu} onChange={e => setSigungu(e.target.value)}
              disabled={!sido || sigunguList.length === 0}>
              <option value="">— 선택 (선택 안 해도 시도 기준 연결) —</option>
              {sigunguList.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          {/* 상세주소 */}
          <div>
            <label style={labelStyle}>상세주소 (선택)</label>
            <input style={inputStyle} value={addressDetail}
              onChange={e => setAddressDetail(e.target.value)}
              placeholder="예: 군산시 성산면 방축리 123" />
          </div>
        </div>

        {/* 연결된 관측소 표시 */}
        {(stationId || currentMeta?.asos_station_id) && (
          <div style={{
            padding: "10px 14px",
            background: colors.chartwellBlueBg,
            borderRadius: "8px",
            display: "flex", alignItems: "center", gap: "8px",
          }}>
            <span style={{ fontSize: "0.85rem" }}>🌤️</span>
            <span style={{ fontSize: "0.8125rem", color: colors.chartwellBlue, fontWeight: 600 }}>
              기상청 ASOS 관측소 {stationId ?? currentMeta?.asos_station_id}번 연결됨
            </span>
          </div>
        )}

        {/* 버튼 */}
        <div style={{ display: "flex", gap: "10px", marginTop: "4px" }}>
          <button
            onClick={handleSave}
            disabled={saving || success}
            style={{
              flex: 1,
              background: success ? colors.successGreen : colors.chartwellBlue,
              color: "#fff", border: "none",
              borderRadius: radius.button,
              padding: "12px 20px",
              fontSize: "0.9375rem", fontWeight: 700,
              cursor: saving || success ? "default" : "pointer",
              transition: "background 200ms",
            }}
          >
            {success ? "✓ 저장 완료" : saving ? "저장 중..." : "저장"}
          </button>
          <button onClick={onCancel} style={{
            background: "none",
            color: colors.inkSecondary,
            border: `1.5px solid ${colors.stoneBorder}`,
            borderRadius: radius.button,
            padding: "12px 16px",
            fontSize: "0.9rem", fontWeight: 600,
            cursor: "pointer",
          }}>취소</button>
        </div>
      </div>
    </div>
  );
}
