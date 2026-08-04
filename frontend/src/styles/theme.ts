/**
 * Shared palette tokens. Values mirror the CSS custom properties declared in
 * src/index.css — change them there first, then echo the change here.
 *
 * The interface uses a single accent (blue). Status and tariff hues are the
 * only other colours, and they carry meaning rather than decoration.
 */
export const STATUS_COLORS = { normal:'#22c55e', warning:'#f59e0b', critical:'#ef4444', offline:'#6b7280', online:'#22c55e' };
export const TARIFF_COLORS = { base:'#2563eb', intermedia:'#f59e0b', punta:'#ef4444' };
export const ACCENT = '#2563eb';
export const ACCENT_QUIET = '#3b82f6';
export const CHART_GRID = '#1e2227';
export const TOOLTIP_STYLE = { background:'#171a1d', border:'1px solid #252a31', borderRadius:'6px', color:'#f5f7fa', fontSize:12, boxShadow:'0 4px 16px rgba(0,0,0,.4)' };
