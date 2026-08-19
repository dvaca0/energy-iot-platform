/**
 * Design tokens for the Campus Map.
 *
 * The first block mirrors `src/App.tsx`, which mirrors the CSS custom
 * properties in `src/index.css`. Same convention the live monitor and smart
 * plug modules follow: change `index.css` first, then App.tsx, then here.
 *
 * The second block is the map's own palette. It exists because a polygon needs
 * a fill, a stroke and a hover state derived from the same semantic colour, and
 * a GIS surface needs those at much lower alpha than a card border does.
 */

export const ACCENT = "#2563eb";
export const ACCENT_QUIET = "#3b82f6";
export const SURFACE = "#171a1d";
export const SURFACE_INNER = "#121417";
export const SURFACE_DEEP = "#0e1114";
export const BORDER = "#252a31";
export const BORDER_SOFT = "#1e2227";
export const TEXT = "#f5f7fa";
export const TEXT_SECONDARY = "#9aa4af";
export const TEXT_MUTED = "#7c8793";

export const GREEN = "#22c55e";
export const AMBER = "#f59e0b";
export const RED = "#ef4444";
export const GRAY = "#6b7280";
export const SLATE = "#475569";

/**
 * Tile layer. CARTO's dark basemap over OpenStreetMap data, chosen because the
 * standard OSM raster is a light, highly saturated sheet that would fight every
 * overlay on a dark dashboard and make an amber building indistinguishable from
 * a yellow road.
 *
 * Attribution is not optional and not decorative: OpenStreetMap's data is ODbL,
 * CARTO's rendering has its own notice, and Leaflet shows both in the corner
 * control. Do not remove either string.
 */
export const TILE_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
export const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

export const MAP_HEIGHT = 620;
