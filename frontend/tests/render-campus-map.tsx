/**
 * Checks for the Campus Map's data-association and status logic.
 *
 * Two halves, following `render-live-monitor.tsx`.
 *
 * The **pure** half exercises the rules that decide what an operator sees:
 * which colour a footprint gets, whether a reading is presented as current,
 * how a GeoJSON ring becomes Leaflet coordinates, and what a magnitude mode
 * refuses to plot. These are the assertions worth freezing, because every one
 * of them is a way the map could lie — a stale number shown as live, a busy
 * building shown as faulty, a footprint drawn in the Indian Ocean.
 *
 * The **render** half renders the presentational components against payload
 * shapes the backend really produces, including the awkward ones: a footprint
 * with no Energy IQ building behind it, a building whose meter reports no
 * phases, and two Energy IQ buildings sharing one physical outline.
 *
 * Leaflet is deliberately absent. It needs a DOM and `renderToStaticMarkup`
 * has none, which is exactly why the module keeps map-specific code in
 * `CampusEnergyMap`/`BuildingGeoJsonLayer` and everything else outside it.
 * Those two files are covered by the visual review on :5175.
 */
import { renderToStaticMarkup } from "react-dom/server";

import { GeographicCoverage } from "../src/App";

import { BuildingDetailPanel } from "../src/components/campusmap/BuildingDetailPanel";
import { BuildingTooltip } from "../src/components/campusmap/BuildingTooltip";
import { CampusSelector } from "../src/components/campusmap/CampusSelector";
import { MapLegend } from "../src/components/campusmap/MapLegend";
import { MapModeSelector } from "../src/components/campusmap/MapModeSelector";
import {
  campusBounds,
  collectionBounds,
  featureCentroid,
  featureRings,
  groundsRings,
  ringCentroid,
} from "../src/components/campusmap/geometry";
import { makeSelection, resolveSelection } from "../src/components/campusmap/selection";
import type { MapSelection } from "../src/components/campusmap/selection";
import {
  STATUS_META,
  UNIDENTIFIED,
  buildRamp,
  displayName,
  formatAge,
  formatNumber,
  leadBuilding,
  modeValue,
  polygonStyle,
  rampColor,
} from "../src/components/campusmap/statusModel";
import type {
  CampusOption,
  Footprint,
  MapBuilding,
  MapMode,
  MapStatus,
} from "../src/components/campusmap/types";

let failures = 0;
let checks = 0;

function check(name: string, condition: boolean, detail = "") {
  checks += 1;
  if (condition) {
    process.stdout.write(`  ok    ${name}\n`);
  } else {
    failures += 1;
    process.stdout.write(`  FAIL  ${name}${detail ? ` — ${detail}` : ""}\n`);
  }
}

function renderOrFail(name: string, node: React.ReactElement): string {
  try {
    const html = renderToStaticMarkup(node);
    check(name, html.length > 0, "rendered empty");
    return html;
  } catch (error) {
    failures += 1;
    checks += 1;
    process.stdout.write(`  FAIL  ${name} — THREW ${(error as Error).message}\n`);
    return "";
  }
}

// ------------------------------------------------------------------- fixtures
/** Shaped exactly like `/api/campus-map/7` returns for building 10. */
const LIVE_BUILDING: MapBuilding = {
  id: 10,
  code: "B-MANUAL-71-edificio-principal-2.0",
  name: "Edificio Principal 2.0",
  campus_id: 7,
  campus: "Campus Central",
  organizational_unit: "DIGESET",
  is_placeholder: false,
  map_status: "active_critical",
  deployment: {
    id: 7,
    status: "active",
    is_operational: true,
    start_date: "2026-08-13",
    end_date: "2026-08-22",
    activated_at: "2026-08-13T14:17:54.444005",
    closed_at: null,
    panel: "SITE",
    node: {
      id: 1,
      code: "N001",
      name: "Edge Node 001",
      measurement_context: "production",
      commission_state: "commissioned",
    },
  },
  deployment_count: 1,
  telemetry: {
    last_reading_at: "2026-08-18T23:47:37.804000",
    age_seconds: 64.9,
    is_live: true,
    window_seconds: 300,
  },
  latest_reading: {
    timestamp: "2026-08-18T23:47:37.804000",
    power_kw: 12.733312,
    voltage: 124.3,
    current: 107.814,
    apparent_kva: 13.414138,
    power_factor: 0.9492455,
    frequency_hz: 60,
    neutral_current: null,
    context: "production",
    phases: {
      A: { voltage: 123.6, current: 38.503, power_kw: 4.7097, apparent_kva: 4.7638, power_factor: 0.99, frequency_hz: 60 },
      B: { voltage: 124.8, current: 35.662, power_kw: 4.3985, apparent_kva: 4.4574, power_factor: 0.99, frequency_hz: 60 },
      C: { voltage: 124.5, current: 33.649, power_kw: 3.625, apparent_kva: 4.1929, power_factor: 0.86, frequency_hz: 60 },
    },
  },
  energy_today_kwh: 168.4213,
  cost_today_mxn: 421.9,
  alerts: {
    open_count: 1,
    max_severity: "EMERGENCY",
    items: [
      {
        id: 683,
        alert_id: "ALT-20260814-1234",
        severity: "EMERGENCY",
        title: "Node N001 reports undervoltage",
        created_at: "2026-08-14T21:58:17.194693",
      },
    ],
  },
};

/** Building 9: a closed campaign whose newest reading is twelve days old. */
const HISTORICAL_BUILDING: MapBuilding = {
  ...LIVE_BUILDING,
  id: 9,
  code: "B-MANUAL-60-edificio-principal-prueba",
  name: "Edificio Principal Prueba",
  organizational_unit: "Dirección General de Servicios Telemáticos",
  map_status: "historical",
  deployment: {
    ...LIVE_BUILDING.deployment!,
    id: 6,
    status: "completed",
    is_operational: false,
    end_date: "2026-08-07",
    closed_at: "2026-08-03T21:57:09.413981",
    panel: "Centro de Datos",
  },
  telemetry: {
    last_reading_at: "2026-08-06T14:18:53.993000",
    age_seconds: 1071006.4,
    is_live: false,
    window_seconds: 300,
  },
  latest_reading: {
    timestamp: "2026-08-06T14:18:53.993000",
    power_kw: 0,
    voltage: 130.5,
    current: 0.08,
    apparent_kva: null,
    power_factor: 0,
    frequency_hz: 60,
    neutral_current: null,
    context: "production",
    // A meter that reports no per-phase breakdown at all.
    phases: null,
  },
  energy_today_kwh: 0,
  cost_today_mxn: 0,
  alerts: { open_count: 0, max_severity: null, items: [] },
};

const MAPPED_FEATURE: Footprint = {
  type: "Feature",
  id: "way/625447870",
  properties: {
    osm_type: "way",
    osm_id: 625447870,
    osm_name: "Servicios Telemáticos",
    osm_building: "university",
    osm_operator: null,
    energy_iq_building_ids: [10, 9],
    map_status: "active_critical",
    association_confidence: "inferred",
  },
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [-103.699, 19.248],
        [-103.698, 19.248],
        [-103.698, 19.249],
        [-103.699, 19.249],
        [-103.699, 19.248],
      ],
    ],
  },
};

/** A real OSM footprint with no name and nothing in Energy IQ behind it. */
const BARE_FEATURE: Footprint = {
  type: "Feature",
  id: "way/1150811090",
  properties: {
    osm_type: "way",
    osm_id: 1150811090,
    osm_name: null,
    osm_building: "yes",
    osm_operator: null,
    energy_iq_building_ids: [],
    map_status: "unregistered",
    association_confidence: null,
  },
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [-103.702, 19.245],
        [-103.7015, 19.245],
        [-103.7015, 19.2455],
        [-103.702, 19.2455],
        [-103.702, 19.245],
      ],
    ],
  },
};

const CAMPUSES: CampusOption[] = [
  {
    id: 7,
    name: "Campus Central",
    location: "Campus Central, Colima, México",
    delegation: "Colima",
    has_geometry: true,
    footprint_count: 130,
    energy_iq_buildings: 2,
    mapped_buildings: 2,
  },
  {
    id: 6,
    name: "Campus Tecomán",
    location: null,
    delegation: "Tecomán",
    has_geometry: false,
    footprint_count: 0,
    energy_iq_buildings: 0,
    mapped_buildings: 0,
  },
];

// ----------------------------------------------------------------- pure rules
function geometryChecks() {
  process.stdout.write("\nGeoJSON → Leaflet\n");

  const rings = featureRings(MAPPED_FEATURE);
  check("a polygon yields one ring", rings.length === 1);
  check(
    "positions are swapped to [lat, lng], not left as [lon, lat]",
    rings[0][0][0] === 19.248 && rings[0][0][1] === -103.699,
    JSON.stringify(rings[0][0]),
  );

  const centre = featureCentroid(MAPPED_FEATURE);
  check(
    "the centroid lands inside the footprint",
    centre !== null && centre[0] > 19.248 && centre[0] < 19.249 && centre[1] < -103.698,
    JSON.stringify(centre),
  );

  const bounds = collectionBounds([MAPPED_FEATURE, BARE_FEATURE]);
  check(
    "bounds span every feature",
    bounds !== null && bounds[0][0] === 19.245 && bounds[1][0] === 19.249,
    JSON.stringify(bounds),
  );
  check("bounds of nothing are null, not [0,0]", collectionBounds([]) === null);

  const multi: Footprint = {
    ...MAPPED_FEATURE,
    geometry: { type: "MultiPolygon", coordinates: [MAPPED_FEATURE.geometry.coordinates] },
  } as Footprint;
  check("a multipolygon yields its rings too", featureRings(multi).length === 1);
}

/**
 * The shoelace arithmetic, at the coordinates it runs at.
 *
 * A centroid test around the origin proves nothing about this dataset. Near
 * 19.2 N, 103.7 W the untranslated form cancels eleven of a double's sixteen
 * digits and returns noise, which put building labels hundreds of metres from
 * their buildings. Every case below is anchored at Colima; each one fails on
 * the untranslated implementation.
 */
function centroidChecks() {
  process.stdout.write("\nCentroid arithmetic at Colima's coordinates\n");

  const square = (lat: number, lng: number, metres: number) => {
    const dLat = metres / 111320;
    const dLng = dLat / Math.cos((lat * Math.PI) / 180);
    return [
      [lat, lng],
      [lat, lng + dLng],
      [lat + dLat, lng + dLng],
      [lat + dLat, lng],
      [lat, lng],
    ] as [number, number][];
  };

  for (const size of [5, 20, 100]) {
    const ring = square(19.2478, -103.6993, size);
    const centre = ringCentroid(ring);
    const offset = centre
      ? Math.hypot(
          (centre[0] - (ring[0][0] + ring[2][0]) / 2) * 111320,
          (centre[1] - (ring[0][1] + ring[1][1]) / 2) * 111320 * Math.cos((19.2478 * Math.PI) / 180),
        )
      : Infinity;
    check(`a ${size} m square's centroid is its centre, to the millimetre`, offset < 0.001, `${offset.toFixed(3)} m off`);
  }

  const collapsed: [number, number][] = [
    [19.2478, -103.6993],
    [19.2478, -103.6993],
    [19.2478, -103.6993],
    [19.2478, -103.6993],
  ];
  const fallback = ringCentroid(collapsed);
  check(
    "a collapsed ring yields the vertex mean, never NaN",
    fallback !== null && Number.isFinite(fallback[0]) && Number.isFinite(fallback[1]),
  );
  check("a ring with fewer than three points has no centroid", ringCentroid([[19, -103]]) === null);
}

/** The campus outline: its own layer, and part of what the viewport frames. */
function groundsChecks() {
  process.stdout.write("\nCampus outline\n");

  const grounds = [
    [
      [-103.7005, 19.2465],
      [-103.6975, 19.2465],
      [-103.6975, 19.2495],
      [-103.7005, 19.2495],
      [-103.7005, 19.2465],
    ],
  ];

  const rings = groundsRings(grounds);
  check("the outline is swapped to [lat, lng] like everything else", rings[0][0][0] === 19.2465 && rings[0][0][1] === -103.7005);
  check("no outline yields no rings", groundsRings(null).length === 0);

  const withBoth = campusBounds([MAPPED_FEATURE], grounds);
  check(
    "the viewport frames the outline as well as the buildings",
    withBoth !== null && withBoth[0][0] === 19.2465 && withBoth[1][1] === -103.6975,
    JSON.stringify(withBoth),
  );

  // Campus 4 (Santiago) is exactly this: a real, identified campus whose
  // buildings OpenStreetMap has not traced. Fitting to its footprints alone
  // would leave the map pointing at nothing.
  const outlineOnly = campusBounds([], grounds);
  check(
    "a campus with no traced buildings still has bounds, from its outline",
    outlineOnly !== null && outlineOnly[0][0] === 19.2465 && outlineOnly[1][0] === 19.2495,
  );
  check("a campus with neither has no bounds, and the caller falls back", campusBounds([], null) === null);
  check(
    "buildings alone still work when no outline was curated",
    campusBounds([MAPPED_FEATURE], null) !== null,
  );
}

function statusChecks() {
  process.stdout.write("\nStatus, freshness and magnitude\n");

  // The distinction the whole page exists for.
  check(
    "a critical building is red, a healthy one green",
    STATUS_META.active_critical.color === "#ef4444" && STATUS_META.active_healthy.color === "#22c55e",
  );
  check(
    "an active deployment without fresh data is not drawn as healthy",
    STATUS_META.active_stale.color !== STATUS_META.active_healthy.color,
  );
  check(
    "a historical building is not drawn as healthy either",
    STATUS_META.historical.color !== STATUS_META.active_healthy.color,
  );
  check(
    "an unregistered footprint is the least prominent thing on the map",
    STATUS_META.unregistered.fillOpacity < STATUS_META.active_healthy.fillOpacity &&
      STATUS_META.unregistered.weight < STATUS_META.registered.weight,
  );

  // Magnitude must never be read off a stale building.
  check("a live building reports its power", modeValue(LIVE_BUILDING, "power") === 12.733312);
  check(
    "a stale building reports no current power, rather than an old number",
    modeValue(HISTORICAL_BUILDING, "power") === null,
  );
  check(
    "a stale building reports no current power factor either",
    modeValue(HISTORICAL_BUILDING, "power_factor") === null,
  );
  check("today's energy comes through", modeValue(LIVE_BUILDING, "energy") === 168.4213);
  check(
    "a building with no energy today contributes nothing to the ramp",
    modeValue(HISTORICAL_BUILDING, "energy") === null,
  );

  const ramp = buildRamp([4, 12.7, 40]);
  check("a ramp spans the real minimum and maximum", ramp?.min === 4 && ramp?.max === 40);
  check("no values means no ramp", buildRamp([]) === null);
  check(
    "a single value sits at the top of the ramp rather than dividing by zero",
    rampColor(12, buildRamp([12])) === ramp?.stops[ramp.stops.length - 1],
  );
  check("a null value has no ramp colour", rampColor(null, ramp) === null);
  check(
    "the magnitude ramp carries no red end to be misread as a fault",
    (ramp?.stops ?? []).every((stop) => stop !== STATUS_META.active_critical.color),
  );

  // Colour is a pure function of the four inputs.
  const critical = polygonStyle({
    status: "active_critical",
    mode: "status",
    value: null,
    ramp: null,
    selected: false,
    hovered: false,
  });
  check("STATUS mode paints the semantic colour", critical.fillColor === "#ef4444");

  const selected = polygonStyle({
    status: "active_critical",
    mode: "status",
    value: null,
    ramp: null,
    selected: true,
    hovered: false,
  });
  check(
    "selection outlines in Energy IQ blue without overwriting the status fill",
    selected.color === "#3b82f6" && selected.fillColor === "#ef4444",
  );

  const unmeasured = polygonStyle({
    status: "active_healthy",
    mode: "power",
    value: null,
    ramp,
    selected: false,
    hovered: false,
  });
  check(
    "a footprint with no value in a magnitude mode is dashed, not painted as the minimum",
    unmeasured.dashArray !== undefined,
  );

  // Freshness wording.
  check("seconds read as seconds", formatAge(45) === "hace 45 s");
  check("minutes read as minutes", formatAge(300) === "hace 5 min");
  check("twelve days read as days", formatAge(1071006) === "hace 12 d");
  check("no reading says so", formatAge(null) === "sin lecturas");

  // Absent is not zero.
  check("null renders as an em dash", formatNumber(null) === "—");
  check("undefined renders as an em dash", formatNumber(undefined) === "—");
  check("zero renders as zero", formatNumber(0, 2) === "0.00");
}

// --------------------------------------------------------------------- render
function renderChecks() {
  process.stdout.write("\nComponent rendering\n");

  const panel = (
    feature: Footprint["properties"] | null,
    buildings: MapBuilding[],
    campusName: string | null = "Campus Central",
  ) => (
    <BuildingDetailPanel
      feature={feature}
      buildings={buildings}
      campusName={campusName}
      onNavigate={() => {}}
      onClose={() => {}}
    />
  );

  // --- the placeholder, and only when nothing is selected ------------------
  const empty = renderOrFail("panel · nothing selected", panel(null, []));
  check("the empty panel prompts a selection", empty.includes("Selecciona un edificio"));

  // --- CASE A: a footprint Energy IQ does not monitor ----------------------
  // The commonest case on every campus, and the one that used to look like a
  // dead click. It must produce a real panel.
  const bare = renderOrFail("panel · unmonitored footprint", panel(BARE_FEATURE.properties, []));
  check("the placeholder is gone once something is selected", !bare.includes("Selecciona un edificio"));
  check("an unmonitored building says so", bare.includes("SIN MONITOREO"));
  check("it explains there is no monitoring point", bare.includes("no está asociado"));
  check("it names the electrical section as absent, not zero", bare.includes("Sin despliegue activo"));
  check("it shows no fabricated power", !bare.includes("kW"));
  check("it shows no fabricated cost", !bare.includes("MXN"));
  check("it still shows the campus", bare.includes("Campus Central"));
  check("it surfaces the OSM identity", bare.includes("way/1150811090"));
  check("it surfaces the OSM building type", bare.includes("yes"));
  check("it offers no dead navigation buttons", !bare.includes("Monitoreo en vivo"));

  // --- CASE B: an unnamed footprint ---------------------------------------
  check("an unnamed, unassociated footprint falls back to a restrained name", bare.includes(UNIDENTIFIED));
  check("and never renders undefined", !bare.includes("undefined"));
  const named = renderOrFail(
    "panel · named but unmonitored footprint",
    panel({ ...BARE_FEATURE.properties, osm_name: "Facultad de Telemática" }, []),
  );
  check("a named footprint uses its OSM name", named.includes("Facultad de Telemática"));
  check("and is not called unidentified", !named.includes(UNIDENTIFIED));
  // The two states are orthogonal: this footprint has a name and no
  // monitoring, and the panel must say exactly that and nothing else.
  check(
    "unidentified and unmonitored stay separate concepts",
    named.includes("SIN MONITOREO") && !named.includes(UNIDENTIFIED),
  );

  // --- CASE D: active and fresh -------------------------------------------
  const live = renderOrFail(
    "panel · live critical building",
    panel(MAPPED_FEATURE.properties, [LIVE_BUILDING, HISTORICAL_BUILDING]),
  );
  check("the institutional name wins over the OSM name", live.includes("Edificio Principal 2.0"));
  check("the OSM identity is still shown, as identity", live.includes("way/625447870"));
  check("the node is named", live.includes("N001"));
  check("the deployment is named", live.includes("#7"));
  check("all three phases are broken out", live.includes("Fase A") && live.includes("Fase B") && live.includes("Fase C"));
  check("a live reading is labelled current", live.includes("Medición actual"));
  check("the live power is shown", live.includes("12.73"));
  check("energy today is shown", live.includes("168.421"));
  check("cost today is shown", live.includes("MXN"));
  check(
    "navigation reuses existing pages",
    live.includes("Ver edificio") && live.includes("Monitoreo en vivo") && live.includes("Ver despliegue"),
  );

  // --- CASE F: an open alert, above the numbers ---------------------------
  check("the critical status is stated", live.includes("CRÍTICO"));
  check("the open alert is surfaced", live.includes("Node N001 reports undervoltage"));
  check("its severity is the monitoring system's own", live.includes("EMERGENCY"));
  check(
    "the alert appears before the electrical detail, not buried under it",
    live.indexOf("Node N001 reports undervoltage") < live.indexOf("Fase A"),
  );

  // --- CASE G: two Energy IQ records on one footprint ----------------------
  check("the footprint says how many records it carries", live.includes("2 registros Energy IQ"));
  check("both records are listed", live.includes("Edificio Principal 2.0") && live.includes("Edificio Principal Prueba"));
  check("each record shows its own state", live.includes("Histórico") && live.includes("Crítico"));
  check("each record shows its own deployment", live.includes("Despliegue #7") && live.includes("Despliegue #6"));
  check(
    "the most urgent record leads, so panel and polygon colour agree",
    leadBuilding([HISTORICAL_BUILDING, LIVE_BUILDING])?.id === LIVE_BUILDING.id,
  );

  // --- CASE C: historical only --------------------------------------------
  const stale = renderOrFail(
    "panel · historical building",
    panel({ ...MAPPED_FEATURE.properties, energy_iq_building_ids: [9] }, [HISTORICAL_BUILDING]),
  );
  check("a historical building is named as such", stale.includes("DATOS HISTÓRICOS"));
  check("a stale reading is never labelled current", !stale.includes("Medición actual"));
  check("it is labelled as the last measurement instead", stale.includes("Última medición"));
  check("its power is marked historical rather than current", stale.includes("Potencia (histórica)"));
  check("its age is stated", stale.includes("hace 12 d"));
  check("it names the closed deployment", stale.includes("Último despliegue"));
  check("a meter reporting no phases shows none", !stale.includes("Fase A"));
  check("it still offers navigation into the platform", stale.includes("Ver edificio"));

  // --- CASE E: active but stale -------------------------------------------
  const staleActive = renderOrFail(
    "panel · active deployment with no recent data",
    panel({ ...MAPPED_FEATURE.properties, energy_iq_building_ids: [11] }, [
      {
        ...LIVE_BUILDING,
        id: 11,
        map_status: "active_stale",
        telemetry: { ...LIVE_BUILDING.telemetry, age_seconds: 7200, is_live: false },
        alerts: { open_count: 0, max_severity: null, items: [] },
      },
    ]),
  );
  check("a stale campaign is visibly different from a healthy one", staleActive.includes("Monitoreo sin datos recientes"));
  check("it still names its deployment", staleActive.includes("#7"));
  check("it still names its node", staleActive.includes("N001"));
  check("it reports how long since the last reading", staleActive.includes("hace 2 h"));
  check("it does not claim the reading is current", !staleActive.includes("Medición actual"));
  check("and marks the power as historical", staleActive.includes("Potencia (histórica)"));

  // --- tooltips ------------------------------------------------------------
  const tooltip = renderOrFail(
    "tooltip · live building",
    <BuildingTooltip feature={MAPPED_FEATURE.properties} buildings={[LIVE_BUILDING, HISTORICAL_BUILDING]} />,
  );
  check("the tooltip shows power", tooltip.includes("12.73"));
  check("the tooltip states the state, not just that it is monitored", tooltip.includes("Crítico"));
  check("the tooltip flags a shared footprint", tooltip.includes("2 edificios"));

  const healthyTooltip = renderOrFail(
    "tooltip · healthy building",
    <BuildingTooltip
      feature={{ ...MAPPED_FEATURE.properties, map_status: "active_healthy" }}
      buildings={[{ ...LIVE_BUILDING, map_status: "active_healthy" }]}
    />,
  );
  check("a healthy live building reads as monitored", healthyTooltip.includes("Monitoreo activo"));

  const bareTooltip = renderOrFail(
    "tooltip · unmonitored footprint",
    <BuildingTooltip feature={BARE_FEATURE.properties} buildings={[]} />,
  );
  check("an unmonitored footprint says so", bareTooltip.includes("Sin monitoreo"));
  check("and shows no electrical value", !bareTooltip.includes("kW"));
  check("and uses the same unidentified fallback as the panel", bareTooltip.includes(UNIDENTIFIED));

  const staleTooltip = renderOrFail(
    "tooltip · stale building",
    <BuildingTooltip
      feature={{ ...MAPPED_FEATURE.properties, energy_iq_building_ids: [9] }}
      buildings={[HISTORICAL_BUILDING]}
    />,
  );
  check("a stale building shows no live power in the tooltip", !staleTooltip.includes("kW"));

  // --- name resolution -----------------------------------------------------
  check(
    "the Energy IQ name outranks the OSM name",
    displayName(MAPPED_FEATURE.properties, [LIVE_BUILDING]) === "Edificio Principal 2.0",
  );
  check(
    "the OSM name is used when there is no Energy IQ building",
    displayName(MAPPED_FEATURE.properties, []) === "Servicios Telemáticos",
  );
  check("neither means unidentified", displayName(BARE_FEATURE.properties, []) === UNIDENTIFIED);
  check("a blank OSM name is not a name", displayName({ osm_name: "   " }, []) === UNIDENTIFIED);

  // --- legend, selectors ---------------------------------------------------
  const legend = renderOrFail(
    "legend · status mode",
    <MapLegend mode="status" ramp={null} counts={{ active_critical: 1, unregistered: 128 }} />,
  );
  check("the legend lists every state", legend.includes("Crítico") && legend.includes("Sin monitoreo"));
  check("the legend counts footprints", legend.includes("128"));
  check("the legend states that colour is not consumption", legend.includes("nunca el consumo"));
  check("OpenStreetMap attribution is present", legend.includes("OpenStreetMap"));

  const rampLegend = renderOrFail(
    "legend · magnitude mode",
    <MapLegend mode="power" ramp={buildRamp([4, 40])} counts={{}} />,
  );
  check("the ramp legend shows real bounds", rampLegend.includes("4.00") && rampLegend.includes("40.00"));
  check("the ramp legend labels the absence", rampLegend.includes("Sin valor medido"));
  check("the ramp legend disclaims judgement", rampLegend.includes("no es una anomalía"));

  const emptyRamp = renderOrFail(
    "legend · magnitude mode with no data",
    <MapLegend mode="cost" ramp={null} counts={{}} />,
  );
  check("an empty ramp says so rather than drawing a scale", emptyRamp.includes("Ningún edificio"));

  const selector = renderOrFail(
    "campus selector",
    <CampusSelector campuses={CAMPUSES} value={7} onChange={() => {}} />,
  );
  check("every campus is listed, traced or not", selector.includes("Campus Central") && selector.includes("Campus Tecomán"));
  check("an untraced campus is marked, not hidden", selector.includes("sin geometría"));
  check("the association coverage is stated", selector.includes("2/2"));

  const availability = {
    status: true,
    power: true,
    energy: true,
    cost: false,
    power_factor: true,
  } as Record<MapMode, boolean>;
  const modes = renderOrFail(
    "mode selector",
    <MapModeSelector value="status" onChange={() => {}} availability={availability} />,
  );
  check("STATUS is offered", modes.includes("Estado"));
  check("a mode with no data is disabled rather than removed", modes.includes("disabled") && modes.includes("Costo hoy"));
}

/**
 * Clicking a footprint must select it — the regression this file exists for.
 *
 * Leaflet's dispatch is modelled here rather than run, because
 * `renderToStaticMarkup` has no DOM. The model is not invented: it mirrors
 * `Map._findEventTargets` and `Map._fireDOMEvent` in the installed leaflet 1.9
 * source, both quoted where they matter.
 *
 *   `_findEventTargets` walks the DOM up from the clicked <path>, and the map
 *   registers ITSELF under the map container (`_targets[stamp(container)] =
 *   this`). The walk only stops at the container, so a click on a polygon
 *   resolves to [polygon, map] — not [polygon].
 *
 *   `_fireDOMEvent` then fires every target in order and returns early only if
 *   the event was stopped or `targets[i].options.bubblingMouseEvents === false`
 *   and the type is one of `_mouseEvents` (which includes 'click').
 *
 * `Path.options.bubblingMouseEvents` defaults to TRUE. So with the map's own
 * click handler clearing the selection, every building click set the selection
 * and cleared it again in the same dispatch: the panel never left its
 * placeholder and the map looked broken. The fix is the one line these checks
 * defend — `bubblingMouseEvents: false` in the footprint's path options.
 */
function clickDispatchChecks() {
  process.stdout.write("\nClick dispatch (models leaflet 1.9 Map._fireDOMEvent)\n");

  const LEAFLET_MOUSE_EVENTS = ["click", "dblclick", "mouseover", "mouseout", "contextmenu"];

  function fireDomEvent(
    type: string,
    targets: Array<{ options: { bubblingMouseEvents?: boolean }; fire: () => void }>,
  ) {
    for (const target of targets) {
      target.fire();
      if (target.options.bubblingMouseEvents === false && LEAFLET_MOUSE_EVENTS.includes(type)) {
        return;
      }
    }
  }

  // Exactly the wiring the components use: the polygon's own click sets the
  // selection, the map's click clears it, and the polygon's path options come
  // from the real `polygonStyle`.
  function clickPolygon(status: MapStatus, campusId: number, featureId: string) {
    let selection: MapSelection | null = null;
    const pathOptions = polygonStyle({
      status,
      mode: "status",
      value: null,
      ramp: null,
      selected: false,
      hovered: false,
    });
    fireDomEvent("click", [
      { options: pathOptions, fire: () => (selection = makeSelection(featureId, campusId)) },
      { options: {}, fire: () => (selection = makeSelection(null, campusId)) },
    ]);
    return resolveSelection(selection, campusId);
  }

  // The bug, stated as a test. Every one of these is a footprint a user clicks
  // on a normal campus, and before the fix every one of them stayed null.
  const cases: Array<[string, MapStatus, string]> = [
    ["an unmonitored OSM footprint", "unregistered", "way/1150811090"],
    ["a registered building with no deployment", "registered", "way/2"],
    ["a building with historical data only", "historical", "way/3"],
    ["a building with an active, fresh deployment", "active_healthy", "way/4"],
    ["a building with an active but stale deployment", "active_stale", "way/5"],
    ["a building with an open warning", "active_warning", "way/6"],
    ["a building with an open critical alert", "active_critical", "way/7"],
  ];
  for (const [label, status, id] of cases) {
    check(`clicking ${label} selects it`, clickPolygon(status, 7, id) === id, "selection was lost");
  }

  check(
    "the footprint's path options stop the click reaching the map",
    polygonStyle({
      status: "unregistered",
      mode: "status",
      value: null,
      ramp: null,
      selected: false,
      hovered: false,
    }).bubblingMouseEvents === false,
  );

  // Clicking bare map still clears, because nothing intercepts it first.
  let bare: MapSelection | null = makeSelection("way/1", 7);
  fireDomEvent("click", [{ options: {}, fire: () => (bare = makeSelection(null, 7)) }]);
  check("clicking empty map space still clears the selection", resolveSelection(bare, 7) === null);

  // Selection styling has to be visible on the map, not only in the panel.
  const selectedStyle = polygonStyle({
    status: "unregistered",
    mode: "status",
    value: null,
    ramp: null,
    selected: true,
    hovered: false,
  });
  const plainStyle = polygonStyle({
    status: "unregistered",
    mode: "status",
    value: null,
    ramp: null,
    selected: false,
    hovered: false,
  });
  check(
    "a selected footprint takes the Energy IQ blue outline even when unmonitored",
    selectedStyle.color === "#3b82f6" && selectedStyle.color !== plainStyle.color,
  );
  check(
    "and a heavier stroke, so selection is obvious without reading the panel",
    selectedStyle.weight > plainStyle.weight,
  );
}

/** Selection identity, and what a campus change does to it. */
function selectionChecks() {
  process.stdout.write("\nSelection identity\n");

  const picked = makeSelection("way/625447870", 7);
  check("a click stores the OSM feature id, not a building id", picked?.featureId === "way/625447870");
  check("and the campus it was made on", picked?.campusId === 7);
  check(
    "selection never consults the Energy IQ association",
    makeSelection("way/999", 7)?.featureId === "way/999",
  );
  check("it reads back on the campus it was made on", resolveSelection(picked, 7) === "way/625447870");
  check("switching campus clears it, without an effect to do so", resolveSelection(picked, 9) === null);
  check("and switching back shows it again", resolveSelection(picked, 7) === "way/625447870");
  check("no selection reads back as none", resolveSelection(null, 7) === null);
  check("clearing yields none", makeSelection(null, 7) === null);
}

/**
 * The coverage card on Infraestructura.
 *
 * The Campus Map page used to carry a block of platform metadata — footprint
 * counts and the telemetry window — which belongs to the deployment rather
 * than to the campus on screen. It lives here now, and every figure is summed
 * from the same `/api/campus-map/campuses` response the map is driven by.
 * Nothing is hardcoded: 140 is Campus Central alone, and stating it as a
 * platform total would have been wrong the moment a second campus was curated.
 */
function coverageChecks() {
  process.stdout.write("\nGeographic coverage card\n");

  const payload = {
    telemetry_window_seconds: 300,
    campuses: [
      { id: 7, has_geometry: true, footprint_count: 140, energy_iq_buildings: 2, mapped_buildings: 2 },
      { id: 9, has_geometry: true, footprint_count: 65, energy_iq_buildings: 1, mapped_buildings: 0 },
      { id: 4, has_geometry: true, footprint_count: 0, energy_iq_buildings: 0, mapped_buildings: 0 },
      { id: 6, has_geometry: false, footprint_count: 0, energy_iq_buildings: 0, mapped_buildings: 0 },
    ],
  };

  const html = renderOrFail("coverage card", <GeographicCoverage coverage={payload} />);
  check("footprints are summed across every campus, not taken from one", html.includes("205"));
  check("it never states one campus's count as the platform total", !html.includes(">140<"));
  check("mapped campuses are counted against the total", html.includes("3/4"));
  check("Energy IQ buildings are summed", html.includes(">3<"));
  check("associations are summed", html.includes(">2<"));
  check("the freshness window reads in minutes", html.includes("5 min"));
  check("it uses product language, not the developer explanation", !html.includes("nunca como actual"));
  check("OpenStreetMap attribution travels with the numbers", html.includes("OpenStreetMap"));

  const odd = renderOrFail(
    "coverage card · window that is not whole minutes",
    <GeographicCoverage coverage={{ ...payload, telemetry_window_seconds: 90 }} />,
  );
  check("a window that is not whole minutes stays in seconds", odd.includes("90 s"));

  const missing = renderOrFail(
    "coverage card · window absent",
    <GeographicCoverage coverage={{ ...payload, telemetry_window_seconds: null }} />,
  );
  check("an absent window renders as an em dash, never as 0", missing.includes("—"));

  check(
    "no coverage data renders nothing rather than a card of zeroes",
    renderToStaticMarkup(<GeographicCoverage coverage={null} />) === "",
  );
}

function main() {
  process.stdout.write("Campus map checks\n");
  coverageChecks();
  clickDispatchChecks();
  selectionChecks();
  geometryChecks();
  centroidChecks();
  groundsChecks();
  statusChecks();
  renderChecks();
  process.stdout.write(`\n${checks - failures}/${checks} checks passed\n`);
  if (failures > 0) {
    process.stdout.write(`${failures} FAILED\n`);
    process.exit(1);
  }
}

main();
