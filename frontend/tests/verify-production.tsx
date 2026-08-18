/**
 * Post-promotion verification, run against the live backend.
 *
 * Not a regression suite — a one-shot proof that what production now serves
 * renders the real fleet correctly, including the two nodes that are
 * intentionally offline for maintenance. Kept because "it looked fine" is not
 * evidence, and because the failure class this guards against (a render that
 * throws after first paint) produces a black screen, not an error page.
 */
import { renderToStaticMarkup } from "react-dom/server";

import { NodeSummaryCard } from "../src/components/livemonitor/NodeSummaryCard";
import { SeriesChart } from "../src/components/livemonitor/SeriesChart";
import { ReadingsTable } from "../src/components/livemonitor/ReadingsTable";
import { CHARTS, nodeSupports } from "../src/components/livemonitor/types";
import type { History, Snapshot } from "../src/components/livemonitor/types";

const API = process.env.API ?? "http://127.0.0.1:8010/api";
let fail = 0;
const ok = (name: string, cond: boolean, detail = "") => {
  process.stdout.write(`  ${cond ? "ok  " : "FAIL"}  ${name}${cond || !detail ? "" : ` — ${detail}`}\n`);
  if (!cond) fail += 1;
};

async function get(path: string) {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

async function main() {
  const snap: Snapshot = await get("/metrics/live/snapshot");
  process.stdout.write("\nFLEET AS PRODUCTION NOW RENDERS IT\n");

  for (const n of snap.nodes) {
    const html = renderToStaticMarkup(<NodeSummaryCard node={n} limits={snap.limits} />);
    const age = n.reading?.age_seconds;
    process.stdout.write(
      `\n  ${n.node_id}  ${n.hardware_kind ?? "?"}  metrics=${n.available_metrics.length}  ` +
        `rpi=${n.rpi_status} meter=${n.shelly_status}  ` +
        `lectura=${age === null || age === undefined ? "nunca" : `hace ${Math.round(age)} s`}\n`,
    );
    ok(`${n.node_id} card renders`, html.length > 0);
    ok(`${n.node_id} no NaN in output`, !html.includes("NaN"));
    ok(`${n.node_id} no "undefined" leaked into text`, !html.includes(">undefined<"));

    // A node that reports nothing must say so, not show zeros.
    if (n.available_metrics.length === 0) {
      // A node with no stored reading at all takes the card's early-return
      // branch, which states the absence in a sentence rather than filling a
      // grid with "no disponible". Either wording is honest; a zero would not
      // be, so that is what this really asserts.
      ok(
        `${n.node_id} declares the absence explicitly`,
        html.includes("no tiene ninguna lectura") ||
          html.includes("no disponible") ||
          html.includes("n/d"),
      );
      ok(`${n.node_id} shows no fabricated zero`, !html.includes(">0.000<") && !html.includes(">0.0000<"));
    }
    // Neutral current is null on this installation — must never be advertised.
    ok(
      `${n.node_id} advertises neutral current only if measured`,
      n.available_metrics.includes("neutral_current") === (n.reading?.neutral_current !== null && n.reading?.neutral_current !== undefined),
    );
  }

  // N001 — the expanded contract.
  const n001 = snap.nodes.find((n) => n.node_id === "N001");
  if (n001) {
    process.stdout.write("\nN001 EXPANDED CONTRACT\n");
    const r = n001.reading!;
    ok("14 metric groups", n001.available_metrics.length === 14, String(n001.available_metrics.length));
    for (const [label, value] of [
      ["phase_a_power_kw", r.phase_a_power_kw], ["phase_b_power_kw", r.phase_b_power_kw],
      ["phase_c_power_kw", r.phase_c_power_kw], ["phase_a_apparent_kva", r.phase_a_apparent_kva],
      ["phase_c_power_factor", r.phase_c_power_factor], ["phase_a_frequency_hz", r.phase_a_frequency_hz],
      ["apparent_kva", r.apparent_kva], ["meter_energy_kwh", r.meter_energy_kwh],
    ] as [string, number | null][]) {
      ok(`${label} is a real number`, typeof value === "number", String(value));
    }
    ok("neutral_current stays NULL", r.neutral_current === null);
    ok("meter temperature reaches health, not the reading", typeof n001.health?.meter_temperature_c === "number");

    const html = renderToStaticMarkup(<NodeSummaryCard node={n001} limits={snap.limits} />);
    ok("card shows per-phase kW", html.includes(String(r.phase_a_power_kw!.toFixed(4))));
    ok("card shows per-phase kVA", html.includes(String(r.phase_a_apparent_kva!.toFixed(4))));
    ok("card shows the phase-C power factor", html.includes(r.phase_c_power_factor!.toFixed(4)));
    ok("neutral current renders as unavailable, not 0", html.includes("no disponible"));
  }

  // Ranges.
  process.stdout.write("\nHISTORICAL RANGES\n");
  for (const range of ["5m", "15m", "30m", "1h", "6h", "24h", "7d"]) {
    const h: History = await get(`/metrics/live/history?node_ids=N001&range=${range}`);
    const pts = h.series[0]?.points.length ?? 0;
    const raw = h.resolution_seconds === 0;
    process.stdout.write(`  ${range.padStart(4)}  ${raw ? "RAW " : `${h.resolution_seconds}s`}  ${String(pts).padStart(4)} pts\n`);
    ok(`${range} populates`, pts > 0);
    ok(`${range} raw-vs-aggregated is as specified`, raw === ["5m", "15m", "30m", "1h"].includes(range));
    const spec = CHARTS.find((c) => c.id === "phase_power")!;
    const chart = renderToStaticMarkup(
      <SeriesChart spec={spec} series={h.series} nodes={snap.nodes.filter((n) => n.node_id === "N001")}
        perPhase resolutionSeconds={h.resolution_seconds} paused={false} />,
    );
    ok(`${range} per-phase power chart renders`, chart.length > 0 && !chart.includes("NaN"));
  }

  // Deployment-scoped.
  process.stdout.write("\nDEPLOYMENT SELECTOR\n");
  const campaigns = await get("/metrics/live/deployments");
  for (const c of campaigns) {
    const h: History = await get(`/metrics/live/history?range=deployment&deployment_id=${c.deployment_id}`);
    const span = h.deployments?.[0];
    process.stdout.write(
      `  #${c.deployment_id} ${c.node_id}  ${String(h.point_count).padStart(4)} pts  ` +
        `dentro=${span?.readings_in_window} fuera=${span?.readings_outside_window}\n`,
    );
    ok(`#${c.deployment_id} scopes to itself`, h.deployment_id === c.deployment_id);
  }

  // Every drawable chart, for the real fleet.
  process.stdout.write("\nEVERY CHART, REAL DATA\n");
  const h: History = await get("/metrics/live/history?node_ids=N001,N002,N003&range=1h");
  let drawn = 0;
  for (const spec of CHARTS) {
    const eligible = snap.nodes.filter((n) => nodeSupports(n, spec));
    const html = renderToStaticMarkup(
      <SeriesChart spec={spec} series={h.series} nodes={snap.nodes} perPhase
        resolutionSeconds={h.resolution_seconds} paused={false} />,
    );
    ok(`${spec.id} renders (${eligible.length} node(s) eligible)`, html.length > 0 && !html.includes("NaN"));
    if (eligible.length > 0) drawn += 1;
  }
  process.stdout.write(`  ${drawn}/${CHARTS.length} charts have at least one eligible node\n`);
  const table = renderToStaticMarkup(<ReadingsTable series={h.series} resolutionSeconds={h.resolution_seconds} />);
  ok("readings table renders", table.length > 0 && !table.includes("NaN"));

  process.stdout.write(fail === 0 ? "\nALL PRODUCTION CHECKS PASSED\n" : `\n${fail} FAILED\n`);
  if (fail) process.exit(1);
}

void main();
