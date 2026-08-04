/**
 * Tokens visuales del módulo Smart Plugs.
 *
 * Replican exactamente la superficie de tarjetas, bordes y tipografía que ya
 * usan las páginas de Nodos y Despliegues en App.tsx, para que el módulo no
 * introduzca un segundo lenguaje visual. El acento único se importa de la
 * paleta compartida en src/styles/theme.ts.
 */
import type { CSSProperties } from "react";
import { ACCENT, ACCENT_QUIET } from "../../styles/theme";

export { ACCENT, ACCENT_QUIET };

export const GREEN = "#22c55e";
export const AMBER = "#f59e0b";
export const RED = "#ef4444";
export const GRAY = "#6b7280";

export const SURFACE = "#171a1d";
export const SURFACE_INNER = "#121417";
export const SURFACE_DEEP = "#0e1114";
export const BORDER = "#252a31";
export const BORDER_SOFT = "#1e2227";
export const BORDER_STRONG = "#2f353d";

export const TEXT = "#f5f7fa";
export const TEXT_SECONDARY = "#c3cbd4";
export const TEXT_BODY = "#9aa4af";
export const TEXT_MUTED = "#8b95a1";
export const TEXT_FAINT = "#7c8793";

export const cardStyle: CSSProperties = {
  background: SURFACE,
  border: `1px solid ${BORDER}`,
  borderRadius: 12,
  padding: "18px 20px",
  boxShadow: "0 1px 2px rgba(0, 0, 0, 0.24)",
  position: "relative",
  overflow: "hidden",
};

export const innerPanelStyle: CSSProperties = {
  background: SURFACE_INNER,
  border: `1px solid ${BORDER_SOFT}`,
  borderRadius: 8,
  padding: "10px 12px",
};

export const fieldLabelStyle: CSSProperties = {
  fontSize: 10,
  color: TEXT_FAINT,
  textTransform: "uppercase",
  letterSpacing: 0.6,
  fontWeight: 600,
};

export const fieldValueStyle: CSSProperties = {
  fontSize: 13,
  color: TEXT,
  fontWeight: 600,
  marginTop: 4,
  wordBreak: "break-word",
};

export const inputStyle: CSSProperties = {
  background: SURFACE_INNER,
  border: `1px solid ${BORDER}`,
  color: TEXT,
  borderRadius: 6,
  padding: "9px 11px",
  fontSize: 13,
  width: "100%",
};

export const primaryButtonStyle: CSSProperties = {
  background: ACCENT,
  border: `1px solid ${ACCENT}`,
  color: "#fff",
  borderRadius: 6,
  padding: "9px 16px",
  fontWeight: 600,
  fontSize: 13,
  cursor: "pointer",
};

export const ghostButtonStyle: CSSProperties = {
  background: SURFACE_INNER,
  border: `1px solid ${BORDER}`,
  color: TEXT_SECONDARY,
  borderRadius: 6,
  padding: "9px 16px",
  fontWeight: 500,
  fontSize: 13,
  cursor: "pointer",
};

/** Formateadores compartidos, en la misma convención es-MX del resto de la app. */
export const fmtNumber = (value: number | null | undefined, digits: number): string =>
  Number(value || 0).toLocaleString("es-MX", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

export const fmtDateTime = (value: string | null | undefined): string => {
  if (!value) return "Sin registro";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("es-MX");
};

export const fmtOrDash = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
};

/** La calidad de señal WiFi se lee mejor con color que con el número crudo. */
export const rssiColor = (rssi: number | null | undefined): string => {
  if (rssi === null || rssi === undefined) return GRAY;
  if (rssi >= -60) return GREEN;
  if (rssi >= -75) return AMBER;
  return RED;
};
