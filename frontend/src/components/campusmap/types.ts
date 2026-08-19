/**
 * Shapes returned by `/api/campus-map`, written out so the map layer never has
 * to guess at a field name.
 *
 * Every measured quantity is `number | null`. Null means the meter did not
 * report it — not zero. The interface renders those as "—", because a phase
 * shown as 0.00 A reads as a de-energised conductor.
 */

export type MapStatus =
  | "unregistered"
  | "registered"
  | "historical"
  | "active_stale"
  | "active_healthy"
  | "active_warning"
  | "active_critical";

export interface PhaseReading {
  voltage: number | null;
  current: number | null;
  power_kw: number | null;
  apparent_kva: number | null;
  power_factor: number | null;
  frequency_hz: number | null;
}

export interface ReadingSnapshot {
  timestamp: string;
  power_kw: number | null;
  voltage: number | null;
  current: number | null;
  apparent_kva: number | null;
  power_factor: number | null;
  frequency_hz: number | null;
  neutral_current: number | null;
  context: string;
  phases: Record<string, PhaseReading> | null;
}

export interface Telemetry {
  last_reading_at: string | null;
  age_seconds: number | null;
  is_live: boolean;
  window_seconds: number;
}

export interface DeploymentSummary {
  id: number;
  status: string;
  is_operational: boolean;
  start_date: string;
  end_date: string | null;
  activated_at: string | null;
  closed_at: string | null;
  panel: string | null;
  node: {
    id: number;
    code: string;
    name: string;
    measurement_context: string;
    commission_state: string;
  } | null;
}

export interface AlertSummary {
  open_count: number;
  max_severity: string | null;
  items: Array<{
    id: number;
    alert_id: string;
    severity: string;
    title: string;
    created_at: string | null;
  }>;
}

export interface MapBuilding {
  id: number;
  code: string;
  name: string;
  campus_id: number;
  campus: string;
  organizational_unit: string | null;
  is_placeholder: boolean;
  map_status: MapStatus;
  deployment: DeploymentSummary | null;
  deployment_count: number;
  telemetry: Telemetry;
  latest_reading: ReadingSnapshot | null;
  energy_today_kwh: number;
  cost_today_mxn: number;
  alerts: AlertSummary;
}

/** OSM identity and Energy IQ identity, side by side and never conflated. */
export interface FootprintProperties {
  osm_type: string;
  osm_id: number;
  osm_name: string | null;
  osm_building: string | null;
  osm_operator: string | null;
  energy_iq_building_ids: number[];
  map_status: MapStatus;
  association_confidence: string | null;
}

export interface Footprint {
  type: "Feature";
  id: string;
  properties: FootprintProperties;
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: unknown };
}

export interface CampusMapPayload {
  campus: { id: number; name: string; location: string | null; delegation: string | null };
  view: {
    has_geometry: boolean;
    fallback_center: [number, number] | null;
    fallback_zoom: number | null;
  };
  geometry: { type: "FeatureCollection"; features: Footprint[] } | null;
  /** Campus property outline as bare GeoJSON rings. Not buildings. */
  grounds: number[][][] | null;
  buildings: MapBuilding[];
  unmapped_building_ids: number[];
  orphan_associations: Array<Record<string, unknown> & { reasons: string[] }>;
  telemetry_window_seconds: number;
  attribution: string;
  generated_at: string;
}

export interface CampusOption {
  id: number;
  name: string;
  location: string | null;
  delegation: string | null;
  has_geometry: boolean;
  footprint_count: number;
  energy_iq_buildings: number;
  mapped_buildings: number;
}

/**
 * One row of `/api/metrics/campuses` — the platform's single definition of
 * campus power, energy and cost. The map reads it; it never recomputes it.
 */
export interface CampusMetrics {
  id: number;
  name: string;
  delegation: string;
  status: string;
  monitored_buildings: number;
  total_buildings: number;
  power_kw: number;
  energy_today_kwh: number;
  cost_today_mxn: number;
}

/** Which quantity the polygons are coloured by. */
export type MapMode = "status" | "power" | "energy" | "cost" | "power_factor";
