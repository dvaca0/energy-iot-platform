/**
 * Render checks for the live technical view.
 *
 * Two halves, deliberately.
 *
 * The **fixture** half is hermetic and is the regression suite: frozen payloads
 * covering the states that have no live example today — a node with no readings
 * at all, a node whose heartbeat never arrived, a stale window, a growing
 * buffer, a node that reports only some of the magnitudes, and a bucketed
 * window. Those are exactly the cases where a chart is tempted to draw a zero,
 * so they are the cases worth freezing.
 *
 * The **live** half runs only when a backend answers, and renders whatever the
 * platform is really returning right now. It is skipped, not failed, when the
 * API is unreachable, so the suite stays runnable off the server.
 *
 * `renderToStaticMarkup` needs no DOM. Recharts' ResponsiveContainer measures
 * to zero without one and emits no SVG — so these checks prove the component
 * tree, the data shaping and every label path, not the pixels. The pixels are
 * what the visual review on :5175 is for.
 */
import { renderToStaticMarkup } from "react-dom/server";

import { NodeSummaryCard } from "../src/components/livemonitor/NodeSummaryCard";
import { ReadingsTable } from "../src/components/livemonitor/ReadingsTable";
import { SeriesChart } from "../src/components/livemonitor/SeriesChart";
import type { History, Limits, NodeSnapshot, Snapshot } from "../src/components/livemonitor/types";
import { CHARTS, conditions, fmt, nodeSupports } from "../src/components/livemonitor/types";

const API = process.env.API ?? "http://127.0.0.1:8010/api";

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

const LIMITS: Limits = {
  nominal_voltage: 127,
  voltage_deviation_warning_pct: 13,
  voltage_deviation_critical_pct: 20,
  missing_phase_voltage: 40,
  nominal_frequency_hz: 60,
  frequency_deviation_warning_hz: 0.5,
  frequency_deviation_critical_hz: 1,
  power_factor_warning: 0.85,
  power_factor_critical: 0.7,
  current_warning_a: 400,
  current_critical_a: 500,
  voltage_imbalance_warning_pct: 2,
  voltage_imbalance_critical_pct: 5,
  current_imbalance_warning_pct: 10,
  current_imbalance_critical_pct: 25,
  imbalance_min_current_a: 1,
  node_offline_timeout_s: 300,
};

function node(overrides: Partial<NodeSnapshot>): NodeSnapshot {
  return {
    node_id: "NTEST",
    name: "Nodo de prueba",
    hardware_kind: "shelly",
    measurement_context: "production",
    commission_state: "commissioned",
    status: "online",
    rpi_status: "ok",
    shelly_status: "ok",
    last_sync: new Date().toISOString(),
    last_sync_age_seconds: 3,
    last_reading_building: "Edificio de prueba",
    deployment: null,
    reading: {
      timestamp: new Date().toISOString(),
      age_seconds: 4,
      context: "production",
      phase_a_voltage: 122.4,
      phase_b_voltage: 124.6,
      phase_c_voltage: 123.5,
      phase_a_current: 39.176,
      phase_b_current: 37.415,
      phase_c_current: 35.907,
      phase_a_power_kw: null,
      phase_b_power_kw: null,
      phase_c_power_kw: null,
      phase_a_apparent_kva: null,
      phase_b_apparent_kva: null,
      phase_c_apparent_kva: null,
      phase_a_power_factor: null,
      phase_b_power_factor: null,
      phase_c_power_factor: null,
      phase_a_frequency_hz: null,
      phase_b_frequency_hz: null,
      phase_c_frequency_hz: null,
      voltage_avg: 123.5,
      current_total: 112.497,
      power_kw: 13.171607,
      apparent_kva: null,
      power_factor: 0.9468,
      frequency_hz: 60,
      neutral_current: null,
      meter_energy_kwh: null,
      meter_energy_returned_kwh: null,
      phase_a_energy_imported_kwh: null,
      phase_b_energy_imported_kwh: null,
      phase_c_energy_imported_kwh: null,
      phase_a_energy_returned_kwh: null,
      phase_b_energy_returned_kwh: null,
      phase_c_energy_returned_kwh: null,
    },
    energy_today_kwh: 186.13,
    available_metrics: [
      "phase_voltage",
      "phase_current",
      "voltage",
      "current",
      "power_kw",
      "power_factor",
      "frequency_hz",
    ],
    health: {
      reported_at: new Date().toISOString(),
      received_at: new Date().toISOString(),
      age_seconds: 5,
      clock_drift_seconds: -0.64,
      collector_status: "active",
      collector_restarts: null,
      buffered_readings: 0,
      pending_sync: 0,
      last_measurement_at: new Date().toISOString(),
      cpu_percent: 3,
      cpu_temperature_c: 37.5,
      memory_percent: 9,
      disk_percent: 17.8,
      disk_free_mb: 51202,
      uptime_seconds: 371097,
      undervoltage: true,
      throttled: false,
      throttle_flags: "0x50000",
      filesystem_readonly: true,
      ethernet_up: true,
      wifi_up: true,
      sqlite_size_mb: 39.36,
      software_version: "2.0.0",
      ads_ok: null,
      shelly_reachable: null,
      meter_temperature_c: null,
      local_alerts: [],
    },
    ...overrides,
  };
}

function seriesFor(nodeId: string, count: number, bucketed: boolean) {
  const points = Array.from({ length: count }, (_, index) => ({
    t: new Date(Date.now() - (count - index) * 15000).toISOString().replace("Z", ""),
    va: 122 + index * 0.01,
    vb: 124 + index * 0.01,
    vc: 123 + index * 0.01,
    ia: 39 + index * 0.02,
    ib: 37 + index * 0.02,
    ic: 35 + index * 0.02,
    v: 123.2,
    i: 111 + index * 0.06,
    kw: 13.1 + index * 0.001,
    pf: 0.95,
    hz: 60,
    kwh: 0.0548,
    ...(bucketed ? { n: 20, i_min: 110, i_max: 113, kw_min: 13, kw_max: 13.2 } : {}),
  }));
  return { node_id: nodeId, hardware_kind: "shelly", points };
}

function history(nodeIds: string[], bucketed: boolean): History {
  return {
    range: bucketed ? "24h" : "15m",
    start: new Date(Date.now() - 900000).toISOString(),
    end: new Date().toISOString(),
    window_start: new Date(Date.now() - 900000).toISOString(),
    incremental: false,
    resolution_seconds: bucketed ? 300 : 0,
    aggregation: bucketed ? "mean over 300 s buckets" : "raw",
    point_count: nodeIds.length * 20,
    series: nodeIds.map((id) => seriesFor(id, 20, bucketed)),
  };
}

// ------------------------------------------------------------------ fixtures

function fixtureChecks() {
  process.stdout.write("\nFixtures\n");

  const healthy = node({});
  const html = renderOrFail("healthy node card", <NodeSummaryCard node={healthy} limits={LIMITS} />);
  check("healthy card shows the per-phase currents", html.includes("39.176"));
  check("healthy card shows full power precision", html.includes("13.1716"));
  check("healthy card reports MIDIENDO", html.includes("MIDIENDO"));

  // A node with no readings at all must not render a single fabricated number.
  const silent = node({
    node_id: "NSILENT",
    reading: null,
    available_metrics: [],
    shelly_status: "offline",
  });
  const silentHtml = renderOrFail("node with no readings", <NodeSummaryCard node={silent} limits={LIMITS} />);
  check("silent node says it has no readings", silentHtml.includes("no tiene ninguna lectura"));
  check(
    "silent node raises the 'Sin lecturas' condition",
    conditions(silent, LIMITS).some((entry) => entry.label === "Sin lecturas"),
  );

  // The honest-degradation case: hardware that reports current but nothing else.
  const partial = node({
    node_id: "NPARTIAL",
    hardware_kind: "ads1256",
    available_metrics: ["phase_current", "current"],
  });
  const partialHtml = renderOrFail(
    "node reporting only current",
    <NodeSummaryCard node={partial} limits={LIMITS} />,
  );
  check("missing magnitudes read 'no disponible'", partialHtml.includes("no disponible"));
  check("missing per-phase voltage reads n/d", partialHtml.includes("n/d"));

  const chartHtml = renderOrFail(
    "chart with an ineligible node",
    <SeriesChart
      spec={CHARTS.find((entry) => entry.id === "phase_voltage")!}
      series={history(["NPARTIAL"], false).series}
      nodes={[partial]}
      perPhase
      resolutionSeconds={0}
      paused={false}
    />,
  );
  check(
    "voltage chart declares the node unavailable rather than plotting zero",
    chartHtml.includes("No disponible en NPARTIAL"),
  );
  check("unavailable chart draws no zero value", !chartHtml.includes(">0.00<"));

  // Stale window: last reading older than the platform's own offline timeout.
  const stale = node({
    node_id: "NSTALE",
    reading: { ...node({}).reading!, age_seconds: 9600 },
    shelly_status: "offline",
  });
  const staleFound = conditions(stale, LIMITS);
  check(
    "stale reading is reported",
    staleFound.some((entry) => entry.label === "Lectura obsoleta"),
  );

  // A buffer that is filling is the signal that uploads are being refused.
  const buffered = node({
    node_id: "NBUF",
    health: { ...node({}).health!, pending_sync: 32402 },
  });
  const bufferedFound = conditions(buffered, LIMITS);
  check(
    "pending buffer is reported",
    bufferedFound.some((entry) => entry.label === "Buffer pendiente"),
  );
  const bufferedHtml = renderOrFail(
    "node with a filling buffer",
    <NodeSummaryCard node={buffered} limits={LIMITS} />,
  );
  check("buffer count is shown in full", bufferedHtml.includes("32,402") || bufferedHtml.includes("32 402"));

  // Imbalance must stay silent at the noise floor and speak under load.
  const idle = node({
    node_id: "NIDLE",
    reading: {
      ...node({}).reading!,
      phase_a_current: 0.00001,
      phase_b_current: 0.00009,
      phase_c_current: 0.00002,
      current_total: 0.00012,
      power_factor: 0.0,
    },
  });
  check(
    "imbalance is not reported at the noise floor",
    !conditions(idle, LIMITS).some((entry) => entry.label === "Desbalance de corriente"),
  );
  check(
    "power factor is not reported at the noise floor",
    !conditions(idle, LIMITS).some((entry) => entry.label === "Factor de potencia bajo"),
  );

  const skewed = node({
    node_id: "NSKEW",
    reading: {
      ...node({}).reading!,
      phase_a_current: 60,
      phase_b_current: 30,
      phase_c_current: 30,
      current_total: 120,
    },
  });
  check(
    "imbalance is reported under real load",
    conditions(skewed, LIMITS).some((entry) => entry.label === "Desbalance de corriente"),
  );

  // Multi-node comparison: legends must name NODE · PHASE, never a bare phase.
  const second = node({ node_id: "N002" });
  const comparison = renderOrFail(
    "two-node per-phase chart",
    <SeriesChart
      spec={CHARTS.find((entry) => entry.id === "phase_current")!}
      series={history(["NTEST", "N002"], false).series}
      nodes={[healthy, second]}
      perPhase
      resolutionSeconds={0}
      paused={false}
    />,
  );
  check("comparison legend names node and phase", comparison.includes("NTEST · A") && comparison.includes("N002 · A"));

  // Bucketed windows must announce themselves everywhere they appear.
  const bucketedHistory = history(["NTEST"], true);
  const tableHtml = renderOrFail(
    "readings table over a bucketed window",
    <ReadingsTable series={bucketedHistory.series} resolutionSeconds={300} />,
  );
  check("bucketed table warns the rows are means", tableHtml.includes("Medias de cubetas de 300 s"));

  const rawTable = renderOrFail(
    "readings table over a raw window",
    <ReadingsTable series={history(["NTEST"], false).series} resolutionSeconds={0} />,
  );
  check("raw table says the rows are stored samples", rawTable.includes("tal y como se almacenaron"));

  // Pause must be visible on the charts, not only in the toolbar.
  const paused = renderOrFail(
    "paused chart",
    <SeriesChart
      spec={CHARTS.find((entry) => entry.id === "power_kw")!}
      series={history(["NTEST"], false).series}
      nodes={[healthy]}
      perPhase={false}
      resolutionSeconds={0}
      paused
    />,
  );
  check("paused chart is labelled", paused.includes("PAUSA"));
}

// ---------------------------------------------------------------------- live

async function get(path: string) {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`${path} -> HTTP ${response.status}`);
  return response.json();
}

async function liveChecks() {
  process.stdout.write("\nLive backend\n");

  let snapshot: Snapshot;
  try {
    snapshot = await get("/metrics/live/snapshot");
  } catch (error) {
    process.stdout.write(`  skip  backend unreachable (${(error as Error).message})\n`);
    return;
  }

  check("snapshot returns nodes", snapshot.nodes.length > 0);
  check("snapshot publishes the platform limits", typeof snapshot.limits?.nominal_voltage === "number");
  check(
    "limits are the platform's own, not invented here",
    snapshot.limits.power_factor_warning === 0.85 && snapshot.limits.nominal_frequency_hz === 60,
    JSON.stringify(snapshot.limits),
  );

  for (const entry of snapshot.nodes) {
    renderOrFail(`live card ${entry.node_id}`, <NodeSummaryCard node={entry} limits={snapshot.limits} />);
    // The rule that matters most: a metric absent from the reading must be
    // absent from `available_metrics`, or the card will print a zero for it.
    if (entry.reading) {
      const claimsPower = entry.available_metrics.includes("power_kw");
      check(
        `${entry.node_id} advertises power only when it reported one`,
        claimsPower === (entry.reading.power_kw !== null),
      );
    } else {
      check(`${entry.node_id} advertises nothing without a reading`, entry.available_metrics.length === 0);
    }
  }

  const codes = snapshot.nodes.map((entry) => entry.node_id);
  for (const range of ["5m", "15m", "30m", "1h", "6h", "24h", "7d", "deployment"]) {
    const started = Date.now();
    const window: History = await get(
      `/metrics/live/history?node_ids=${codes.join(",")}&range=${range}`,
    );
    const elapsed = Date.now() - started;
    const bytes = JSON.stringify(window).length;
    process.stdout.write(
      `  ${range.padStart(3)}  ${String(elapsed).padStart(4)} ms  ${(bytes / 1024).toFixed(1).padStart(6)} KB  ` +
        `${String(window.point_count).padStart(4)} pts  res=${window.resolution_seconds}s\n`,
    );

    check(`${range} declares its aggregation`, typeof window.aggregation === "string" && window.aggregation.length > 0);
    check(`${range} stays under 1000 points`, window.point_count <= 1000, `${window.point_count}`);

    for (const spec of CHARTS) {
      renderOrFail(
        `${range} · ${spec.id}`,
        <SeriesChart
          spec={spec}
          series={window.series}
          nodes={snapshot.nodes}
          perPhase
          resolutionSeconds={window.resolution_seconds}
          paused={false}
        />,
      );
    }
    renderOrFail(
      `${range} · tabla`,
      <ReadingsTable series={window.series} resolutionSeconds={window.resolution_seconds} />,
    );
  }

  // --- the deployment range is scoped by deployment, not by node + dates ---
  const campaigns = await get("/metrics/live/deployments");
  check("the deployment selector has options", Array.isArray(campaigns) && campaigns.length > 0);

  if (Array.isArray(campaigns) && campaigns.length > 0) {
    for (const campaign of campaigns) {
      const scoped: History = await get(
        `/metrics/live/history?range=deployment&deployment_id=${campaign.deployment_id}`,
      );
      const span = scoped.deployments?.[0];
      check(
        `#${campaign.deployment_id} resolves to itself, not to a union`,
        scoped.deployment_id === campaign.deployment_id && span?.deployment_id === campaign.deployment_id,
      );
      check(
        `#${campaign.deployment_id} uses its own bounds`,
        scoped.window_start.slice(0, 16) === (campaign.activated_at ?? "").slice(0, 16),
        `${scoped.window_start} vs ${campaign.activated_at}`,
      );
      check(
        `#${campaign.deployment_id} shows only nodes with its data`,
        scoped.series.every((entry) => entry.points.length === 0 || entry.node_id === campaign.node_id),
        scoped.series.map((entry) => entry.node_id).join(","),
      );
      check(
        `#${campaign.deployment_id} reports its attribution census`,
        typeof span?.readings_in_window === "number" &&
          typeof span?.readings_outside_window === "number",
      );
      // A campaign whose readings all fall outside its window is legitimately
      // empty. The page must be able to say why, so the numbers must be there.
      if (span?.readings_in_window === 0 && (span?.readings_outside_window ?? 0) > 0) {
        check(
          `#${campaign.deployment_id} is empty and explains itself`,
          scoped.point_count === 0 && (span.readings_outside_window ?? 0) > 0,
        );
      }
    }

    // Node selection must not change a deployment-scoped answer.
    const first = campaigns[0];
    const plain: History = await get(
      `/metrics/live/history?range=deployment&deployment_id=${first.deployment_id}`,
    );
    const withNodes: History = await get(
      `/metrics/live/history?range=deployment&deployment_id=${first.deployment_id}&node_ids=N002,N003`,
    );
    check(
      "node_ids is ignored in deployment mode",
      plain.point_count === withNodes.point_count &&
        plain.series.map((entry) => entry.node_id).join() ===
          withNodes.series.map((entry) => entry.node_id).join(),
    );

    // Two campaigns from different months must not share an axis.
    if (campaigns.length > 1) {
      const a: History = await get(
        `/metrics/live/history?range=deployment&deployment_id=${campaigns[0].deployment_id}`,
      );
      const b: History = await get(
        `/metrics/live/history?range=deployment&deployment_id=${campaigns[campaigns.length - 1].deployment_id}`,
      );
      check(
        "different campaigns get different windows, never a merged one",
        a.window_start !== b.window_start && a.end !== b.end,
      );
    }
  }

  // Incremental extension must return strictly newer samples, or the client
  // would re-append points it already holds and draw a spur on every line.
  const base: History = await get(`/metrics/live/history?node_ids=${codes[0]}&range=15m`);
  const points = base.series[0]?.points ?? [];
  if (points.length > 2) {
    const watermark = points[points.length - 2].t;
    const extension: History = await get(
      `/metrics/live/history?node_ids=${codes[0]}&range=15m&since=${encodeURIComponent(watermark)}`,
    );
    check("since= is honoured on a raw range", extension.incremental === true);
    check(
      "since= returns only newer samples",
      (extension.series[0]?.points ?? []).every((point) => point.t > watermark),
    );
    const bucketedExtension: History = await get(
      `/metrics/live/history?node_ids=${codes[0]}&range=24h&since=${encodeURIComponent(watermark)}`,
    );
    check("since= is refused on a bucketed range", bucketedExtension.incremental === false);
  }
}

// -------------------------------------------------------- the M15 expansion

/** The verbatim capture from N001's meter, 2026-08-18. */
const CAPTURE = {
  a_act_power: 4632.3, b_act_power: 4392.3, c_act_power: 3628.2,
  a_aprt_power: 4679.9, b_aprt_power: 4437.9, c_aprt_power: 4194.1,
  a_pf: 0.99, b_pf: 0.99, c_pf: 0.87,
  total_act_power: 12652.766, total_aprt_power: 13311.875,
  n_current: null as number | null,
};

/** A node measuring with the expanded schema — i.e. after the collector update. */
function expandedNode(): NodeSnapshot {
  const base = node({});
  return {
    ...base,
    node_id: "NEXP",
    reading: {
      ...base.reading!,
      phase_a_power_kw: CAPTURE.a_act_power / 1000,
      phase_b_power_kw: CAPTURE.b_act_power / 1000,
      phase_c_power_kw: CAPTURE.c_act_power / 1000,
      phase_a_apparent_kva: CAPTURE.a_aprt_power / 1000,
      phase_b_apparent_kva: CAPTURE.b_aprt_power / 1000,
      phase_c_apparent_kva: CAPTURE.c_aprt_power / 1000,
      phase_a_power_factor: CAPTURE.a_pf,
      phase_b_power_factor: CAPTURE.b_pf,
      phase_c_power_factor: CAPTURE.c_pf,
      phase_a_frequency_hz: 60,
      phase_b_frequency_hz: 60,
      phase_c_frequency_hz: 60,
      power_kw: CAPTURE.total_act_power / 1000,
      apparent_kva: CAPTURE.total_aprt_power / 1000,
      neutral_current: CAPTURE.n_current,
      meter_energy_kwh: 5310.91991,
      meter_energy_returned_kwh: 184.58757,
    },
    available_metrics: [
      "phase_voltage", "phase_current", "phase_power", "phase_apparent",
      "phase_power_factor", "phase_frequency", "voltage", "current",
      "power_kw", "apparent_kva", "power_factor", "frequency_hz",
      "energy_imported", "energy_returned",
    ],
  };
}

function expandedSeries(nodeId: string, count: number) {
  const points = Array.from({ length: count }, (_, index) => ({
    t: new Date(Date.now() - (count - index) * 15000).toISOString().replace("Z", ""),
    va: 124.7, vb: 126.1, vc: 126.0,
    ia: 37.47, ib: 35.133, ic: 33.257,
    pa: 4.6323, pb: 4.3923, pc: 3.6282,
    sa: 4.6799, sb: 4.4379, sc: 4.1941,
    pfa: 0.99, pfb: 0.99, pfc: 0.87,
    fa: 60, fb: 60, fc: 60,
    v: 125.6, i: 105.86, kw: 12.652766, kva: 13.311875, pf: 0.9505, hz: 60,
    imp_t: 5310.92, ret_t: 184.588,
    // `nc` is deliberately ABSENT, exactly as the backend omits it.
    kwh: 0.0527,
  }));
  return { node_id: nodeId, hardware_kind: "shelly", points };
}

function m15Checks() {
  process.stdout.write("\nM15 — the expanded field set\n");

  const expanded = expandedNode();
  const html = renderOrFail("expanded node card", <NodeSummaryCard node={expanded} limits={LIMITS} />);
  check("per-phase active power is shown", html.includes("4.6323"));
  check("per-phase apparent power is shown", html.includes("4.6799"));
  check("phase C power factor 0.87 is visible beside 0.99", html.includes("0.8700") && html.includes("0.9900"));
  check("total apparent power is shown", html.includes("13.3119"));
  check("meter import register is shown at register precision", html.includes("5310.920"));

  // The whole point of the migration: the aggregate hides the phase C problem.
  check(
    "the aggregate PF alone would have hidden phase C",
    expanded.reading!.power_factor! > 0.94 && expanded.reading!.phase_c_power_factor! < 0.88,
  );

  // n_current is genuinely null on this installation.
  check(
    "neutral current is not advertised when the meter returned null",
    !expanded.available_metrics.includes("neutral_current"),
  );
  const neutralChart = CHARTS.find((spec) => spec.id === "neutral_current")!;
  check("the neutral chart is not drawable for this node", !nodeSupports(expanded, neutralChart));
  check("no chart renders neutral current as 0", !html.includes(">0.000<"));

  // Old data: every new column null. Must render as unavailable, never as zero.
  const legacy = node({ node_id: "NOLD" });
  const legacyHtml = renderOrFail("pre-M15 node card", <NodeSummaryCard node={legacy} limits={LIMITS} />);
  check("pre-M15 node still renders its measured values", legacyHtml.includes("39.176"));
  check("pre-M15 node marks the new columns n/d", legacyHtml.includes("n/d"));
  check(
    "pre-M15 node advertises none of the new groups",
    !["phase_power", "phase_apparent", "phase_power_factor", "phase_frequency", "apparent_kva"].some(
      (metric) => legacy.available_metrics.includes(metric),
    ),
  );

  // Derived reactive power.
  const reactive = CHARTS.find((spec) => spec.id === "reactive_derived")!;
  check("reactive power is declared derived", Boolean(reactive.derived));
  check(
    "reactive power needs BOTH measured inputs",
    reactive.derived!.from.includes("power_kw") && reactive.derived!.from.includes("apparent_kva"),
  );
  const q = reactive.derived!.compute({ t: "x", kw: 12.652766, kva: 13.311875 });
  const expectedQ = Math.sqrt(13.311875 ** 2 - 12.652766 ** 2);
  check("Q = sqrt(S^2 - P^2) from the captured values", Math.abs((q ?? -1) - expectedQ) < 1e-9,
    `${q} vs ${expectedQ}`);
  check("Q is null when apparent power is missing", reactive.derived!.compute({ t: "x", kw: 12.65 }) === null);
  check("Q is null when active power is missing", reactive.derived!.compute({ t: "x", kva: 13.31 }) === null);
  check("Q clamps at zero rather than producing NaN at unity PF",
    reactive.derived!.compute({ t: "x", kw: 10.000001, kva: 10 }) === 0);
  const qHtml = renderOrFail(
    "reactive chart",
    <SeriesChart spec={reactive} series={[expandedSeries("NEXP", 10)]} nodes={[expanded]}
      perPhase={false} resolutionSeconds={0} paused={false} />,
  );
  check("the reactive chart is labelled CALCULADO", qHtml.includes("CALCULADO"));
  check("the reactive chart states its formula", qHtml.includes("√(S² − P²)"));
  check("a node without apparent power cannot supply Q", !nodeSupports(legacy, reactive));

  // Multi-node comparison across the schema boundary.
  const comparison = renderOrFail(
    "expanded vs legacy on the same chart",
    <SeriesChart
      spec={CHARTS.find((spec) => spec.id === "phase_power")!}
      series={[expandedSeries("NEXP", 10), seriesFor("NOLD", 10, false)]}
      nodes={[expanded, legacy]}
      perPhase
      resolutionSeconds={0}
      paused={false}
    />,
  );
  check("the legacy node is named as unavailable, not plotted", comparison.includes("No disponible en NOLD"));
  check("the expanded node is plotted", comparison.includes("4.6323"));

  // Exact tooltip precision, per unit.
  check("kW formats to 4 decimals", fmt(4.6323, "kW") === "4.6323");
  check("kVA formats to 4 decimals", fmt(13.311875, "kVA") === "13.3119");
  check("power factor formats to 4 decimals", fmt(0.87, "") === "0.8700");
  check("current formats to 3 decimals", fmt(37.47, "A") === "37.470");
  check("registers format to 3 decimals, not 6", fmt(5310.91991, "kWh_reg") === "5310.920");
  check("interval energy keeps 6 decimals", fmt(0.0527198, "kWh") === "0.052720");
  check("an absent value formats as an em dash, never 0", fmt(undefined as never, "kW") === "—");
  check("null formats as an em dash", fmt(null, "A") === "—");

  // Every chart must render for a fully-expanded node.
  for (const spec of CHARTS) {
    if (!nodeSupports(expanded, spec)) continue;
    renderOrFail(
      `expanded · ${spec.id}`,
      <SeriesChart spec={spec} series={[expandedSeries("NEXP", 12)]} nodes={[expanded]}
        perPhase resolutionSeconds={0} paused={false} />,
    );
  }
}

async function main() {
  process.stdout.write("Live monitor render checks\n");
  fixtureChecks();
  m15Checks();
  await liveChecks();
  process.stdout.write(`\n${checks - failures}/${checks} checks passed\n`);
  if (failures > 0) {
    process.stdout.write(`${failures} FAILED\n`);
    process.exit(1);
  }
}

void main();
