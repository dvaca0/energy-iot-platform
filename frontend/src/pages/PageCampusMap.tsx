/**
 * Mapa de Campus — the geographic view of Universidad de Colima's electrical
 * monitoring.
 *
 * Composition only. The page holds selection and mode state and wires the
 * pieces together; every rule it appears to apply lives in a module of its own:
 *
 *   useCampusMap      fetching, campus choice, polling
 *   statusModel       colour, freshness wording, number formatting
 *   geometry          GeoJSON ⇄ Leaflet coordinates
 *   CampusEnergyMap   the only file that imports Leaflet
 *
 * Campus totals come from `/api/metrics/campuses`, the platform's existing
 * definition, and are shown as a strip above the map rather than as the cards
 * that used to be the whole page. The map is the page now; the numbers frame it.
 */

import { Suspense, lazy, useMemo, useState } from "react";

import { BuildingDetailPanel } from "../components/campusmap/BuildingDetailPanel";
import { CampusSelector } from "../components/campusmap/CampusSelector";
import { MapLegend } from "../components/campusmap/MapLegend";
import { MapModeSelector } from "../components/campusmap/MapModeSelector";
import { buildRamp, formatMoney, formatNumber, modeValue } from "../components/campusmap/statusModel";
import {
  ACCENT_QUIET,
  AMBER,
  BORDER,
  BORDER_SOFT,
  SURFACE,
  SURFACE_INNER,
  TEXT,
  TEXT_MUTED,
} from "../components/campusmap/styles";
import { makeSelection, resolveSelection } from "../components/campusmap/selection";
import type { MapSelection } from "../components/campusmap/selection";
import { useCampusMap } from "../components/campusmap/useCampusMap";
import type { MapMode, MapStatus } from "../components/campusmap/types";
import "../components/campusmap/campusMap.css";

const MODES: MapMode[] = ["status", "power", "energy", "cost", "power_factor"];

/**
 * Leaflet is loaded on demand, not with the app.
 *
 * It touches `window` at module scope, so a static import would execute it
 * anywhere the module graph is evaluated without a DOM — which is exactly what
 * `tests/render-insights.tsx` does when it pulls a component out of `App.tsx`.
 * Deferring it keeps every other page renderable in Node, and keeps ~150 kB of
 * mapping code out of the initial bundle for the users who never open this page.
 */
const CampusEnergyMap = lazy(() =>
  import("../components/campusmap/CampusEnergyMap").then((module) => ({
    default: module.CampusEnergyMap,
  })),
);

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div
      style={{
        background: SURFACE_INNER,
        border: `1px solid ${BORDER_SOFT}`,
        borderRadius: 8,
        padding: "12px 14px",
        minWidth: 132,
        flex: "1 1 132px",
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: TEXT_MUTED,
          textTransform: "uppercase",
          letterSpacing: 0.85,
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 19,
          fontWeight: 600,
          color: tone ?? TEXT,
          marginTop: 5,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function Notice({ children, tone = TEXT_MUTED }: { children: React.ReactNode; tone?: string }) {
  return (
    <div
      style={{
        background: SURFACE,
        border: `1px solid ${BORDER}`,
        borderRadius: 12,
        padding: "26px 24px",
        color: tone,
        fontSize: 13,
        lineHeight: 1.65,
      }}
    >
      {children}
    </div>
  );
}

export default function PageCampusMap({ setPage }: { setPage?: (page: string) => void }) {
  const { campuses, campusId, setCampusId, payload, metrics, loading, error } = useCampusMap();
  const [requestedMode, setRequestedMode] = useState<MapMode>("status");

  // A selection belongs to a campus, so it is stored with one and read back
  // only for the campus in view — see `selection.ts` for why that is derived
  // rather than reset from an effect, and why the identity is the OSM feature
  // rather than an Energy IQ building.
  const [selection, setSelection] = useState<MapSelection | null>(null);
  const selectedId = resolveSelection(selection, campusId);
  const setSelectedId = (featureId: string | null) =>
    setSelection(makeSelection(featureId, campusId));

  const features = useMemo(() => payload?.geometry?.features ?? [], [payload]);
  const buildings = useMemo(() => payload?.buildings ?? [], [payload]);

  const buildingsById = useMemo(
    () => new Map(buildings.map((building) => [building.id, building])),
    [buildings],
  );

  const availability = useMemo(() => {
    const out = {} as Record<MapMode, boolean>;
    for (const candidate of MODES) {
      out[candidate] =
        candidate === "status" ||
        buildings.some((building) => modeValue(building, candidate) !== null);
    }
    return out;
  }, [buildings]);

  // A mode can stop being available when the campus changes under it. Falling
  // back here — rather than resetting the state from an effect — means the map
  // never renders one frame on a mode this campus has no data for.
  const mode: MapMode = availability[requestedMode] ? requestedMode : "status";

  const valueByFeature = useMemo(() => {
    const map = new Map<string, number | null>();
    for (const feature of features) {
      const linked = feature.properties.energy_iq_building_ids
        .map((id) => buildingsById.get(id))
        .filter(Boolean);
      // One footprint, several buildings: the polygon shows their sum for
      // additive quantities and the first available value otherwise, because a
      // power factor is not a thing you can add up.
      const values = linked
        .map((building) => modeValue(building!, mode))
        .filter((v): v is number => v !== null);
      if (values.length === 0) {
        map.set(feature.id, null);
      } else if (mode === "power_factor") {
        map.set(feature.id, values[0]);
      } else {
        map.set(feature.id, values.reduce((sum, v) => sum + v, 0));
      }
    }
    return map;
  }, [features, buildingsById, mode]);

  const ramp = useMemo(() => {
    if (mode === "status") return null;
    return buildRamp([...valueByFeature.values()].filter((v): v is number => v !== null));
  }, [valueByFeature, mode]);

  const statusCounts = useMemo(() => {
    const counts: Partial<Record<MapStatus, number>> = {};
    for (const feature of features) {
      const status = feature.properties.map_status;
      counts[status] = (counts[status] ?? 0) + 1;
    }
    return counts;
  }, [features]);

  const selectedFeature = features.find((feature) => feature.id === selectedId) ?? null;
  const selectedBuildings = selectedFeature
    ? selectedFeature.properties.energy_iq_building_ids
        .map((id) => buildingsById.get(id))
        .filter((b): b is NonNullable<typeof b> => Boolean(b))
    : [];

  const liveCount = buildings.filter((b) => b.telemetry.is_live).length;
  const openAlerts = buildings.reduce((sum, b) => sum + b.alerts.open_count, 0);
  const unmapped = payload?.unmapped_building_ids ?? [];

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div
        style={{
          background: SURFACE,
          border: `1px solid ${BORDER}`,
          borderRadius: 12,
          padding: "16px 20px",
          display: "flex",
          flexWrap: "wrap",
          gap: 16,
          alignItems: "flex-start",
          justifyContent: "space-between",
        }}
      >
        <CampusSelector campuses={campuses} value={campusId} onChange={setCampusId} />
        <MapModeSelector value={mode} onChange={setRequestedMode} availability={availability} />
      </div>

      {metrics && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Metric
            label="Edificios monitoreados"
            value={`${metrics.monitored_buildings}/${metrics.total_buildings}`}
          />
          <Metric label="Con datos en vivo" value={String(liveCount)} />
          <Metric label="Potencia del campus" value={formatNumber(metrics.power_kw, 2, "kW")} />
          <Metric label="Energía hoy" value={formatNumber(metrics.energy_today_kwh, 3, "kWh")} />
          <Metric label="Costo hoy" value={formatMoney(metrics.cost_today_mxn)} tone={ACCENT_QUIET} />
          <Metric
            label="Alertas abiertas"
            value={String(openAlerts)}
            tone={openAlerts > 0 ? AMBER : undefined}
          />
        </div>
      )}

      {error && <Notice tone={AMBER}>{error}</Notice>}

      {loading && !payload && <Notice>Cargando el mapa del campus…</Notice>}

      {payload && !payload.view.has_geometry && (
        <Notice>
          <strong style={{ color: TEXT }}>{payload.campus.name}</strong> todavía no tiene huellas de
          edificio trazadas. Sus edificios y mediciones siguen disponibles en el resto de la
          plataforma; para dibujarlo, agrega su bbox en <code>campuses.json</code> y ejecuta{" "}
          <code>scripts/build_campus_geojson.py</code>. Consulta{" "}
          <code>docs/CampusMap.md</code>.
        </Notice>
      )}

      {payload && payload.view.has_geometry && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) minmax(0, 340px)",
            gap: 16,
            alignItems: "start",
          }}
          className="campus-map-shell"
        >
          <div style={{ display: "grid", gap: 12, minWidth: 0 }}>
            <Suspense fallback={<Notice>Cargando el mapa…</Notice>}>
              <CampusEnergyMap
                features={features}
                buildingsById={buildingsById}
                mode={mode}
                ramp={ramp}
                valueByFeature={valueByFeature}
                grounds={payload.grounds}
                selectedId={selectedId}
                onSelect={setSelectedId}
                fitKey={String(payload.campus.id)}
                fallbackCenter={payload.view.fallback_center}
                fallbackZoom={payload.view.fallback_zoom}
              />
            </Suspense>

            <div style={{ maxWidth: 360 }}>
              <MapLegend mode={mode} ramp={ramp} counts={statusCounts} />
            </div>

            {/*
              Two notices about *this map*, shown only when they apply. The
              platform-level counts and the telemetry window that used to sit
              here are technical metadata about the whole deployment, not about
              the campus on screen — they live on Infraestructura now. What
              stays is what a reader of this map cannot work out by looking at
              it: why a campus is empty, and which buildings have data but
              nowhere to draw it.
            */}
            {features.length === 0 && (
              <div style={{ fontSize: 11.5, color: AMBER, lineHeight: 1.6 }}>
                OpenStreetMap aún no tiene edificios trazados dentro de este predio. El contorno del
                campus sí está mapeado y es lo que se muestra.
              </div>
            )}
            {unmapped.length > 0 && (
              <div style={{ fontSize: 11.5, color: TEXT_MUTED, lineHeight: 1.6 }}>
                Sin ubicar en el mapa:{" "}
                {unmapped.map((id) => buildingsById.get(id)?.name ?? `#${id}`).join(", ")}. Sus datos
                existen; falta la asociación con una huella del mapa.
              </div>
            )}
          </div>

          <BuildingDetailPanel
            feature={selectedFeature?.properties ?? null}
            buildings={selectedBuildings}
            campusName={payload.campus.name}
            onNavigate={(page) => setPage?.(page)}
            onClose={() => setSelectedId(null)}
          />
        </div>
      )}
    </div>
  );
}
