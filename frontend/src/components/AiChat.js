import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState, useRef, useEffect, useCallback } from "react";
import { colors, radius, shadow } from "../design-system/tokens";
// ── 참조 데이터 레이블 ─────────────────────────────────────────────────────────
const DATA_LABELS = {
    alerts: "알림",
    environment: "환경",
    revenue: "수익",
    harvest: "수확예측",
    recommendations: "AI추천",
    meta: "농장정보",
};
// ── 초기 제안 칩 (채팅 시작 전) ────────────────────────────────────────────────
const INITIAL_SUGGESTIONS = [
    "현재 알림 확인해줘",
    "수확일이 언제야?",
    "수익 높이는 방법은?",
    "오늘 환경 상태 어때?",
    "재배 관리 팁 알려줘",
];
// ── 메시지 파싱 — **bold** 텍스트 처리 ─────────────────────────────────────────
function parseContent(text) {
    const parts = text.split(/(\*\*[^*]+\*\*)/g);
    return parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
            return _jsx("strong", { children: part.slice(2, -2) }, i);
        }
        // 줄바꿈 처리
        return part.split("\n").map((line, j, arr) => (_jsxs("span", { children: [line, j < arr.length - 1 && _jsx("br", {})] }, `${i}-${j}`)));
    });
}
// ── LoadingDots ────────────────────────────────────────────────────────────────
function LoadingDots() {
    return (_jsx("div", { style: { display: "flex", gap: "4px", alignItems: "center", padding: "4px 0" }, children: [0, 1, 2].map(i => (_jsx("span", { style: {
                width: "7px",
                height: "7px",
                borderRadius: "50%",
                background: colors.inkMuted,
                display: "inline-block",
                animation: `dot-bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
            } }, i))) }));
}
// ── AI 아바타 아이콘 ──────────────────────────────────────────────────────────
function AiAvatar() {
    return (_jsx("div", { style: {
            width: "32px",
            height: "32px",
            borderRadius: "50%",
            background: colors.chartwellBlueBg,
            border: `1.5px solid ${colors.chartwellBlue}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
        }, children: _jsxs("svg", { width: "17", height: "17", viewBox: "0 0 24 24", fill: "none", stroke: colors.chartwellBlue, strokeWidth: "2", strokeLinecap: "round", children: [_jsx("path", { d: "M12 2a9 9 0 0 1 9 9c0 4-2.5 7-6 8.5V22l-3-2-3 2v-2.5C5.5 18 3 15 3 11a9 9 0 0 1 9-9z" }), _jsx("circle", { cx: "9", cy: "11", r: "1", fill: colors.chartwellBlue }), _jsx("circle", { cx: "15", cy: "11", r: "1", fill: colors.chartwellBlue })] }) }));
}
// ── 메인 컴포넌트 ──────────────────────────────────────────────────────────────
export function AiChat({ farmId, cropName, farmName }) {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [started, setStarted] = useState(false);
    const listRef = useRef(null);
    const inputRef = useRef(null);
    const bottomRef = useRef(null);
    // 새 메시지 올 때 스크롤 아래로
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, loading]);
    // ── 메시지 전송 ────────────────────────────────────────────────────────────
    const sendMessage = useCallback(async (text) => {
        const trimmed = text.trim();
        if (!trimmed || loading)
            return;
        setStarted(true);
        setInput("");
        const userMsg = {
            role: "user",
            content: trimmed,
            timestamp: new Date().toISOString(),
        };
        setMessages(prev => [...prev, userMsg]);
        setLoading(true);
        try {
            const history = messages.slice(-10).map(m => ({
                role: m.role,
                content: m.content,
                timestamp: m.timestamp,
            }));
            const res = await fetch(`/api/farms/${farmId}/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: trimmed, history }),
            });
            if (!res.ok)
                throw new Error(`서버 오류 (${res.status})`);
            const data = await res.json();
            const aiMsg = {
                role: "assistant",
                content: data.reply,
                timestamp: new Date().toISOString(),
                suggestions: data.suggestions ?? [],
                referencedData: data.referenced_data ?? [],
            };
            setMessages(prev => [...prev, aiMsg]);
        }
        catch (err) {
            setMessages(prev => [...prev, {
                    role: "assistant",
                    content: "죄송합니다, 잠시 문제가 발생했습니다. 다시 시도해 주세요.",
                    timestamp: new Date().toISOString(),
                    isError: true,
                }]);
        }
        finally {
            setLoading(false);
            inputRef.current?.focus();
        }
    }, [farmId, loading, messages]);
    // ── 입력창 Enter 처리 ─────────────────────────────────────────────────────
    function handleKeyDown(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage(input);
        }
    }
    // ── 렌더 ──────────────────────────────────────────────────────────────────
    return (_jsxs("div", { style: {
            display: "flex",
            flexDirection: "column",
            height: "calc(100vh - 180px)", // 헤더 + 탭바 아래 전체
            minHeight: "400px",
            maxHeight: "820px",
        }, children: [_jsxs("div", { style: {
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "8px 12px",
                    background: colors.chartwellBlueBg,
                    borderRadius: `${radius.card} ${radius.card} 0 0`,
                    border: `1px solid ${colors.stoneBorder}`,
                    borderBottom: "none",
                    flexShrink: 0,
                }, children: [_jsxs("svg", { width: "13", height: "13", viewBox: "0 0 24 24", fill: "none", stroke: colors.chartwellBlue, strokeWidth: "2.5", children: [_jsx("circle", { cx: "12", cy: "12", r: "10" }), _jsx("line", { x1: "12", y1: "8", x2: "12", y2: "12" }), _jsx("line", { x1: "12", y1: "16", x2: "12.01", y2: "16" })] }), _jsxs("span", { style: { fontSize: "0.75rem", color: colors.chartwellBlue, fontWeight: 600 }, children: [farmName ?? farmId, " \uB18D\uC7A5 \uB370\uC774\uD130 \uAE30\uBC18 \u00B7 AI \uC5F0\uACB0 \uC900\uBE44 \uC911 (\uD604\uC7AC \uADDC\uCE59 \uAE30\uBC18 \uC751\uB2F5)"] })] }), _jsxs("div", { ref: listRef, style: {
                    flex: 1,
                    overflowY: "auto",
                    padding: "16px 12px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "16px",
                    background: colors.cloudWhite,
                    border: `1px solid ${colors.stoneBorder}`,
                    borderTop: "none",
                    borderBottom: "none",
                }, children: [!started && (_jsxs("div", { style: { display: "flex", flexDirection: "column", alignItems: "center", gap: "20px", paddingTop: "24px" }, children: [_jsxs("div", { style: { textAlign: "center" }, children: [_jsx("div", { style: {
                                            width: "56px", height: "56px",
                                            borderRadius: "50%",
                                            background: colors.chartwellBlueBg,
                                            border: `2px solid ${colors.chartwellBlue}`,
                                            display: "flex", alignItems: "center", justifyContent: "center",
                                            margin: "0 auto 12px",
                                        }, children: _jsxs("svg", { width: "28", height: "28", viewBox: "0 0 24 24", fill: "none", stroke: colors.chartwellBlue, strokeWidth: "1.8", strokeLinecap: "round", children: [_jsx("path", { d: "M12 2a9 9 0 0 1 9 9c0 4-2.5 7-6 8.5V22l-3-2-3 2v-2.5C5.5 18 3 15 3 11a9 9 0 0 1 9-9z" }), _jsx("circle", { cx: "9", cy: "11", r: "1", fill: colors.chartwellBlue }), _jsx("circle", { cx: "15", cy: "11", r: "1", fill: colors.chartwellBlue })] }) }), _jsx("p", { style: { fontWeight: 700, fontSize: "1rem", color: colors.inkPrimary, marginBottom: "4px" }, children: "\uB18D\uC7A5 AI \uC0C1\uB2F4\uC0AC" }), _jsxs("p", { style: { fontSize: "0.875rem", color: colors.inkSecondary, lineHeight: 1.6 }, children: [cropName ? `${cropName} 재배 ` : "", farmName ?? farmId, " \uB18D\uC7A5\uC5D0 \uB300\uD574", _jsx("br", {}), "\uBB34\uC5C7\uC774\uB4E0 \uBB3C\uC5B4\uBCF4\uC138\uC694"] })] }), _jsx("div", { style: {
                                    display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center", maxWidth: "420px",
                                }, children: INITIAL_SUGGESTIONS.map(s => (_jsx("button", { onClick: () => sendMessage(s), style: {
                                        background: colors.canvasFog,
                                        border: `1px solid ${colors.stoneBorder}`,
                                        borderRadius: radius.badge,
                                        padding: "8px 14px",
                                        fontSize: "0.875rem",
                                        color: colors.inkSecondary,
                                        cursor: "pointer",
                                        transition: "border-color 150ms, color 150ms, background 150ms",
                                        lineHeight: 1.3,
                                    }, onMouseEnter: e => {
                                        e.currentTarget.style.borderColor = colors.chartwellBlue;
                                        e.currentTarget.style.color = colors.chartwellBlue;
                                        e.currentTarget.style.background = colors.chartwellBlueBg;
                                    }, onMouseLeave: e => {
                                        e.currentTarget.style.borderColor = colors.stoneBorder;
                                        e.currentTarget.style.color = colors.inkSecondary;
                                        e.currentTarget.style.background = colors.canvasFog;
                                    }, children: s }, s))) })] })), messages.map((msg, idx) => (_jsxs("div", { style: {
                            display: "flex",
                            flexDirection: msg.role === "user" ? "row-reverse" : "row",
                            alignItems: "flex-end",
                            gap: "8px",
                        }, children: [msg.role === "assistant" && _jsx(AiAvatar, {}), _jsxs("div", { style: { maxWidth: "78%", display: "flex", flexDirection: "column", gap: "6px",
                                    alignItems: msg.role === "user" ? "flex-end" : "flex-start" }, children: [_jsx("div", { style: {
                                            background: msg.role === "user"
                                                ? colors.chartwellBlue
                                                : msg.isError ? colors.dangerBg : colors.canvasFog,
                                            color: msg.role === "user" ? "#fff"
                                                : msg.isError ? colors.dangerRed : colors.inkPrimary,
                                            border: msg.role === "user"
                                                ? "none"
                                                : `1px solid ${msg.isError ? colors.dangerRed : colors.stoneBorder}`,
                                            borderRadius: msg.role === "user"
                                                ? "18px 18px 4px 18px"
                                                : "18px 18px 18px 4px",
                                            padding: "12px 16px",
                                            fontSize: "0.9375rem",
                                            lineHeight: 1.65,
                                            boxShadow: msg.role === "assistant" ? shadow.card : "none",
                                            whiteSpace: "pre-wrap",
                                            wordBreak: "break-word",
                                        }, children: parseContent(msg.content) }), msg.role === "assistant" && (msg.referencedData?.length ?? 0) > 0 && (_jsx("div", { style: { display: "flex", gap: "4px", flexWrap: "wrap" }, children: msg.referencedData.map(key => (_jsx("span", { style: {
                                                fontSize: "0.65rem", fontWeight: 600,
                                                background: colors.chartwellBlueBg,
                                                color: colors.chartwellBlue,
                                                borderRadius: radius.badge,
                                                padding: "2px 7px",
                                                border: `1px solid ${colors.chartwellBlue}22`,
                                            }, children: DATA_LABELS[key] ?? key }, key))) })), msg.role === "assistant" && idx === messages.length - 1 &&
                                        !loading && (msg.suggestions?.length ?? 0) > 0 && (_jsx("div", { style: { display: "flex", gap: "6px", flexWrap: "wrap", marginTop: "2px" }, children: msg.suggestions.map(s => (_jsx("button", { onClick: () => sendMessage(s), style: {
                                                background: colors.cloudWhite,
                                                border: `1px solid ${colors.stoneBorder}`,
                                                borderRadius: radius.badge,
                                                padding: "6px 12px",
                                                fontSize: "0.8rem",
                                                color: colors.inkSecondary,
                                                cursor: "pointer",
                                                transition: "border-color 150ms, color 150ms",
                                            }, onMouseEnter: e => {
                                                e.currentTarget.style.borderColor = colors.chartwellBlue;
                                                e.currentTarget.style.color = colors.chartwellBlue;
                                            }, onMouseLeave: e => {
                                                e.currentTarget.style.borderColor = colors.stoneBorder;
                                                e.currentTarget.style.color = colors.inkSecondary;
                                            }, children: s }, s))) })), _jsx("span", { style: { fontSize: "0.65rem", color: colors.inkMuted }, children: new Date(msg.timestamp).toLocaleTimeString("ko-KR", {
                                            hour: "2-digit", minute: "2-digit",
                                        }) })] })] }, idx))), loading && (_jsxs("div", { style: { display: "flex", alignItems: "flex-end", gap: "8px" }, children: [_jsx(AiAvatar, {}), _jsx("div", { style: {
                                    background: colors.canvasFog,
                                    border: `1px solid ${colors.stoneBorder}`,
                                    borderRadius: "18px 18px 18px 4px",
                                    padding: "12px 16px",
                                    boxShadow: shadow.card,
                                }, children: _jsx(LoadingDots, {}) })] })), _jsx("div", { ref: bottomRef })] }), _jsxs("div", { style: {
                    display: "flex",
                    gap: "8px",
                    alignItems: "flex-end",
                    padding: "12px",
                    background: colors.cloudWhite,
                    border: `1px solid ${colors.stoneBorder}`,
                    borderTop: `1px solid ${colors.stoneBorder}`,
                    borderRadius: `0 0 ${radius.card} ${radius.card}`,
                    flexShrink: 0,
                    boxShadow: "0 -2px 8px rgba(0,0,0,0.04)",
                }, children: [_jsx("textarea", { ref: inputRef, value: input, onChange: e => setInput(e.target.value), onKeyDown: handleKeyDown, placeholder: "\uB18D\uC7A5 \uC6B4\uC601\uC5D0 \uB300\uD574 \uC9C8\uBB38\uD558\uC138\uC694... (Enter \uC804\uC1A1)", rows: 1, style: {
                            flex: 1,
                            resize: "none",
                            border: `1.5px solid ${colors.stoneBorder}`,
                            borderRadius: "12px",
                            padding: "10px 14px",
                            fontSize: "0.9375rem",
                            fontFamily: "'Inter', sans-serif",
                            lineHeight: 1.5,
                            color: colors.inkPrimary,
                            background: colors.canvasFog,
                            outline: "none",
                            maxHeight: "120px",
                            overflowY: "auto",
                            transition: "border-color 150ms, box-shadow 150ms",
                        }, onFocus: e => {
                            e.currentTarget.style.borderColor = colors.chartwellBlue;
                            e.currentTarget.style.boxShadow = `0 0 0 3px ${colors.chartwellBlueBg}`;
                        }, onBlur: e => {
                            e.currentTarget.style.borderColor = colors.stoneBorder;
                            e.currentTarget.style.boxShadow = "none";
                        }, onInput: e => {
                            // 자동 높이 조절
                            const el = e.currentTarget;
                            el.style.height = "auto";
                            el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
                        } }), _jsx("button", { onClick: () => sendMessage(input), disabled: !input.trim() || loading, style: {
                            width: "42px",
                            height: "42px",
                            borderRadius: "50%",
                            border: "none",
                            background: (!input.trim() || loading) ? colors.stoneBorder : colors.chartwellBlue,
                            color: "#fff",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            cursor: (!input.trim() || loading) ? "not-allowed" : "pointer",
                            transition: "background 150ms",
                            flexShrink: 0,
                        }, "aria-label": "\uC804\uC1A1", children: _jsxs("svg", { width: "18", height: "18", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", strokeLinecap: "round", children: [_jsx("line", { x1: "22", y1: "2", x2: "11", y2: "13" }), _jsx("polygon", { points: "22 2 15 22 11 13 2 9 22 2" })] }) })] }), _jsx("style", { children: `
        @keyframes dot-bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
          40%            { transform: translateY(-6px); opacity: 1; }
        }
      ` })] }));
}
