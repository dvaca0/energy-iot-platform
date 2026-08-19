/**
 * The side panel: everything the backend knows about the selected footprint,
 * and nothing it does not.
 *
 * The selection is a *physical* thing — an OSM footprint — and this panel is
 * written that way. It always has something to say, because a footprint always
 * exists; whether Energy IQ measures it is a separate question answered
 * further down. An earlier version treated "no Energy IQ building" as "nothing
 * to show", which made two thirds of every campus feel unclickable.
 *
 * Four rules:
 *
 * **Only measured quantities appear.** A field the meter did not report renders
 * as "—". Nothing is defaulted to zero to fill the layout out, and an
 * unmonitored building shows no electrical section at all — 0 kW and "not
 * measured" are different facts.
 *
 * **A value never appears without its age.** Past the telemetry window the
 * block is headed "Última medición" instead of "Medición actual".
 *
 * **A shared footprint exposes every record.** The DIGESET outline carries two
 * Energy IQ buildings; both are listed and either can be opened.
 *
 * **Navigation reuses existing pages.** The actions call `onNavigate`, which
 * the page wires to App.tsx's own `setPage`. No route is invented, and a
 * footprint with nothing to navigate to shows no buttons rather than dead ones.
 */

import { useState } from "react";

import {
  STATUS_META,
  UNIDENTIFIED,
  displayName,
  formatAge,
  formatMoney,
  formatNumber,
  formatTimestamp,
  leadBuilding,
  statusAccent,
} from "./statusModel";
import {
  ACCENT,
  ACCENT_QUIET,
  AMBER,
  BORDER,
  BORDER_SOFT,
  RED,
  SURFACE,
  SURFACE_INNER,
  TEXT,
  TEXT_MUTED,
  TEXT_SECONDARY,
} from "./styles";
import type { FootprintProperties, MapBuilding, PhaseReading } from "./types";

interface Props {
  feature: FootprintProperties | null;
  buildings: MapBuilding[];
  campusName: string | null;
  onNavigate: (page: string) => void;
  onClose: () => void;
}

const LABEL: React.CSSProperties = {
  fontSize: 10,
  color: TEXT_MUTED,
  textTransform: "uppercase",
  letterSpacing: 0.85,
  fontWeight: 600,
};

const SECTION: React.CSSProperties = {
  borderTop: `1px solid ${BORDER_SOFT}`,
  paddingTop: 14,
  marginTop: 14,
};

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12 }}>
      <span style={{ color: TEXT_MUTED }}>{label}</span>
      <span style={{ color: TEXT_SECONDARY, fontVariantNumeric: "tabular-nums", textAlign: "right" }}>
        {value}
      </span>
    </div>
  );
}

function StatusChip({ status }: { status: MapBuilding["map_status"] }) {
  const color = statusAccent(status);
  return (
    <span
      style={{
        background: `${color}14`,
        color,
        border: `1px solid ${color}33`,
        borderRadius: 4,
        padding: "3px 8px",
        fontSize: 11,
        fontWeight: 500,
        whiteSpace: "nowrap",
      }}
    >
      {STATUS_META[status].label.toUpperCase()}
    </span>
  );
}

function PhaseBlock({ name, phase }: { name: string; phase: PhaseReading }) {
  return (
    <div
      style={{
        background: SURFACE_INNER,
        border: `1px solid ${BORDER_SOFT}`,
        borderRadius: 7,
        padding: "10px 12px",
      }}
    >
      <div style={{ ...LABEL, marginBottom: 7, color: ACCENT_QUIET }}>Fase {name}</div>
      <div style={{ display: "grid", gap: 4 }}>
        <Row label="Corriente" value={formatNumber(phase.current, 3, "A")} />
        <Row label="Tensión" value={formatNumber(phase.voltage, 1, "V")} />
        <Row label="Potencia activa" value={formatNumber(phase.power_kw, 3, "kW")} />
        <Row label="Factor de potencia" value={formatNumber(phase.power_factor, 3)} />
      </div>
    </div>
  );
}

/** The open alerts on the measuring node, above the numbers rather than below. */
function AlertBanner({ building }: { building: MapBuilding }) {
  if (building.alerts.open_count === 0) return null;
  const critical = building.map_status === "active_critical";
  const tone = critical ? RED : AMBER;
  return (
    <div
      style={{
        marginTop: 12,
        background: `${tone}10`,
        border: `1px solid ${tone}33`,
        borderLeft: `2px solid ${tone}`,
        borderRadius: 6,
        padding: "10px 12px",
      }}
    >
      <div style={{ ...LABEL, color: tone, marginBottom: 6 }}>
        {building.alerts.max_severity} · {building.alerts.open_count} abierta
        {building.alerts.open_count === 1 ? "" : "s"}
      </div>
      {building.alerts.items.map((alert) => (
        <div key={alert.id} style={{ marginBottom: 5 }}>
          <div style={{ fontSize: 11.5, color: TEXT_SECONDARY, lineHeight: 1.4 }}>{alert.title}</div>
          <div style={{ fontSize: 10.5, color: TEXT_MUTED }}>
            {alert.severity} · {formatTimestamp(alert.created_at)}
          </div>
        </div>
      ))}
    </div>
  );
}

/** One Energy IQ record in full: deployment, freshness, and what it measured. */
function BuildingRecord({
  building,
  onNavigate,
}: {
  building: MapBuilding;
  onNavigate: (page: string) => void;
}) {
  const reading = building.latest_reading;
  const live = building.telemetry.is_live;

  return (
    <>
      <AlertBanner building={building} />

      <div style={SECTION}>
        <div style={{ ...LABEL, marginBottom: 9 }}>Despliegue</div>
        {building.deployment ? (
          <div style={{ display: "grid", gap: 5 }}>
            <Row
              label={building.deployment.is_operational ? "Despliegue activo" : "Último despliegue"}
              value={`#${building.deployment.id} · ${building.deployment.status}`}
            />
            <Row label="Nodo" value={building.deployment.node?.code ?? "—"} />
            <Row label="Tablero" value={building.deployment.panel ?? "—"} />
            <Row
              label="Ventana"
              value={`${building.deployment.start_date} → ${building.deployment.end_date ?? "abierto"}`}
            />
            {building.deployment_count > 1 && (
              <Row label="Campañas en el edificio" value={String(building.deployment_count)} />
            )}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: TEXT_MUTED, lineHeight: 1.55 }}>
            El edificio está registrado en Energy IQ pero nunca ha tenido un despliegue.
          </div>
        )}
      </div>

      <div style={SECTION}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div style={LABEL}>{live ? "Medición actual" : "Última medición"}</div>
          <div style={{ fontSize: 10.5, color: live ? TEXT_MUTED : AMBER }}>
            {formatAge(building.telemetry.age_seconds)}
          </div>
        </div>

        {!live && building.telemetry.last_reading_at && (
          <div
            style={{
              marginTop: 9,
              background: `${AMBER}10`,
              border: `1px solid ${AMBER}33`,
              borderRadius: 6,
              padding: "8px 10px",
              fontSize: 11,
              color: AMBER,
              lineHeight: 1.5,
            }}
          >
            {building.map_status === "active_stale"
              ? `Monitoreo sin datos recientes. El despliegue sigue activo, pero la última lectura quedó fuera de la ventana de telemetría (${building.telemetry.window_seconds} s).`
              : `Sin monitoreo activo. Estos valores son históricos, no el estado actual.`}
          </div>
        )}

        {reading ? (
          <>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit,minmax(110px,1fr))",
                gap: 12,
                marginTop: 13,
              }}
            >
              <div>
                <div style={LABEL}>{live ? "Potencia" : "Potencia (histórica)"}</div>
                <div style={{ fontSize: 20, fontWeight: 600, color: TEXT, marginTop: 3 }}>
                  {formatNumber(reading.power_kw, 2, "kW")}
                </div>
              </div>
              <div>
                <div style={LABEL}>Energía hoy</div>
                <div style={{ fontSize: 20, fontWeight: 600, color: TEXT, marginTop: 3 }}>
                  {formatNumber(building.energy_today_kwh, 3, "kWh")}
                </div>
              </div>
              <div>
                <div style={LABEL}>Costo hoy</div>
                <div style={{ fontSize: 20, fontWeight: 600, color: ACCENT_QUIET, marginTop: 3 }}>
                  {formatMoney(building.cost_today_mxn)}
                </div>
              </div>
            </div>

            <div style={{ display: "grid", gap: 5, marginTop: 14 }}>
              <Row label="Tensión" value={formatNumber(reading.voltage, 1, "V")} />
              <Row label="Corriente" value={formatNumber(reading.current, 3, "A")} />
              <Row label="Potencia aparente" value={formatNumber(reading.apparent_kva, 3, "kVA")} />
              <Row label="Factor de potencia" value={formatNumber(reading.power_factor, 3)} />
              <Row label="Frecuencia" value={formatNumber(reading.frequency_hz, 2, "Hz")} />
              <Row label="Corriente de neutro" value={formatNumber(reading.neutral_current, 3, "A")} />
              <Row label="Marca de tiempo" value={formatTimestamp(reading.timestamp)} />
            </div>

            {reading.phases && (
              <div style={{ display: "grid", gap: 9, marginTop: 14 }}>
                {Object.entries(reading.phases).map(([name, phase]) => (
                  <PhaseBlock key={name} name={name} phase={phase} />
                ))}
              </div>
            )}
          </>
        ) : (
          <div style={{ fontSize: 12, color: TEXT_MUTED, marginTop: 10 }}>
            Sin lecturas de producción para este edificio.
          </div>
        )}
      </div>

      <div style={{ ...SECTION, display: "flex", gap: 8, flexWrap: "wrap" }}>
        {[
          { label: "Ver edificio", page: "buildings" },
          { label: "Monitoreo en vivo", page: "live" },
          { label: "Ver despliegue", page: "deployments" },
        ].map((action) => (
          <button
            key={action.page}
            type="button"
            onClick={() => onNavigate(action.page)}
            style={{
              background: "transparent",
              border: `1px solid ${ACCENT}55`,
              color: ACCENT_QUIET,
              borderRadius: 6,
              padding: "7px 12px",
              fontSize: 11.5,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            {action.label}
          </button>
        ))}
      </div>
    </>
  );
}

/**
 * A footprint OSM knows and Energy IQ does not — the common case on every
 * campus, and the one that must not look like a dead click.
 *
 * It says "sin monitoreo" and shows no electrical section at all. Rendering
 * zeroes here would be a lie of a particular kind: 0 kW is a measurement, and
 * this building has none.
 */
function UnmonitoredRecord({ feature }: { feature: FootprintProperties }) {
  return (
    <>
      <div style={SECTION}>
        <div style={{ ...LABEL, marginBottom: 8 }}>Datos eléctricos</div>
        <div style={{ fontSize: 12.5, color: TEXT_SECONDARY, lineHeight: 1.6 }}>
          Sin despliegue activo. Este edificio aún no está asociado a un punto de monitoreo de
          Energy IQ, así que no hay nodo, despliegue ni mediciones que mostrar.
        </div>
      </div>

      <div style={SECTION}>
        <div style={{ ...LABEL, marginBottom: 9 }}>Huella física</div>
        <div style={{ display: "grid", gap: 5 }}>
          <Row label="Origen" value="OpenStreetMap" />
          <Row label="Identificador" value={`${feature.osm_type}/${feature.osm_id}`} />
          <Row label="Nombre en OSM" value={feature.osm_name ?? "—"} />
          <Row label="Tipo de edificio" value={feature.osm_building ?? "—"} />
          {feature.osm_operator && <Row label="Operador" value={feature.osm_operator} />}
        </div>
      </div>
    </>
  );
}

function EmptyPanel({ message }: { message: string }) {
  return (
    <div
      style={{
        background: SURFACE,
        border: `1px solid ${BORDER}`,
        borderRadius: 12,
        padding: "22px 20px",
        color: TEXT_MUTED,
        fontSize: 12.5,
        lineHeight: 1.6,
      }}
    >
      {message}
    </div>
  );
}

export function BuildingDetailPanel({ feature, buildings, campusName, onNavigate, onClose }: Props) {
  // Which associated record is expanded. Held by id and resolved against the
  // current footprint, so selecting a different building silently falls back to
  // its own lead record instead of needing an effect to reset it.
  const [openId, setOpenId] = useState<number | null>(null);

  if (!feature) {
    return (
      <EmptyPanel message="Selecciona un edificio en el mapa para ver su despliegue, su nodo y sus mediciones eléctricas." />
    );
  }

  const lead = leadBuilding(buildings);
  const active = buildings.find((b) => b.id === openId) ?? lead;
  const title = displayName(feature, buildings);
  const status = active?.map_status ?? feature.map_status;
  const meta = STATUS_META[status];

  return (
    <div
      style={{
        background: SURFACE,
        border: `1px solid ${BORDER}`,
        borderRadius: 12,
        padding: "18px 20px",
        maxHeight: "100%",
        overflowY: "auto",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: TEXT, lineHeight: 1.3 }}>{title}</div>
          {campusName && (
            <div style={{ fontSize: 11.5, color: TEXT_SECONDARY, marginTop: 3 }}>{campusName}</div>
          )}
          {active?.organizational_unit && (
            <div style={{ fontSize: 11.5, color: TEXT_SECONDARY, marginTop: 2 }}>
              {active.organizational_unit}
            </div>
          )}
          <div style={{ fontSize: 10.5, color: TEXT_MUTED, marginTop: 4 }}>
            OSM {feature.osm_type}/{feature.osm_id}
            {feature.osm_name && title !== feature.osm_name ? ` · "${feature.osm_name}"` : ""}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar panel"
          style={{
            background: "transparent",
            border: `1px solid ${BORDER}`,
            color: TEXT_MUTED,
            borderRadius: 6,
            width: 26,
            height: 26,
            cursor: "pointer",
            flexShrink: 0,
            lineHeight: 1,
          }}
        >
          ×
        </button>
      </div>

      <div style={{ marginTop: 12 }}>
        <StatusChip status={status} />
      </div>
      <p style={{ fontSize: 11.5, color: TEXT_MUTED, marginTop: 8, lineHeight: 1.55 }}>
        {meta.description}
      </p>

      {/*
        A footprint shared by several Energy IQ buildings — the DIGESET outline
        holds two. Listing them is not decoration: one is a live campaign and
        the other a closed one, and collapsing that to a single record would
        hide whichever was curated second.
      */}
      {buildings.length > 1 && (
        <div style={SECTION}>
          <div style={{ ...LABEL, marginBottom: 9 }}>
            {buildings.length} registros Energy IQ en esta huella
          </div>
          <div style={{ display: "grid", gap: 7 }}>
            {buildings.map((building) => {
              const open = building.id === active?.id;
              return (
                <button
                  key={building.id}
                  type="button"
                  onClick={() => setOpenId(building.id)}
                  aria-pressed={open}
                  style={{
                    textAlign: "left",
                    background: open ? SURFACE_INNER : "transparent",
                    border: `1px solid ${open ? statusAccent(building.map_status) + "55" : BORDER_SOFT}`,
                    borderLeft: `2px solid ${statusAccent(building.map_status)}`,
                    borderRadius: 6,
                    padding: "9px 11px",
                    cursor: "pointer",
                    display: "grid",
                    gap: 4,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: TEXT }}>
                      {building.name}
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        color: statusAccent(building.map_status),
                        whiteSpace: "nowrap",
                      }}
                    >
                      {STATUS_META[building.map_status].short}
                    </span>
                  </div>
                  <div style={{ fontSize: 10.5, color: TEXT_MUTED }}>
                    {building.deployment
                      ? `Despliegue #${building.deployment.id} · ${building.deployment.node?.code ?? "sin nodo"}`
                      : "Sin despliegue"}
                    {" · "}
                    {building.telemetry.is_live
                      ? formatNumber(building.latest_reading?.power_kw ?? null, 2, "kW")
                      : formatAge(building.telemetry.age_seconds)}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {active ? (
        <BuildingRecord building={active} onNavigate={onNavigate} />
      ) : (
        <UnmonitoredRecord feature={feature} />
      )}
    </div>
  );
}

export { UNIDENTIFIED };
