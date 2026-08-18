/**
 * Regression test for the 2026-08-13 production outage.
 *
 *     Uncaught ReferenceError: effectiveStatus is not defined
 *
 * `AIInsightCard` returns early when it has no findings, so every static check
 * and every manual load passed for as long as `/api/anomalies` was empty. The
 * dangling identifier lived inside `normalized.map(...)`, which only runs once
 * at least one finding exists — so the defect shipped, sat latent for hours,
 * and then took the entire React tree down the moment the anomaly engine
 * produced its first result.
 *
 * The lesson this test encodes: rendering the EMPTY state proves nothing. The
 * fixtures below are the exact records `/api/anomalies?include_resolved=true`
 * returned while production was black, including the `status: "active"` finding
 * with a `current_value`, which is the branch that threw.
 *
 * No DOM and no test framework: renderToStaticMarkup is enough, and a
 * ReferenceError in a render surfaces as a thrown exception here exactly as it
 * did in the browser.
 */
import { renderToStaticMarkup } from "react-dom/server";

import { AIInsightCard } from "../src/App";

let failures = 0;

function check(label: string, condition: boolean, detail = "") {
  if (condition) {
    console.log(`  ok   ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? ` :: ${detail}` : ""}`);
  }
}

function render(label: string, insights: unknown[]): string | null {
  try {
    return renderToStaticMarkup(<AIInsightCard insights={insights} />);
  } catch (error) {
    failures += 1;
    console.log(`  FAIL ${label} threw ${(error as Error).name}: ${(error as Error).message}`);
    return null;
  }
}

// Verbatim from /api/anomalies?include_resolved=true at 2026-08-14T03:34 UTC,
// the payload that was crashing production.
const LIVE_PAYLOAD = [
  {
    priority: "medium",
    category: "Power Factor",
    building: "Edificio Principal 2.0",
    node_id: "N001",
    title: "Factor de potencia bajo",
    desc: "Factor de potencia por debajo del umbral.",
    status: "resolved",
    threshold: 0.95,
    unit: "",
    previous_value: 0.94,
    previous_at: "2026-08-14T03:20:00",
    current_value: 0.9513710855638156,
    current_at: "2026-08-14T03:34:46.447000",
    recovered_at: "2026-08-14T03:34:46.447000",
  },
  {
    priority: "high",
    category: "Current Load",
    building: "Edificio Principal 2.0",
    node_id: "N001",
    title: "Carga de corriente elevada",
    desc: "Corriente sostenida por encima del umbral.",
    status: "resolved",
    threshold: 100,
    unit: " A",
    previous_value: 108.2,
    previous_at: "2026-08-14T03:20:00",
    current_value: 107.741,
    current_at: "2026-08-14T03:34:46.447000",
    recovered_at: "2026-08-14T03:34:46.447000",
  },
  {
    // THE record that threw: status "active" WITH a current_value is the exact
    // combination the dangling reference guarded.
    priority: "medium",
    category: "Night Consumption",
    building: "Edificio Principal 2.0",
    node_id: "N001",
    title: "Consumo nocturno elevado",
    desc: "Consumo sostenido fuera de horario.",
    status: "active",
    threshold: 10,
    unit: " kW",
    current_value: 12.981311,
    current_at: "2026-08-14T03:34:46.447000",
  },
];

console.log("\n--- AIInsightCard renders the live /api/anomalies payload ---");
const live = render("live payload renders without throwing", LIVE_PAYLOAD);
if (live !== null) {
  check("renders one card per finding", (live.match(/Edificio Principal 2\.0/g) || []).length === 3);
  check("renders the ACTIVE finding's current value", live.includes("12.98"), live.slice(0, 200));
  check("renders a resolved finding's recovery block", live.includes("Recuperado"));
  check("shows the active/resolved counts", live.includes("activa(s)"));
}

console.log("\n--- the active-with-value branch in isolation ---");
const activeOnly = render("active finding renders", [LIVE_PAYLOAD[2]]);
if (activeOnly !== null) {
  check("active finding shows Valor actual", activeOnly.includes("Valor actual"));
  check("active finding shows no recovery block", !activeOnly.includes("Recuperado"));
}

console.log("\n--- a resolved finding still renders its recovery block ---");
const resolvedOnly = render("resolved finding renders", [LIVE_PAYLOAD[0]]);
if (resolvedOnly !== null) {
  check("resolved finding shows Recuperado", resolvedOnly.includes("Recuperado"));
}

console.log("\n--- string findings and the empty state still work ---");
const strings = render("plain string findings render", ["El sistema no reporta anomalías nuevas."]);
if (strings !== null) {
  check("string finding is rendered", strings.includes("Mensaje del sistema"));
}
const empty = render("empty list renders", []);
if (empty !== null) {
  // The early return is exactly what hid the defect. Asserted so nobody
  // mistakes "the empty state renders" for coverage of the map.
  check("empty state short-circuits before the map", empty.includes("Sin anomalías registradas"));
}

console.log(
  `\n${"=".repeat(60)}\n  ${failures === 0 ? "ALL CHECKS PASSED" : `${failures} FAILED`}\n${"=".repeat(60)}`,
);
process.exit(failures === 0 ? 0 : 1);
