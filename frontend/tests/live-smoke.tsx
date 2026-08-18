/**
 * Live smoke check — NOT part of `make check`.
 *
 * The regression suite uses frozen fixtures so it stays hermetic. This one
 * renders the card against whatever the live backend is returning right now,
 * which is the only way to prove the running platform's real data does not
 * reproduce the outage. Run it against the server, repeatedly, while data
 * updates.
 */
import { renderToStaticMarkup } from "react-dom/server";

import { AIInsightCard } from "../src/App";

const API = process.env.API ?? "http://127.0.0.1:8010/api";

let failures = 0;

async function get(path: string) {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
  return r.json();
}

async function main() {
  const stamp = new Date().toISOString();
  const anomalies = await get("/anomalies?include_resolved=true");
  const list = anomalies.anomalies ?? anomalies;

  const statuses = list.map((a: Record<string, unknown>) => a.status);
  process.stdout.write(
    `  ${stamp}  anomalies=${list.length} statuses=[${statuses.join(",")}] `,
  );

  try {
    const html = renderToStaticMarkup(<AIInsightCard insights={list} />);
    const cards = (html.match(/Anomaly Engine/g) || []).length;
    process.stdout.write(`rendered ok (${html.length} bytes, ${cards} card)\n`);
  } catch (error) {
    failures += 1;
    process.stdout.write(`RENDER THREW ${(error as Error).name}: ${(error as Error).message}\n`);
  }

  // The other collections the dashboard maps over, so a bad record in any of
  // them surfaces here rather than in the browser.
  for (const path of [
    "/dashboard/summary",
    "/nodes",
    "/deployments",
    "/data-explorer/options",
    "/metrics/live",
    "/metrics/buildings",
    "/org/delegations",
    "/org/buildings",
    "/smart-plugs",
  ]) {
    try {
      await get(path);
    } catch (error) {
      failures += 1;
      process.stdout.write(`  FAIL ${path}: ${(error as Error).message}\n`);
    }
  }
}

main()
  .then(() => process.exit(failures === 0 ? 0 : 1))
  .catch((e) => {
    console.error("  FAIL", e);
    process.exit(1);
  });
