// Seline Analytics design tokens
export const colors = {
    // backgrounds
    canvasFog: "#fafaf9",
    cloudWhite: "#ffffff",
    stoneBorder: "#e5e7eb",
    surfaceMuted: "#f3f4f6",
    // text
    inkPrimary: "#111827",
    inkSecondary: "#4b5563",
    inkMuted: "#9ca3af",
    // accent
    chartwellBlue: "#3ba6f1",
    chartwellBlueDark: "#1a8dd6",
    chartwellBlueBg: "#eff8ff",
    // status
    successGreen: "#16a34a",
    successBg: "#f0fdf4",
    warningAmber: "#d97706",
    warningBg: "#fffbeb",
    dangerRed: "#dc2626",
    dangerBg: "#fef2f2",
};
export const typography = {
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    // sizes — minimum 16px for 60+ year old users
    xs: "0.75rem", // 12px — labels only
    sm: "0.875rem", // 14px — secondary text
    base: "1rem", // 16px — minimum body
    lg: "1.125rem", // 18px
    xl: "1.25rem", // 20px
    "2xl": "1.5rem", // 24px
    "3xl": "1.875rem", // 30px — hero numbers
    "4xl": "2.25rem", // 36px
};
export const spacing = {
    1: "0.25rem",
    2: "0.5rem",
    3: "0.75rem",
    4: "1rem",
    5: "1.25rem",
    6: "1.5rem",
    8: "2rem",
    10: "2.5rem",
    12: "3rem",
    16: "4rem",
};
export const radius = {
    card: "10px",
    button: "9999px",
    badge: "9999px",
    input: "8px",
};
export const shadow = {
    card: "rgba(0,0,0,.05) 0 4px 16px 0",
    focus: `0 0 0 3px ${colors.chartwellBlueBg}`,
};
export const breakpoints = {
    mobile: 640, // < 640px
    tablet: 1024, // 640–1023px
    desktop: 1024, // ≥ 1024px
};
