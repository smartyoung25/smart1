import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState, useEffect } from "react";
import { colors, radius, shadow } from "../design-system/tokens";
// ── Component ─────────────────────────────────────────────────────────────────
export function FarmSettings({ farmId, currentMeta, onSaved, onCancel }) {
    const [name, setName] = useState(currentMeta?.name ?? "");
    const [crop, setCrop] = useState(currentMeta?.crop ?? "");
    const [areaM2, setAreaM2] = useState(String(currentMeta?.area_m2 ?? ""));
    const [sido, setSido] = useState(currentMeta?.sido ?? "");
    const [sigungu, setSigungu] = useState(currentMeta?.sigungu ?? "");
    const [addressDetail, setAddressDetail] = useState(currentMeta?.address_detail ?? "");
    const [sidoList, setSidoList] = useState([]);
    const [sigunguList, setSigunguList] = useState([]);
    const [saving, setSaving] = useState(false);
    const [success, setSuccess] = useState(false);
    const [stationId, setStationId] = useState(currentMeta?.asos_station_id ?? null);
    // 시도 목록 로드
    useEffect(() => {
        fetch(`/api/farms/${farmId}/meta/regions`)
            .then(r => r.json())
            .then(d => setSidoList(d.sido_list ?? []))
            .catch(console.error);
    }, [farmId]);
    // 시도 변경 → 시군구 목록 로드
    useEffect(() => {
        if (!sido) {
            setSigunguList([]);
            return;
        }
        fetch(`/api/farms/${farmId}/meta/regions?sido=${encodeURIComponent(sido)}`)
            .then(r => r.json())
            .then(d => setSigunguList(d.sigungu_list ?? []))
            .catch(console.error);
        setSigungu(""); // 시도 바뀌면 시군구 초기화
    }, [sido, farmId]);
    async function handleSave() {
        if (!name.trim()) {
            alert("농장명을 입력해 주세요.");
            return;
        }
        const area = parseFloat(areaM2);
        if (isNaN(area) || area <= 0) {
            alert("면적을 올바르게 입력해 주세요.");
            return;
        }
        setSaving(true);
        try {
            const res = await fetch(`/api/farms/${farmId}/meta`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: name.trim(),
                    crop: crop.trim() || undefined,
                    area_m2: area,
                    sido: sido || undefined,
                    sigungu: sigungu || undefined,
                    address_detail: addressDetail.trim() || undefined,
                }),
            });
            if (!res.ok)
                throw new Error(await res.text());
            const updated = await res.json();
            setStationId(updated.asos_station_id ?? null);
            setSuccess(true);
            setTimeout(() => { setSuccess(false); onSaved(updated); }, 900);
        }
        catch {
            alert("저장 중 오류가 발생했습니다.");
        }
        finally {
            setSaving(false);
        }
    }
    const inputStyle = {
        width: "100%",
        padding: "9px 12px",
        border: `1.5px solid ${colors.stoneBorder}`,
        borderRadius: radius.input,
        fontSize: "0.9375rem",
        color: colors.inkPrimary,
        background: colors.canvasFog,
        outline: "none",
    };
    const selectStyle = { ...inputStyle, cursor: "pointer" };
    const labelStyle = {
        fontSize: "0.8rem", fontWeight: 600, color: colors.inkSecondary,
        marginBottom: "5px", display: "block",
    };
    return (_jsxs("div", { style: {
            background: colors.cloudWhite,
            border: `1.5px solid ${colors.chartwellBlue}`,
            borderRadius: radius.card,
            padding: "22px",
            boxShadow: shadow.card,
        }, children: [_jsxs("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }, children: [_jsx("h3", { style: { fontSize: "1rem", fontWeight: 800, color: colors.inkPrimary }, children: "\uD83C\uDFE1 \uB18D\uC7A5 \uAE30\uBCF8 \uC815\uBCF4" }), _jsx("button", { onClick: onCancel, style: {
                            background: "none", border: "none", cursor: "pointer",
                            color: colors.inkMuted, fontSize: "0.8rem",
                        }, children: "\uB2EB\uAE30 \u2715" })] }), _jsxs("div", { style: { display: "flex", flexDirection: "column", gap: "14px" }, children: [_jsxs("div", { children: [_jsx("label", { style: labelStyle, children: "\uB18D\uC7A5\uBA85" }), _jsx("input", { style: inputStyle, value: name, onChange: e => setName(e.target.value), placeholder: "\uC608: \uD55C\uC194 \uB538\uAE30 \uB18D\uC7A5" })] }), _jsxs("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }, children: [_jsxs("div", { children: [_jsx("label", { style: labelStyle, children: "\uC791\uBAA9" }), _jsxs("select", { style: inputStyle, value: crop, onChange: e => setCrop(e.target.value), children: [_jsx("option", { value: "", children: "\uC791\uBAA9 \uC120\uD0DD" }), _jsx("option", { value: "\uB538\uAE30", children: "\uB538\uAE30" }), _jsx("option", { value: "\uBC29\uC6B8\uD1A0\uB9C8\uD1A0", children: "\uBC29\uC6B8\uD1A0\uB9C8\uD1A0" }), _jsx("option", { value: "\uC644\uC219\uD1A0\uB9C8\uD1A0", children: "\uC644\uC219\uD1A0\uB9C8\uD1A0" }), _jsx("option", { value: "\uCC38\uC678", children: "\uCC38\uC678" }), _jsx("option", { value: "\uC624\uC774", children: "\uC624\uC774" })] })] }), _jsxs("div", { children: [_jsx("label", { style: labelStyle, children: "\uC7AC\uBC30 \uBA74\uC801 (m\u00B2)" }), _jsx("input", { style: inputStyle, type: "number", value: areaM2, onChange: e => setAreaM2(e.target.value), placeholder: "\uC608: 1500", min: 1 })] })] }), _jsxs("div", { style: { borderTop: `1px solid ${colors.stoneBorder}`, paddingTop: "14px" }, children: [_jsx("p", { style: { fontSize: "0.78rem", color: colors.inkMuted, marginBottom: "12px" }, children: "\uD83D\uDCCD \uC8FC\uC18C\uB97C \uC785\uB825\uD558\uBA74 \uAC00\uC7A5 \uAC00\uAE4C\uC6B4 \uAE30\uC0C1\uCCAD \uAD00\uCE21\uC18C\uAC00 \uC790\uB3D9\uC73C\uB85C \uC5F0\uACB0\uB429\uB2C8\uB2E4." }), _jsxs("div", { style: { marginBottom: "12px" }, children: [_jsx("label", { style: labelStyle, children: "\uC2DC\uB3C4" }), _jsxs("select", { style: selectStyle, value: sido, onChange: e => setSido(e.target.value), children: [_jsx("option", { value: "", children: "\u2014 \uC120\uD0DD \u2014" }), sidoList.map(s => _jsx("option", { value: s, children: s }, s))] })] }), _jsxs("div", { style: { marginBottom: "12px" }, children: [_jsx("label", { style: labelStyle, children: "\uC2DC\uAD70\uAD6C" }), _jsxs("select", { style: selectStyle, value: sigungu, onChange: e => setSigungu(e.target.value), disabled: !sido || sigunguList.length === 0, children: [_jsx("option", { value: "", children: "\u2014 \uC120\uD0DD (\uC120\uD0DD \uC548 \uD574\uB3C4 \uC2DC\uB3C4 \uAE30\uC900 \uC5F0\uACB0) \u2014" }), sigunguList.map(s => _jsx("option", { value: s, children: s }, s))] })] }), _jsxs("div", { children: [_jsx("label", { style: labelStyle, children: "\uC0C1\uC138\uC8FC\uC18C (\uC120\uD0DD)" }), _jsx("input", { style: inputStyle, value: addressDetail, onChange: e => setAddressDetail(e.target.value), placeholder: "\uC608: \uAD70\uC0B0\uC2DC \uC131\uC0B0\uBA74 \uBC29\uCD95\uB9AC 123" })] })] }), (stationId || currentMeta?.asos_station_id) && (_jsxs("div", { style: {
                            padding: "10px 14px",
                            background: colors.chartwellBlueBg,
                            borderRadius: "8px",
                            display: "flex", alignItems: "center", gap: "8px",
                        }, children: [_jsx("span", { style: { fontSize: "0.85rem" }, children: "\uD83C\uDF24\uFE0F" }), _jsxs("span", { style: { fontSize: "0.8125rem", color: colors.chartwellBlue, fontWeight: 600 }, children: ["\uAE30\uC0C1\uCCAD ASOS \uAD00\uCE21\uC18C ", stationId ?? currentMeta?.asos_station_id, "\uBC88 \uC5F0\uACB0\uB428"] })] })), _jsxs("div", { style: { display: "flex", gap: "10px", marginTop: "4px" }, children: [_jsx("button", { onClick: handleSave, disabled: saving || success, style: {
                                    flex: 1,
                                    background: success ? colors.successGreen : colors.chartwellBlue,
                                    color: "#fff", border: "none",
                                    borderRadius: radius.button,
                                    padding: "12px 20px",
                                    fontSize: "0.9375rem", fontWeight: 700,
                                    cursor: saving || success ? "default" : "pointer",
                                    transition: "background 200ms",
                                }, children: success ? "✓ 저장 완료" : saving ? "저장 중..." : "저장" }), _jsx("button", { onClick: onCancel, style: {
                                    background: "none",
                                    color: colors.inkSecondary,
                                    border: `1.5px solid ${colors.stoneBorder}`,
                                    borderRadius: radius.button,
                                    padding: "12px 16px",
                                    fontSize: "0.9rem", fontWeight: 600,
                                    cursor: "pointer",
                                }, children: "\uCDE8\uC18C" })] })] })] }));
}
