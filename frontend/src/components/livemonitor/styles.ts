/**
 * Design tokens for the live technical view.
 *
 * The first block mirrors the tokens in `src/App.tsx`, which in turn mirror the
 * CSS custom properties in `src/index.css`. This page is a separate module, so
 * it restates them rather than importing from a 2.3k-line file — change
 * `index.css` first, then App.tsx, then here.
 */

export const ACCENT = "#2563eb";
export const ACCENT_QUIET = "#3b82f6";
export const SURFACE = "#171a1d";
export const SURFACE_INNER = "#121417";
export const SURFACE_SUNK = "#0e1114";
export const BORDER = "#252a31";
export const BORDER_SOFT = "#1e2227";
export const TEXT = "#f5f7fa";
export const TEXT_SECONDARY = "#9aa4af";
export const TEXT_MUTED = "#7c8793";
export const CARD_SHADOW = "0 1px 2px rgba(0,0,0,.24)";
export const CHART_GRID = "#1e2227";

export const OK = "#22c55e";
export const WARN = "#f59e0b";
export const CRIT = "#ef4444";
export const IDLE = "#6b7280";

/**
 * Phase colours.
 *
 * A categorical palette, in the same sense as `TARIFF_COLORS` — the hue names a
 * phase, it never reports a condition. Green, amber and red are deliberately
 * absent: on this page they mean OK / warning / critical, and a phase C drawn
 * in red would read as an alarm on every chart it appears in.
 */
export const PHASE_COLORS: Record<string, string> = {
  A: "#3b82f6",
  B: "#22d3ee",
  C: "#a78bfa",
};

/** Totals and averages. Neutral, so a phase always outranks it visually. */
export const TOTAL_COLOR = "#cbd5e1";

/**
 * Per-node hues, for comparing nodes on one axis. Assigned by position in the
 * selection, which is stable because the selector keeps node order.
 */
export const NODE_COLORS = ["#3b82f6", "#f59e0b", "#22d3ee", "#a78bfa", "#f472b6"];

/**
 * Per-node stroke patterns. When several nodes are charted per phase, hue
 * carries the phase and the dash carries the node — so a line is never
 * ambiguous, and the legend can always be read as NODE · PHASE.
 */
export const NODE_DASH = ["", "5 3", "2 3", "8 3 2 3", "1 3"];

export const cardStyle: React.CSSProperties = {
  background: SURFACE,
  border: `1px solid ${BORDER}`,
  borderRadius: 12,
  padding: "18px 20px",
  boxShadow: CARD_SHADOW,
};

export const innerTileStyle: React.CSSProperties = {
  background: SURFACE_INNER,
  border: `1px solid ${BORDER_SOFT}`,
  borderRadius: 8,
  padding: "9px 11px",
};

export const tooltipStyle: React.CSSProperties = {
  background: SURFACE,
  border: `1px solid ${BORDER}`,
  borderRadius: 6,
  color: TEXT,
  fontSize: 12,
  boxShadow: "0 4px 16px rgba(0,0,0,.45)",
  padding: "9px 11px",
};

export const buttonStyle = (active: boolean): React.CSSProperties => ({
  background: active ? `${ACCENT}1f` : SURFACE_INNER,
  color: active ? ACCENT_QUIET : TEXT_SECONDARY,
  border: `1px solid ${active ? `${ACCENT}55` : BORDER}`,
  borderRadius: 6,
  padding: "5px 11px",
  fontSize: 11.5,
  fontWeight: 500,
  cursor: "pointer",
  letterSpacing: 0.2,
  whiteSpace: "nowrap",
});

export const labelStyle: React.CSSProperties = {
  fontSize: 10,
  color: TEXT_MUTED,
  textTransform: "uppercase",
  letterSpacing: 0.7,
};
