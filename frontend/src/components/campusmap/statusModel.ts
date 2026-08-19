/**
 * What a polygon looks like, and what the tooltip says about it.
 *
 * Pure functions only — no React, no Leaflet, no fetching. Everything the map
 * decides visually is decided here, so the rules can be read in one place and
 * tested without a browser (see `tests/render-campus-map.tsx`).
 *
 * Two ideas the rest of the module depends on:
 *
 * **Status and magnitude are different questions.** A building drawing 400 kW
 * is not in a worse state than one drawing 4 kW; it is a bigger building. So
 * STATUS mode uses the semantic palette (green/amber/red/gray) and the
 * magnitude modes use a single-hue graduated ramp that carries no judgement at
 * all. Colouring high consumption red would teach an operator that red means
 * "busy", and then a real fault in red would be ignored.
 *
 * **Freshness is stated, never assumed.** `active_stale` is its own state
 * rather than being folded into healthy or historical, and every panel that
 * shows a number also shows how old it is.
 */

import { ACCENT, ACCENT_QUIET, AMBER, GRAY, GREEN, RED, SLATE } from "./styles";
import type { MapBuilding, MapMode, MapStatus } from "./types";

export interface StatusMeta {
  label: string;
  short: string;
  color: string;
  /** Fill alpha. Unmonitored footprints sit far back; live ones come forward. */
  fillOpacity: number;
  weight: number;
  description: string;
}

export const STATUS_META: Record<MapStatus, StatusMeta> = {
  unregistered: {
    // One term for this state everywhere — chip, legend and tooltip. "Sin
    // monitoreo" answers the question a reader actually has (does Energy IQ
    // measure this?); the earlier "Sin registrar" invited it to be read as a
    // problem with the building rather than the absence of an association.
    label: "Sin monitoreo",
    short: "Sin monitoreo",
    color: SLATE,
    fillOpacity: 0.18,
    weight: 0.6,
    description: "El edificio existe en OpenStreetMap pero no está registrado en Energy IQ.",
  },
  registered: {
    label: "Registrado sin despliegue",
    short: "Sin despliegue",
    color: GRAY,
    fillOpacity: 0.3,
    weight: 1,
    description: "Energy IQ conoce el edificio, pero nunca ha tenido un despliegue ni lecturas.",
  },
  historical: {
    label: "Datos históricos",
    short: "Histórico",
    color: ACCENT,
    fillOpacity: 0.28,
    weight: 1.2,
    description: "Tiene mediciones pasadas en Energy IQ, sin monitoreo activo ahora.",
  },
  active_stale: {
    label: "Despliegue activo sin datos recientes",
    short: "Activo sin datos",
    color: AMBER,
    fillOpacity: 0.22,
    weight: 1.6,
    description:
      "Hay un despliegue activo, pero la última lectura quedó fuera de la ventana de telemetría.",
  },
  active_healthy: {
    label: "Monitoreo activo",
    short: "Monitoreo activo",
    color: GREEN,
    fillOpacity: 0.45,
    weight: 1.8,
    description: "Despliegue activo con lecturas recientes y sin alertas abiertas.",
  },
  active_warning: {
    label: "Advertencia",
    short: "Advertencia",
    color: AMBER,
    fillOpacity: 0.5,
    weight: 2,
    description: "Despliegue activo con una alerta abierta de nivel WARNING o ERROR.",
  },
  active_critical: {
    label: "Crítico",
    short: "Crítico",
    color: RED,
    fillOpacity: 0.55,
    weight: 2.2,
    description: "Despliegue activo con una alerta abierta de nivel CRITICAL o EMERGENCY.",
  },
};

/**
 * Most urgent first, ending with the footprints nobody monitors.
 *
 * One list, two uses: the legend reads top to bottom in this order, and a
 * footprint shared by several Energy IQ buildings takes the first of their
 * states — so the panel headline and the polygon colour can never disagree
 * about which record speaks for the building. The backend applies the same
 * ordering in `campus_map_state.SEVERITY_ORDER`.
 */
export const URGENCY_ORDER: MapStatus[] = [
  "active_critical",
  "active_warning",
  "active_stale",
  "active_healthy",
  "historical",
  "registered",
  "unregistered",
];

export const LEGEND_ORDER = URGENCY_ORDER;

export const MODE_META: Record<MapMode, { label: string; unit: string; hint: string }> = {
  status: {
    label: "Estado",
    unit: "",
    hint: "Salud de la cadena de medición: despliegue, frescura de datos y alertas abiertas.",
  },
  power: {
    label: "Potencia",
    unit: "kW",
    hint: "Potencia activa instantánea de la última lectura. Magnitud, no diagnóstico.",
  },
  energy: {
    label: "Energía hoy",
    unit: "kWh",
    hint: "Energía acumulada desde la medianoche local. Magnitud, no diagnóstico.",
  },
  cost: {
    label: "Costo hoy",
    unit: "MXN",
    hint: "Costo acumulado hoy, cobrado por hora a su propia tarifa. Magnitud, no diagnóstico.",
  },
  power_factor: {
    label: "Factor de potencia",
    unit: "",
    hint: "Factor de potencia de la última lectura. Escala graduada, sin umbral implícito.",
  },
};

/**
 * The quantity a magnitude mode reads off a building, or `null` when the
 * building cannot answer.
 *
 * Null is returned generously and on purpose. A building with no active
 * deployment has no current power; a stale one has a number but not a *current*
 * one. Both fall back to the STATUS colour rather than being drawn on the ramp,
 * because placing a twelve-day-old reading on a live scale is the exact
 * misrepresentation this page exists to avoid.
 */
export function modeValue(building: MapBuilding, mode: MapMode): number | null {
  switch (mode) {
    case "power":
      return building.telemetry.is_live ? (building.latest_reading?.power_kw ?? null) : null;
    case "power_factor":
      return building.telemetry.is_live ? (building.latest_reading?.power_factor ?? null) : null;
    case "energy":
      return building.energy_today_kwh > 0 ? building.energy_today_kwh : null;
    case "cost":
      return building.cost_today_mxn > 0 ? building.cost_today_mxn : null;
    default:
      return null;
  }
}

export interface Ramp {
  min: number;
  max: number;
  stops: string[];
}

/** A restrained blue ramp: one hue, five steps, no red end to misread. */
const RAMP_STOPS = ["#1e3a5f", "#1d4e89", "#1d63b4", "#2f83d6", "#5ba7f0"];

export function buildRamp(values: number[]): Ramp | null {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return null;
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  return { min, max, stops: RAMP_STOPS };
}

export function rampColor(value: number | null, ramp: Ramp | null): string | null {
  if (value === null || ramp === null) return null;
  // A single monitored building has min === max; put it at the top of the ramp
  // rather than dividing by zero and rendering it as the darkest step.
  const span = ramp.max - ramp.min;
  const t = span <= 0 ? 1 : (value - ramp.min) / span;
  const index = Math.min(ramp.stops.length - 1, Math.max(0, Math.round(t * (ramp.stops.length - 1))));
  return ramp.stops[index];
}

export interface PolygonStyle {
  color: string;
  weight: number;
  fillColor: string;
  fillOpacity: number;
  opacity: number;
  dashArray?: string;
  /**
   * Stops a click on this footprint from also reaching the map.
   *
   * Leaflet registers the map itself under the map container in `_targets`,
   * and `_findEventTargets` walks the DOM from the clicked `<path>` all the way
   * up through that container — so a click on a polygon resolves to
   * `[polygon, map]` and `_fireDOMEvent` fires BOTH. `Path` bubbles mouse
   * events by default. With the map's own click handler clearing the
   * selection, every building click set the selection and then cleared it in
   * the same dispatch, and the panel never left its placeholder.
   *
   * `_fireDOMEvent` returns early when a target has this false and the event is
   * one of `_mouseEvents` (click included), which is exactly the escape we
   * want: the footprint handles its own click, the map never sees it, and
   * clicking bare map still clears.
   */
  bubblingMouseEvents: false;
}

/**
 * The Leaflet path style for one footprint.
 *
 * Selection is drawn with the Energy IQ accent regardless of state, so a
 * selected critical building keeps its red fill and gains a blue outline. The
 * two carry different information and must not overwrite each other.
 */
export function polygonStyle(options: {
  status: MapStatus;
  mode: MapMode;
  value: number | null;
  ramp: Ramp | null;
  selected: boolean;
  hovered: boolean;
}): PolygonStyle {
  const { status, mode, value, ramp, selected, hovered } = options;
  const meta = STATUS_META[status];
  const graduated = mode !== "status" ? rampColor(value, ramp) : null;

  const fillColor = graduated ?? meta.color;
  const fillOpacity = graduated
    ? 0.62
    : meta.fillOpacity + (hovered ? 0.12 : 0) + (selected ? 0.08 : 0);

  return {
    bubblingMouseEvents: false,
    color: selected ? ACCENT_QUIET : hovered ? "#8fa3b8" : meta.color,
    weight: selected ? 3 : hovered ? Math.max(meta.weight, 1.8) : meta.weight,
    opacity: status === "unregistered" && !selected && !hovered ? 0.5 : 0.95,
    fillColor,
    fillOpacity: Math.min(fillOpacity, 0.75),
    // A footprint on a magnitude scale that has no value is a real absence, not
    // a zero: dashed says "not measured in this mode" without hiding it.
    dashArray: mode !== "status" && graduated === null ? "3 4" : undefined,
  };
}

/** Colour used for the small square in the legend and in the detail header. */
export function statusAccent(status: MapStatus): string {
  return STATUS_META[status].color;
}

// ------------------------------------------------------------------ freshness
/**
 * "hace 3 min", "hace 12 d" — the age of a reading in words.
 *
 * Every place that shows a measured value shows this next to it. A number
 * without its age is the failure mode the platform has already been bitten by:
 * a stale value rendered exactly like a live one.
 */
export function formatAge(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "sin lecturas";
  if (seconds < 60) return `hace ${Math.round(seconds)} s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `hace ${Math.round(seconds / 3600)} h`;
  return `hace ${Math.round(seconds / 86400)} d`;
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  // Backend timestamps are naive UTC; mark them so the browser converts to the
  // reader's zone instead of silently treating them as local.
  const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "medium" });
}

/** `null` renders as an em dash. Never as 0 — they are different facts. */
export function formatNumber(value: number | null | undefined, digits = 2, unit = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const text = value.toLocaleString("es-MX", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return unit ? `${text} ${unit}` : text;
}

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `$${value.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} MXN`;
}

/** Shown when we have the footprint but nobody has given it a name. */
export const UNIDENTIFIED = "Edificio sin identificar";

/**
 * What to call a footprint, in the order the platform trusts names.
 *
 * 1. the Energy IQ building name — the institutional record, and the only
 *    name that is a database identity;
 * 2. the OSM name, which is a local nickname and often absent;
 * 3. `UNIDENTIFIED`.
 *
 * "Sin identificar" and "Sin monitoreo" answer different questions and must
 * never be conflated: the first says nobody has named this outline, the second
 * says Energy IQ does not measure it. A building can easily be one and not the
 * other.
 */
export function displayName(
  feature: { osm_name: string | null } | null,
  buildings: MapBuilding[],
): string {
  const canonical = leadBuilding(buildings)?.name?.trim();
  if (canonical) return canonical;
  const osm = feature?.osm_name?.trim();
  if (osm) return osm;
  return UNIDENTIFIED;
}

/**
 * The record a shared footprint leads with: the most urgent of them.
 *
 * The same rule the polygon's colour uses, so the panel headline and the map
 * agree. A healthy record must never be the one that speaks for a footprint
 * whose other record is critical.
 */
export function leadBuilding(buildings: MapBuilding[]): MapBuilding | null {
  if (buildings.length === 0) return null;
  const ranked = [...buildings].sort(
    (a, b) => URGENCY_ORDER.indexOf(a.map_status) - URGENCY_ORDER.indexOf(b.map_status),
  );
  return ranked[0];
}

/** Short line under a building name in tooltip and panel. */
export function statusCaption(building: MapBuilding): string {
  const meta = STATUS_META[building.map_status];
  if (building.map_status === "active_stale") {
    return `${meta.short} · ${formatAge(building.telemetry.age_seconds)}`;
  }
  if (building.map_status === "historical") {
    return `${meta.short} · última lectura ${formatAge(building.telemetry.age_seconds)}`;
  }
  return meta.short;
}

export { ACCENT, ACCENT_QUIET };
