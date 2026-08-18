/**
 * The instantaneous card: everything one node is measuring at this moment.
 *
 * This is the evolution of the compact summary the page already had. The shape
 * is kept — a header identifying the node, then a dense grid of current values —
 * but it now carries the whole of what is stored: per-phase detail beside the
 * totals, the freshness of the reading, and the condition of the Raspberry Pi
 * underneath it.
 *
 * Density is the point. A technician glances at this instead of reading it, so
 * values are tabular-aligned and grouped by what they answer: *the phases*,
 * *the totals*, *the node*. A metric the node does not report reads
 * "no disponible" and is greyed — never 0, which would be a measurement.
 */
import {
  BORDER,
  BORDER_SOFT,
  CRIT,
  IDLE,
  OK,
  PHASE_COLORS,
  SURFACE_INNER,
  SURFACE_SUNK,
  TEXT,
  TEXT_MUTED,
  TEXT_SECONDARY,
  WARN,
  cardStyle,
  labelStyle,
} from "./styles";
import type { Condition, Level, Limits, NodeSnapshot } from "./types";
import { clockTime, conditions, fmt, humanAge } from "./types";

const LEVEL_COLOR: Record<Level, string> = { ok: OK, warn: WARN, crit: CRIT };

function Chip({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span
      style={{
        background: `${color}14`,
        color,
        border: `1px solid ${color}33`,
        borderRadius: 4,
        padding: "2.5px 7px",
        fontSize: 10.5,
        fontWeight: 500,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

/** A single measured value. `available` false renders the honest absence. */
function Value({
  label,
  value,
  unit,
  available,
}: {
  label: string;
  value: number | null;
  unit: string;
  available: boolean;
}) {
  return (
    <div
      style={{
        background: SURFACE_INNER,
        border: `1px solid ${BORDER_SOFT}`,
        borderRadius: 7,
        padding: "8px 10px",
        minWidth: 92,
      }}
    >
      <div style={{ ...labelStyle, marginBottom: 4 }}>{label}</div>
      {available ? (
        <div
          style={{
            fontSize: 16,
            fontWeight: 600,
            color: TEXT,
            letterSpacing: -0.3,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {fmt(value, unit)}
          {unit && <span style={{ fontSize: 10.5, color: TEXT_MUTED, marginLeft: 3 }}>{unit}</span>}
        </div>
      ) : (
        <div style={{ fontSize: 11.5, color: IDLE, fontStyle: "italic" }}>no disponible</div>
      )}
    </div>
  );
}

function HealthItem({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "3px 0" }}>
      <span style={{ fontSize: 10.5, color: TEXT_MUTED }}>{label}</span>
      <span
        style={{
          fontSize: 11,
          color: color ?? TEXT_SECONDARY,
          fontWeight: 500,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
    </div>
  );
}

export function NodeSummaryCard({ node, limits }: { node: NodeSnapshot; limits: Limits }) {
  const reading = node.reading;
  const health = node.health;
  const found: Condition[] = conditions(node, limits);
  const worst: Level = found.some((entry) => entry.level === "crit")
    ? "crit"
    : found.some((entry) => entry.level === "warn")
      ? "warn"
      : "ok";

  const has = (metric: string) => node.available_metrics.includes(metric);

  // One row per phase, one column per quantity the meter publishes per phase.
  // This is the layout the original request sketched and that was not buildable
  // until M15 — before it, only V and A existed per phase.
  const phases: {
    name: "A" | "B" | "C";
    v: number | null;
    i: number | null;
    p: number | null;
    s: number | null;
    pf: number | null;
    f: number | null;
  }[] = [
    {
      name: "A",
      v: reading?.phase_a_voltage ?? null,
      i: reading?.phase_a_current ?? null,
      p: reading?.phase_a_power_kw ?? null,
      s: reading?.phase_a_apparent_kva ?? null,
      pf: reading?.phase_a_power_factor ?? null,
      f: reading?.phase_a_frequency_hz ?? null,
    },
    {
      name: "B",
      v: reading?.phase_b_voltage ?? null,
      i: reading?.phase_b_current ?? null,
      p: reading?.phase_b_power_kw ?? null,
      s: reading?.phase_b_apparent_kva ?? null,
      pf: reading?.phase_b_power_factor ?? null,
      f: reading?.phase_b_frequency_hz ?? null,
    },
    {
      name: "C",
      v: reading?.phase_c_voltage ?? null,
      i: reading?.phase_c_current ?? null,
      p: reading?.phase_c_power_kw ?? null,
      s: reading?.phase_c_apparent_kva ?? null,
      pf: reading?.phase_c_power_factor ?? null,
      f: reading?.phase_c_frequency_hz ?? null,
    },
  ];

  /** Column heading, unit, and the metric group that decides whether it has data. */
  const phaseColumns: {
    head: string;
    unit: string;
    metric: string;
    pick: (row: (typeof phases)[number]) => number | null;
  }[] = [
    { head: "V", unit: "V", metric: "phase_voltage", pick: (row) => row.v },
    { head: "A", unit: "A", metric: "phase_current", pick: (row) => row.i },
    { head: "kW", unit: "kW", metric: "phase_power", pick: (row) => row.p },
    { head: "kVA", unit: "kVA", metric: "phase_apparent", pick: (row) => row.s },
    { head: "PF", unit: "", metric: "phase_power_factor", pick: (row) => row.pf },
    { head: "Hz", unit: "Hz", metric: "phase_frequency", pick: (row) => row.f },
  ];

  const readingFresh =
    reading?.age_seconds !== null &&
    reading?.age_seconds !== undefined &&
    reading.age_seconds <= limits.node_offline_timeout_s;

  return (
    <div style={{ ...cardStyle, borderColor: worst === "ok" ? BORDER : `${LEVEL_COLOR[worst]}44` }}>
      {/* ---------------------------------------------------------- header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 14,
          flexWrap: "wrap",
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <div
            style={{
              background: SURFACE_INNER,
              border: `1px solid ${BORDER}`,
              borderRadius: 6,
              padding: "6px 9px",
              fontSize: 10.5,
              color: TEXT_SECONDARY,
              fontWeight: 600,
              letterSpacing: 0.5,
            }}
          >
            NODE
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: TEXT }}>{node.node_id}</span>
              <span style={{ fontSize: 11.5, color: TEXT_MUTED }}>{node.name}</span>
            </div>
            <div style={{ fontSize: 11, color: TEXT_MUTED, marginTop: 2 }}>
              {node.last_reading_building ?? "Lectura sin edificio"}
              {" · "}
              {reading
                ? `última lectura ${clockTime(reading.timestamp)} (hace ${humanAge(reading.age_seconds)})`
                : "sin lecturas almacenadas"}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <Chip color={TEXT_MUTED}>{node.hardware_kind ?? "hardware sin declarar"}</Chip>
          <Chip color={TEXT_MUTED}>{reading?.context ?? node.measurement_context}</Chip>
          <Chip color={node.commission_state === "commissioned" ? OK : WARN}>
            {node.commission_state}
          </Chip>
          <Chip color={readingFresh ? OK : IDLE}>{readingFresh ? "MIDIENDO" : "SIN DATOS FRESCOS"}</Chip>
        </div>
      </div>

      {reading === null ? (
        <div style={{ fontSize: 12, color: TEXT_MUTED, padding: "10px 0 14px" }}>
          Este nodo no tiene ninguna lectura almacenada, así que no hay valores instantáneos que
          mostrar. Su estado se lee abajo, en el heartbeat.
        </div>
      ) : (
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 14 }}>
          {/* ------------------------------------------------------ phases */}
          <div
            style={{
              background: SURFACE_SUNK,
              border: `1px solid ${BORDER_SOFT}`,
              borderRadius: 9,
              padding: "11px 13px",
              flex: "1 1 260px",
            }}
          >
            <div style={{ ...labelStyle, marginBottom: 8 }}>Por fase</div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ ...labelStyle, textAlign: "left", paddingBottom: 5, fontWeight: 500 }} />
                  {phaseColumns.map((column) => (
                    <th
                      key={column.head}
                      style={{
                        ...labelStyle,
                        textAlign: "right",
                        paddingBottom: 5,
                        paddingLeft: 8,
                        fontWeight: 500,
                        color: has(column.metric) ? TEXT_MUTED : IDLE,
                      }}
                    >
                      {column.head}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {phases.map((phase) => (
                  <tr key={phase.name}>
                    <td style={{ padding: "3px 0" }}>
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                          fontSize: 11.5,
                          color: TEXT_SECONDARY,
                          whiteSpace: "nowrap",
                        }}
                      >
                        <span
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: 2,
                            background: PHASE_COLORS[phase.name],
                          }}
                        />
                        Fase {phase.name}
                      </span>
                    </td>
                    {phaseColumns.map((column) => (
                      <td
                        key={column.head}
                        style={{
                          textAlign: "right",
                          fontSize: 12.5,
                          paddingLeft: 8,
                          color: has(column.metric) ? TEXT : IDLE,
                          fontVariantNumeric: "tabular-nums",
                          padding: "3px 0 3px 8px",
                        }}
                        // "n/d" is not a formatting fallback — it is the answer.
                        // The node does not report this quantity, which is a
                        // different fact from reporting zero.
                        title={has(column.metric) ? undefined : "El nodo no reporta esta magnitud"}
                      >
                        {has(column.metric) ? fmt(column.pick(phase), column.unit) : "n/d"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* ------------------------------------------------------ totals */}
          <div style={{ flex: "2 1 420px" }}>
            <div style={{ ...labelStyle, marginBottom: 8 }}>Totales</div>
            <div style={{ display: "flex", gap: 9, flexWrap: "wrap" }}>
              <Value
                label="Potencia activa"
                value={reading.power_kw}
                unit="kW"
                available={has("power_kw")}
              />
              <Value
                label="Potencia aparente"
                value={reading.apparent_kva}
                unit="kVA"
                available={has("apparent_kva")}
              />
              <Value
                label="Corriente total"
                value={reading.current_total}
                unit="A"
                available={has("current")}
              />
              <Value
                label="Corriente neutro"
                value={reading.neutral_current}
                unit="A"
                available={has("neutral_current")}
              />
              <Value
                label="Tensión prom."
                value={reading.voltage_avg}
                unit="V"
                available={has("voltage")}
              />
              <Value
                label="Factor de pot."
                value={reading.power_factor}
                unit=""
                available={has("power_factor")}
              />
              <Value
                label="Frecuencia"
                value={reading.frequency_hz}
                unit="Hz"
                available={has("frequency_hz")}
              />
              <Value label="Energía hoy" value={node.energy_today_kwh} unit="kWh" available />
              <Value
                label="Registro importada"
                value={reading.meter_energy_kwh}
                unit="kWh_reg"
                available={has("energy_imported")}
              />
              <Value
                label="Registro devuelta"
                value={reading.meter_energy_returned_kwh}
                unit="kWh_reg"
                available={has("energy_returned")}
              />
            </div>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------- health */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(168px, 1fr))",
          gap: "2px 22px",
          background: SURFACE_SUNK,
          border: `1px solid ${BORDER_SOFT}`,
          borderRadius: 9,
          padding: "10px 13px",
        }}
      >
        <HealthItem
          label="Raspberry Pi"
          value={node.rpi_status === "ok" ? "en línea" : "sin contacto"}
          color={node.rpi_status === "ok" ? OK : CRIT}
        />
        <HealthItem
          label="Medidor"
          value={node.shelly_status === "ok" ? "reportando" : "sin lecturas"}
          color={node.shelly_status === "ok" ? OK : CRIT}
        />
        <HealthItem
          label="Buffer pendiente"
          value={
            health?.pending_sync === null || health?.pending_sync === undefined
              ? "—"
              : health.pending_sync.toLocaleString("es-MX")
          }
          color={(health?.pending_sync ?? 0) > 0 ? WARN : OK}
        />
        <HealthItem label="Heartbeat" value={`hace ${humanAge(health?.age_seconds)}`} />
        <HealthItem
          label="Colector"
          value={health?.collector_status ?? "—"}
          color={health?.collector_status === "active" ? OK : health ? WARN : undefined}
        />
        <HealthItem
          label="CPU"
          value={health?.cpu_percent !== null && health?.cpu_percent !== undefined ? `${health.cpu_percent} %` : "—"}
        />
        <HealthItem
          label="Temp. Raspberry"
          value={
            health?.cpu_temperature_c !== null && health?.cpu_temperature_c !== undefined
              ? `${health.cpu_temperature_c} °C`
              : "—"
          }
        />
        {/* The meter's own temperature — a different device from the Pi above.
            Health telemetry, which is why it lives on the heartbeat and not on
            the reading. */}
        <HealthItem
          label="Temp. medidor"
          value={
            health?.meter_temperature_c !== null && health?.meter_temperature_c !== undefined
              ? `${health.meter_temperature_c} °C`
              : "—"
          }
        />
        <HealthItem
          label="Disco"
          value={health?.disk_percent !== null && health?.disk_percent !== undefined ? `${health.disk_percent} %` : "—"}
        />
        <HealthItem
          label="Desfase de reloj"
          value={
            health?.clock_drift_seconds !== null && health?.clock_drift_seconds !== undefined
              ? `${health.clock_drift_seconds.toFixed(2)} s`
              : "—"
          }
        />
        <HealthItem label="Software" value={health?.software_version ?? "—"} />
      </div>

      {/* Sticky flags the node raises about itself. Undervoltage and throttling
          are latched since boot, so they describe history, not this instant. */}
      {(health?.undervoltage || health?.throttled || health?.filesystem_readonly) && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 9 }}>
          {health?.undervoltage && <Chip color={WARN}>subtensión registrada desde el arranque</Chip>}
          {health?.throttled && <Chip color={WARN}>throttling activo</Chip>}
          {health?.filesystem_readonly && <Chip color={TEXT_MUTED}>raíz de sólo lectura</Chip>}
        </div>
      )}

      {/* ------------------------------------------------------ conditions */}
      {found.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ ...labelStyle, marginBottom: 6 }}>
            Condiciones técnicas · umbrales de la plataforma
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {found.map((condition) => (
              <div
                key={condition.label}
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 9,
                  flexWrap: "wrap",
                  background: SURFACE_INNER,
                  border: `1px solid ${LEVEL_COLOR[condition.level]}26`,
                  borderRadius: 6,
                  padding: "6px 10px",
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: LEVEL_COLOR[condition.level],
                    flexShrink: 0,
                  }}
                />
                <span style={{ fontSize: 11.5, color: TEXT, fontWeight: 500 }}>{condition.label}</span>
                <span style={{ fontSize: 11, color: TEXT_MUTED }}>{condition.detail}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
