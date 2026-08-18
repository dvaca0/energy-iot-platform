/**
 * The measurement vocabulary of the live technical view.
 *
 * This file is the frontend half of the field inventory. Every quantity the
 * page can draw is declared here once, with its unit, its display precision and
 * the metric group that decides whether a given node reports it at all. If a
 * quantity is not in this file, the platform does not store it — see
 * `backend/app/services/live_view.py` for the other half, and the audit note in
 * `docs/Live-Monitoring.md` for the Shelly fields we receive but discard.
 *
 * Precision follows the stored value, not taste. The Shelly Pro 3EM publishes
 * 0.1 V and 1 mA; the backend rounds bucket means to a declared number of
 * places, and the numbers below match it exactly, so a tooltip shows what was
 * measured rather than a re-rounded version of it.
 */

export type Range = "5m" | "15m" | "30m" | "1h" | "6h" | "24h" | "7d" | "deployment";

export const RANGES: { id: Range; label: string }[] = [
  { id: "5m", label: "5 min" },
  { id: "15m", label: "15 min" },
  { id: "30m", label: "30 min" },
  { id: "1h", label: "1 h" },
  { id: "6h", label: "6 h" },
  { id: "24h", label: "24 h" },
  { id: "7d", label: "7 días" },
  { id: "deployment", label: "Despliegue" },
];

/** Ranges the backend serves un-bucketed, and therefore extends incrementally. */
export const RAW_RANGES: Range[] = ["5m", "15m", "30m", "1h"];

/**
 * One sample, or one bucket.
 *
 * Every measured key is optional. The backend **omits** a key whose value is
 * null rather than serialising it, because absence and null carry the same
 * meaning — the quantity was not measured at that instant — and twenty-two of
 * the thirty-three series are empty on every reading stored before the M15
 * schema expansion. Reading a missing key as `undefined` and formatting it as
 * "—" is therefore correct and is what `fmt` does.
 */
export interface Point {
  t: string;
  /** Raw samples behind this point. Present only when the window is bucketed. */
  n?: number;
  /** Interval energy, always emitted (0 is a real answer for this one). */
  kwh?: number | null;
  [series: string]: number | string | null | undefined;
}

export interface Series {
  node_id: string;
  hardware_kind: string | null;
  points: Point[];
}

export interface DeploymentSpan {
  node_id: string | null;
  deployment_id: number;
  building: string | null;
  status: string;
  activated_at: string | null;
  closed_at: string | null;
  /**
   * Readings carrying this deployment's id that fall inside — and outside — its
   * own declared window. They can disagree: attribution is written once at
   * ingest from each measurement's `captured_at` and never recomputed, so a
   * campaign whose window was entered wrongly ends up owning readings its dates
   * do not cover. When `readings_in_window` is 0 the chart is legitimately
   * empty, and the page says so rather than looking broken.
   */
  readings_in_window?: number;
  readings_outside_window?: number;
}

export interface History {
  range: Range;
  /** Populated only for the deployment range. */
  deployments?: DeploymentSpan[];
  /** The deployment the readings were scoped to, when scoped at all. */
  deployment_id?: number | null;
  start: string;
  end: string;
  window_start: string;
  incremental: boolean;
  resolution_seconds: number;
  aggregation: string;
  point_count: number;
  series: Series[];
}

export interface Reading {
  timestamp: string;
  age_seconds: number | null;
  context: string;
  phase_a_voltage: number | null;
  phase_b_voltage: number | null;
  phase_c_voltage: number | null;
  phase_a_current: number | null;
  phase_b_current: number | null;
  phase_c_current: number | null;
  phase_a_power_kw: number | null;
  phase_b_power_kw: number | null;
  phase_c_power_kw: number | null;
  phase_a_apparent_kva: number | null;
  phase_b_apparent_kva: number | null;
  phase_c_apparent_kva: number | null;
  phase_a_power_factor: number | null;
  phase_b_power_factor: number | null;
  phase_c_power_factor: number | null;
  phase_a_frequency_hz: number | null;
  phase_b_frequency_hz: number | null;
  phase_c_frequency_hz: number | null;
  voltage_avg: number | null;
  current_total: number | null;
  power_kw: number | null;
  apparent_kva: number | null;
  power_factor: number | null;
  frequency_hz: number | null;
  neutral_current: number | null;
  meter_energy_kwh: number | null;
  meter_energy_returned_kwh: number | null;
  phase_a_energy_imported_kwh: number | null;
  phase_b_energy_imported_kwh: number | null;
  phase_c_energy_imported_kwh: number | null;
  phase_a_energy_returned_kwh: number | null;
  phase_b_energy_returned_kwh: number | null;
  phase_c_energy_returned_kwh: number | null;
}

export interface Health {
  reported_at: string | null;
  received_at: string | null;
  age_seconds: number | null;
  clock_drift_seconds: number | null;
  collector_status: string | null;
  collector_restarts: number | null;
  buffered_readings: number | null;
  pending_sync: number | null;
  last_measurement_at: string | null;
  cpu_percent: number | null;
  cpu_temperature_c: number | null;
  memory_percent: number | null;
  disk_percent: number | null;
  disk_free_mb: number | null;
  uptime_seconds: number | null;
  undervoltage: boolean | null;
  throttled: boolean | null;
  throttle_flags: string | null;
  filesystem_readonly: boolean | null;
  ethernet_up: boolean | null;
  wifi_up: boolean | null;
  sqlite_size_mb: number | null;
  software_version: string | null;
  ads_ok: boolean | null;
  shelly_reachable: number | null;
  /** The METER's temperature, not the Pi's. */
  meter_temperature_c: number | null;
  local_alerts: string[];
}

export interface NodeSnapshot {
  node_id: string;
  name: string | null;
  hardware_kind: string | null;
  measurement_context: string;
  commission_state: string;
  status: string;
  rpi_status: string;
  shelly_status: string;
  last_sync: string | null;
  last_sync_age_seconds: number | null;
  last_reading_building: string | null;
  deployment: { id: number; status: string; building: string | null } | null;
  reading: Reading | null;
  energy_today_kwh: number;
  available_metrics: string[];
  health: Health | null;
}

export interface Limits {
  nominal_voltage: number;
  voltage_deviation_warning_pct: number;
  voltage_deviation_critical_pct: number;
  missing_phase_voltage: number;
  nominal_frequency_hz: number;
  frequency_deviation_warning_hz: number;
  frequency_deviation_critical_hz: number;
  power_factor_warning: number;
  power_factor_critical: number;
  current_warning_a: number;
  current_critical_a: number;
  voltage_imbalance_warning_pct: number;
  voltage_imbalance_critical_pct: number;
  current_imbalance_warning_pct: number;
  current_imbalance_critical_pct: number;
  imbalance_min_current_a: number;
  node_offline_timeout_s: number;
}

export interface Snapshot {
  generated_at: string;
  limits: Limits;
  nodes: NodeSnapshot[];
}

// ---------------------------------------------------------------- formatting

/** Decimals per unit, matching `PRECISION` in the backend service. */
export const DECIMALS: Record<string, number> = {
  V: 2,
  A: 3,
  kW: 4,
  kVA: 4,
  kvar: 4,
  "": 4, // power factor is dimensionless
  Hz: 3,
  // Interval energy. The cumulative registers use kWh_reg below, because they
  // reach millions of watt-hours and six decimals of a seven-digit number is
  // noise a technician cannot use.
  kWh: 6,
  kWh_reg: 3,
};

/**
 * Format a measured value, or the em dash when there is none.
 *
 * A null is never rendered as 0. The distinction between "this node measured
 * zero amps" and "this node reports no current" is the whole point of the
 * unavailability handling, and collapsing it here would undo it everywhere.
 */
export function fmt(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(DECIMALS[unit] ?? 2);
}

/** Same, with the unit appended. */
export function fmtUnit(value: number | null | undefined, unit: string): string {
  const text = fmt(value, unit);
  if (text === "—") return text;
  return unit ? `${text} ${unit}` : text;
}

/** Compact axis labels — the tooltip carries the exact value. */
export function fmtAxis(value: number, unit: string): string {
  if (unit === "kWh") return value.toFixed(3);
  if (unit === "") return value.toFixed(2);
  if (unit === "Hz") return value.toFixed(2);
  if (unit === "kW") return value.toFixed(1);
  return value.toFixed(unit === "V" ? 0 : 1);
}

export function clockTime(iso: string): string {
  const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return date.toLocaleTimeString("es-MX", { hour12: false });
}

export function clockTimeWithDate(iso: string): string {
  const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return date.toLocaleString("es-MX", { hour12: false });
}

export function humanAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return `${Math.floor(seconds / 86400)} d`;
}

// ------------------------------------------------------------- chart catalog

export interface Line {
  /** Key on `Point`, or a synthetic key for a derived series. */
  key: string;
  /** Phase letter, or null for a total/average. Drives the colour. */
  phase: "A" | "B" | "C" | null;
  label: string;
}

export interface ChartSpec {
  id: string;
  title: string;
  unit: string;
  /** Which metric group a node must report for its series to be drawn. */
  requires: string;
  /** Lines drawn when a single node is selected, or per-phase mode is on. */
  phases: Line[];
  /** Lines drawn when comparing nodes on totals. Empty means "use phases". */
  totals: Line[];
  /** Whether zero is a meaningful floor. Voltage and frequency never are. */
  zeroBaseline: boolean;
  /**
   * Computed, not measured. Present only on the reactive-power chart, and the
   * interface labels every such chart explicitly so a reader can never mistake
   * arithmetic for an instrument reading.
   */
  derived?: {
    /** Metric groups that must both be present for the derivation to be valid. */
    from: string[];
    compute: (point: Point) => number | null;
    explanation: string;
  };
  note?: string;
}

/**
 * Reactive power, derived — never stored.
 *
 * The captured firmware (SPEM-003CEBEU, Pro3EM, 1.4.2) does not expose Q. It
 * exposes P and S, so Q follows from the power triangle:
 *
 *     Q = sqrt(max(S² - P², 0))
 *
 * The `max(…, 0)` is not cosmetic. P and S are measured independently and
 * rounded, so at a near-unity power factor S² − P² can land just below zero;
 * without the clamp the chart would show NaN exactly when the installation is
 * behaving best.
 *
 * Returns null unless BOTH inputs are present at that instant. Deriving from a
 * half-known point would fabricate a number, which is the one thing this page
 * does not do.
 */
function reactive(activeKey: string, apparentKey: string) {
  return (point: Point): number | null => {
    const p = point[activeKey];
    const s = point[apparentKey];
    if (typeof p !== "number" || typeof s !== "number") return null;
    return Math.sqrt(Math.max(s * s - p * p, 0));
  };
}

/**
 * Every chart the page can draw, in display order.
 *
 * The catalogue mirrors the real device contract captured from N001's meter on
 * 2026-08-18. A quantity absent from that capture is absent here: there is no
 * per-phase reactive-power chart, and no meter-error chart, because the
 * firmware reports neither.
 *
 * A chart whose metric no selected node reports is not drawn as an empty axis —
 * the page collects those into one honest "no disponible" list instead.
 */
export const CHARTS: ChartSpec[] = [
  {
    id: "phase_voltage",
    title: "Tensión por fase",
    unit: "V",
    requires: "phase_voltage",
    phases: [
      { key: "va", phase: "A", label: "A" },
      { key: "vb", phase: "B", label: "B" },
      { key: "vc", phase: "C", label: "C" },
    ],
    totals: [],
    zeroBaseline: false,
  },
  {
    id: "phase_current",
    title: "Corriente por fase",
    unit: "A",
    requires: "phase_current",
    phases: [
      { key: "ia", phase: "A", label: "A" },
      { key: "ib", phase: "B", label: "B" },
      { key: "ic", phase: "C", label: "C" },
    ],
    totals: [],
    zeroBaseline: true,
  },
  {
    id: "current_total",
    title: "Corriente total (suma de fases)",
    unit: "A",
    requires: "current",
    phases: [{ key: "i", phase: null, label: "I total" }],
    totals: [{ key: "i", phase: null, label: "I total" }],
    zeroBaseline: true,
  },
  {
    id: "neutral_current",
    title: "Corriente de neutro",
    unit: "A",
    requires: "neutral_current",
    phases: [{ key: "nc", phase: null, label: "I neutro" }],
    totals: [{ key: "nc", phase: null, label: "I neutro" }],
    zeroBaseline: true,
    note: "El medidor devuelve n_current nulo cuando la instalación no tiene TC de neutro.",
  },
  {
    id: "phase_power",
    title: "Potencia activa por fase",
    unit: "kW",
    requires: "phase_power",
    phases: [
      { key: "pa", phase: "A", label: "A" },
      { key: "pb", phase: "B", label: "B" },
      { key: "pc", phase: "C", label: "C" },
    ],
    totals: [],
    zeroBaseline: true,
  },
  {
    id: "power_kw",
    title: "Potencia activa total",
    unit: "kW",
    requires: "power_kw",
    phases: [{ key: "kw", phase: null, label: "kW" }],
    totals: [{ key: "kw", phase: null, label: "kW" }],
    zeroBaseline: true,
  },
  {
    id: "phase_apparent",
    title: "Potencia aparente por fase",
    unit: "kVA",
    requires: "phase_apparent",
    phases: [
      { key: "sa", phase: "A", label: "A" },
      { key: "sb", phase: "B", label: "B" },
      { key: "sc", phase: "C", label: "C" },
    ],
    totals: [],
    zeroBaseline: true,
  },
  {
    id: "apparent_kva",
    title: "Potencia aparente total",
    unit: "kVA",
    requires: "apparent_kva",
    phases: [{ key: "kva", phase: null, label: "kVA" }],
    totals: [{ key: "kva", phase: null, label: "kVA" }],
    zeroBaseline: true,
  },
  {
    id: "reactive_derived",
    title: "Potencia reactiva calculada",
    unit: "kvar",
    requires: "power_kw",
    phases: [{ key: "q", phase: null, label: "Q (calc.)" }],
    totals: [{ key: "q", phase: null, label: "Q (calc.)" }],
    zeroBaseline: true,
    derived: {
      from: ["power_kw", "apparent_kva"],
      compute: reactive("kw", "kva"),
      explanation: "Q = √(S² − P²) a partir de la potencia activa y aparente medidas.",
    },
  },
  {
    id: "phase_power_factor",
    title: "Factor de potencia por fase",
    unit: "",
    requires: "phase_power_factor",
    phases: [
      { key: "pfa", phase: "A", label: "A" },
      { key: "pfb", phase: "B", label: "B" },
      { key: "pfc", phase: "C", label: "C" },
    ],
    totals: [],
    zeroBaseline: false,
  },
  {
    id: "power_factor",
    title: "Factor de potencia total",
    unit: "",
    requires: "power_factor",
    phases: [{ key: "pf", phase: null, label: "PF" }],
    totals: [{ key: "pf", phase: null, label: "PF" }],
    zeroBaseline: false,
    note: "Cociente P/S calculado por el colector; el medidor no publica un PF agregado.",
  },
  {
    id: "phase_frequency",
    title: "Frecuencia por fase",
    unit: "Hz",
    requires: "phase_frequency",
    phases: [
      { key: "fa", phase: "A", label: "A" },
      { key: "fb", phase: "B", label: "B" },
      { key: "fc", phase: "C", label: "C" },
    ],
    totals: [],
    zeroBaseline: false,
  },
  {
    id: "frequency",
    title: "Frecuencia agregada",
    unit: "Hz",
    requires: "frequency_hz",
    phases: [{ key: "hz", phase: null, label: "Hz" }],
    totals: [{ key: "hz", phase: null, label: "Hz" }],
    zeroBaseline: false,
  },
  {
    id: "voltage_avg",
    title: "Tensión promedio (fases energizadas)",
    unit: "V",
    requires: "voltage",
    phases: [{ key: "v", phase: null, label: "V prom" }],
    totals: [{ key: "v", phase: null, label: "V prom" }],
    zeroBaseline: false,
  },
  {
    id: "energy_interval",
    title: "Energía por intervalo",
    unit: "kWh",
    requires: "power_kw",
    phases: [{ key: "kwh", phase: null, label: "kWh" }],
    totals: [{ key: "kwh", phase: null, label: "kWh" }],
    zeroBaseline: true,
    note: "Resuelta por el servicio canónico según la era de medición (ADR-0007), no el registro crudo.",
  },
  {
    id: "energy_imported",
    title: "Energía importada acumulada (registro del medidor)",
    unit: "kWh_reg",
    requires: "energy_imported",
    phases: [
      { key: "imp_a", phase: "A", label: "A" },
      { key: "imp_b", phase: "B", label: "B" },
      { key: "imp_c", phase: "C", label: "C" },
      { key: "imp_t", phase: null, label: "Total" },
    ],
    totals: [{ key: "imp_t", phase: null, label: "Total" }],
    zeroBaseline: false,
    note: "Contador monotónico del medidor. Sólo para conciliación; ningún análisis lo diferencia.",
  },
  {
    id: "energy_returned",
    title: "Energía devuelta acumulada (registro del medidor)",
    unit: "kWh_reg",
    requires: "energy_returned",
    phases: [
      { key: "ret_a", phase: "A", label: "A" },
      { key: "ret_b", phase: "B", label: "B" },
      { key: "ret_c", phase: "C", label: "C" },
      { key: "ret_t", phase: null, label: "Total" },
    ],
    totals: [{ key: "ret_t", phase: null, label: "Total" }],
    zeroBaseline: false,
    note: "Energía exportada hacia la red, según el registro del medidor.",
  },
];

/** Whether a node can supply a chart — including the two-input derived case. */
export function nodeSupports(node: NodeSnapshot, spec: ChartSpec): boolean {
  if (spec.derived) return spec.derived.from.every((m) => node.available_metrics.includes(m));
  return node.available_metrics.includes(spec.requires);
}

// ---------------------------------------------------------------- conditions

export type Level = "ok" | "warn" | "crit";

export interface Condition {
  level: Level;
  label: string;
  detail: string;
}

function spreadPct(values: (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null && value !== undefined);
  if (present.length < 2) return null;
  const max = Math.max(...present);
  const min = Math.min(...present);
  const mean = present.reduce((sum, value) => sum + value, 0) / present.length;
  if (mean === 0) return null;
  return ((max - min) / mean) * 100;
}

/**
 * Technical conditions for one node, evaluated against the platform's own
 * limits.
 *
 * Every number compared here arrives from `/api/metrics/live/snapshot`, which
 * reads `app.monitoring.config` — the same source the alerting rules use. The
 * page holds no thresholds of its own, so a badge here and a Telegram alert can
 * never disagree. This is a diagnostic hint, not an alert: nothing is raised,
 * escalated or notified from the browser.
 */
export function conditions(node: NodeSnapshot, limits: Limits): Condition[] {
  const found: Condition[] = [];
  const reading = node.reading;

  if (node.rpi_status !== "ok") {
    found.push({
      level: "crit",
      label: "Raspberry sin contacto",
      detail: `Último heartbeat hace ${humanAge(node.last_sync_age_seconds)}`,
    });
  }

  if (reading === null) {
    found.push({ level: "crit", label: "Sin lecturas", detail: "El nodo nunca ha almacenado una medición" });
    return found;
  }

  const age = reading.age_seconds;
  if (age !== null && age > limits.node_offline_timeout_s) {
    found.push({
      level: "crit",
      label: "Lectura obsoleta",
      detail: `Última medición hace ${humanAge(age)} (límite ${humanAge(limits.node_offline_timeout_s)})`,
    });
  }

  const phaseVoltages = [
    reading.phase_a_voltage,
    reading.phase_b_voltage,
    reading.phase_c_voltage,
  ];
  const energised = phaseVoltages.filter(
    (value): value is number => value !== null && value >= limits.missing_phase_voltage,
  );
  const dead = phaseVoltages
    .map((value, index) => ({ value, name: "ABC"[index] }))
    .filter((entry) => entry.value !== null && entry.value < limits.missing_phase_voltage);
  if (energised.length > 0 && dead.length > 0) {
    found.push({
      level: "crit",
      label: `Fase ausente (${dead.map((entry) => entry.name).join(", ")})`,
      detail: `Por debajo de ${limits.missing_phase_voltage} V mientras las demás están energizadas`,
    });
  }

  if (reading.voltage_avg !== null && reading.voltage_avg >= limits.missing_phase_voltage) {
    const deviation =
      (Math.abs(reading.voltage_avg - limits.nominal_voltage) / limits.nominal_voltage) * 100;
    if (deviation > limits.voltage_deviation_warning_pct) {
      found.push({
        level: deviation > limits.voltage_deviation_critical_pct ? "crit" : "warn",
        label: "Tensión fuera de rango",
        detail: `${deviation.toFixed(1)} % respecto de ${limits.nominal_voltage} V nominales`,
      });
    }
  }

  if (reading.frequency_hz !== null && reading.frequency_hz > 0) {
    const deviation = Math.abs(reading.frequency_hz - limits.nominal_frequency_hz);
    if (deviation > limits.frequency_deviation_warning_hz) {
      found.push({
        level: deviation > limits.frequency_deviation_critical_hz ? "crit" : "warn",
        label: "Frecuencia fuera de rango",
        detail: `${reading.frequency_hz.toFixed(3)} Hz frente a ${limits.nominal_frequency_hz} ±${limits.frequency_deviation_warning_hz} Hz`,
      });
    }
  }

  if (reading.power_factor !== null && (reading.current_total ?? 0) >= limits.imbalance_min_current_a) {
    if (reading.power_factor < limits.power_factor_warning) {
      found.push({
        level: reading.power_factor < limits.power_factor_critical ? "crit" : "warn",
        label: "Factor de potencia bajo",
        detail: `${reading.power_factor.toFixed(4)} frente a ${limits.power_factor_warning} mínimo`,
      });
    }
  }

  if (reading.current_total !== null && reading.current_total > limits.current_warning_a) {
    found.push({
      level: reading.current_total > limits.current_critical_a ? "crit" : "warn",
      label: "Corriente elevada",
      detail: `${reading.current_total.toFixed(3)} A frente a ${limits.current_warning_a} A`,
    });
  }

  // Imbalance is meaningless at the noise floor: an idle panel reads ~1e-5 A
  // and the spread between two noise samples is arbitrarily large. The backend
  // rules guard on exactly this current, and so does this badge.
  const phaseCurrents = [
    reading.phase_a_current,
    reading.phase_b_current,
    reading.phase_c_current,
  ];
  const loaded = (reading.current_total ?? 0) >= limits.imbalance_min_current_a;
  const currentSpread = loaded ? spreadPct(phaseCurrents) : null;
  if (currentSpread !== null && currentSpread > limits.current_imbalance_warning_pct) {
    found.push({
      level: currentSpread > limits.current_imbalance_critical_pct ? "crit" : "warn",
      label: "Desbalance de corriente",
      detail: `${currentSpread.toFixed(1)} % entre fases (umbral ${limits.current_imbalance_warning_pct} %)`,
    });
  }

  const voltageSpread = energised.length >= 2 ? spreadPct(phaseVoltages) : null;
  if (voltageSpread !== null && voltageSpread > limits.voltage_imbalance_warning_pct) {
    found.push({
      level: voltageSpread > limits.voltage_imbalance_critical_pct ? "crit" : "warn",
      label: "Desbalance de tensión",
      detail: `${voltageSpread.toFixed(2)} % entre fases (umbral ${limits.voltage_imbalance_warning_pct} %)`,
    });
  }

  const pending = node.health?.pending_sync ?? null;
  if (pending !== null && pending > 0) {
    found.push({
      level: "warn",
      label: "Buffer pendiente",
      detail: `${pending.toLocaleString("es-MX")} lecturas sin subir en el nodo`,
    });
  }

  if (node.health?.collector_status && node.health.collector_status !== "active") {
    found.push({
      level: "crit",
      label: "Colector no activo",
      detail: `Estado reportado: ${node.health.collector_status}`,
    });
  }

  if (node.health?.ads_ok === false) {
    found.push({
      level: "crit",
      label: "ADC sin responder",
      detail: "El nodo reporta su convertidor analógico-digital como no funcional",
    });
  }

  return found;
}
