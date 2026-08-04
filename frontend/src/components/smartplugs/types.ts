/**
 * Modelo de datos del módulo Smart Plugs (Shelly Plug US Gen4).
 *
 * La identidad permanente de un enchufe es su dirección MAC. La IP es
 * volátil (DHCP) y nunca debe usarse para identificar un dispositivo.
 *
 * Los nombres de campo replican el contrato del backend:
 *   GET  /api/smart-plugs
 *   POST /api/smart-plugs/{id}/assign
 *   GET  /api/smart-plugs/{id}/history
 */

export interface SmartPlug {
  /** Identificador estable usado en las rutas del API. */
  id: string;
  /** Identidad permanente del dispositivo. */
  mac: string;
  model: string;

  /** Datos de red volátiles reportados por la Raspberry que lo descubrió. */
  ip: string | null;
  hostname: string | null;
  serial: string | null;
  firmware: string | null;
  rssi: number | null;
  temperature_c: number | null;

  /** Asignación administrativa. */
  node: string | null;
  building: string | null;
  deployment: string | null;
  friendly_name: string | null;
  outlet_location: string | null;

  /** Telemetría instantánea. */
  online: boolean;
  last_seen: string | null;
  power_w: number | null;
  voltage_v: number | null;
  current_a: number | null;
  power_factor: number | null;
  energy_today_kwh: number | null;
}

/**
 * Cuerpo de POST /api/smart-plugs/{id}/assign.
 * Se declara como alias de tipo (no interface) para que sea asignable
 * directamente al payload Record<string, string> del cliente HTTP.
 */
export type SmartPlugAssignment = {
  friendly_name: string;
  building: string;
  deployment: string;
  outlet_location: string;
};

/** Punto de GET /api/smart-plugs/{id}/history */
export interface SmartPlugHistoryPoint {
  timestamp: string;
  power_w: number | null;
  energy_kwh: number | null;
}

export type SmartPlugStatusFilter = "all" | "online" | "offline" | "unassigned";

export type SmartPlugBadgeVariant = "online" | "offline" | "unassigned";

export interface SmartPlugFilterState {
  search: string;
  status: SmartPlugStatusFilter;
  building: string;
  deployment: string;
  node: string;
}

export const EMPTY_FILTERS: SmartPlugFilterState = {
  search: "",
  status: "all",
  building: "all",
  deployment: "all",
  node: "all",
};

export interface SmartPlugSummaryData {
  online: number;
  offline: number;
  unassigned: number;
  powerW: number;
  energyTodayKwh: number;
}

/**
 * Un enchufe se considera asignado cuando un técnico le dio un nombre
 * amigable y lo ubicó dentro de un edificio.
 */
export function isPlugAssigned(plug: SmartPlug): boolean {
  return Boolean(plug.friendly_name && plug.building);
}

/** Un enchufe descubierto pero no asignado se resalta por encima de su conexión. */
export function plugVariant(plug: SmartPlug): SmartPlugBadgeVariant {
  if (!isPlugAssigned(plug)) return "unassigned";
  return plug.online ? "online" : "offline";
}

export function plugDisplayName(plug: SmartPlug): string {
  return plug.friendly_name || plug.model || plug.mac;
}

export function summarize(plugs: SmartPlug[]): SmartPlugSummaryData {
  return plugs.reduce<SmartPlugSummaryData>(
    (acc, plug) => ({
      online: acc.online + (plug.online ? 1 : 0),
      offline: acc.offline + (plug.online ? 0 : 1),
      unassigned: acc.unassigned + (isPlugAssigned(plug) ? 0 : 1),
      powerW: acc.powerW + (plug.online ? Number(plug.power_w || 0) : 0),
      energyTodayKwh: acc.energyTodayKwh + Number(plug.energy_today_kwh || 0),
    }),
    { online: 0, offline: 0, unassigned: 0, powerW: 0, energyTodayKwh: 0 }
  );
}

/** Enchufe en línea con mayor consumo instantáneo. */
export function highestConsumer(plugs: SmartPlug[]): SmartPlug | null {
  const online = plugs.filter((plug) => plug.online && Number(plug.power_w || 0) > 0);
  if (online.length === 0) return null;

  return online.reduce((top, plug) =>
    Number(plug.power_w || 0) > Number(top.power_w || 0) ? plug : top
  );
}

export function applyFilters(plugs: SmartPlug[], filters: SmartPlugFilterState): SmartPlug[] {
  const search = filters.search.trim().toLowerCase();

  return plugs.filter((plug) => {
    if (filters.status === "online" && !plug.online) return false;
    if (filters.status === "offline" && plug.online) return false;
    if (filters.status === "unassigned" && isPlugAssigned(plug)) return false;

    if (filters.building !== "all" && plug.building !== filters.building) return false;
    if (filters.deployment !== "all" && plug.deployment !== filters.deployment) return false;
    if (filters.node !== "all" && plug.node !== filters.node) return false;

    if (!search) return true;

    return [
      plug.friendly_name,
      plug.model,
      plug.mac,
      plug.ip,
      plug.hostname,
      plug.building,
      plug.deployment,
      plug.outlet_location,
      plug.node,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(search);
  });
}

/** Valores únicos de un campo, para poblar los selectores de filtro. */
export function distinctValues(plugs: SmartPlug[], field: "building" | "deployment" | "node"): string[] {
  const values = plugs
    .map((plug) => plug[field])
    .filter((value): value is string => Boolean(value));

  return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b, "es-MX"));
}
