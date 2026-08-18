/**
 * One chart, one magnitude.
 *
 * Magnitudes are never mixed on a shared axis. Volts and amps on one plot make
 * the smaller of the two unreadable and invite a comparison that has no
 * physical meaning, so each quantity gets its own card even though that costs
 * vertical space.
 *
 * Two identification rules make a line unambiguous no matter how many are drawn:
 * hue carries the **phase**, dash pattern carries the **node**, and every legend
 * entry is written as NODE · PHASE. A technician reading a crossing pair can
 * always tell whether they are looking at two phases of one node or the same
 * phase of two nodes.
 */
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  BORDER,
  BORDER_SOFT,
  CHART_GRID,
  NODE_COLORS,
  NODE_DASH,
  OK,
  PHASE_COLORS,
  WARN,
  SURFACE_INNER,
  TEXT,
  TEXT_MUTED,
  TEXT_SECONDARY,
  TOTAL_COLOR,
  cardStyle,
  labelStyle,
  tooltipStyle,
} from "./styles";
import type { ChartSpec, NodeSnapshot, Point, Series } from "./types";
import { fmt, fmtAxis, fmtUnit, nodeSupports } from "./types";

interface DrawnLine {
  /** Column name in the flattened dataset. */
  field: string;
  /** What the legend and the tooltip call it: NODE · PHASE. */
  label: string;
  color: string;
  dash: string;
  nodeId: string;
}

interface Props {
  spec: ChartSpec;
  series: Series[];
  nodes: NodeSnapshot[];
  perPhase: boolean;
  resolutionSeconds: number;
  paused: boolean;
}

function epoch(iso: string): number {
  return Date.parse(iso.endsWith("Z") ? iso : `${iso}Z`);
}

/**
 * Flatten the per-node series into rows keyed by instant.
 *
 * Nodes sample independently, so their timestamps rarely coincide on
 * un-bucketed ranges; the union leaves a null in every column that did not
 * report at that instant, and `connectNulls` bridges it. That is honest here —
 * the gap is "this node did not sample at this millisecond", not "this node
 * measured nothing" — while a genuinely absent metric never reaches this
 * function at all, because its node is filtered out upstream.
 */
function flatten(
  series: Series[],
  lines: DrawnLine[],
  keyOf: (nodeId: string, key: string) => string,
  derive?: (point: Point) => number | null,
) {
  const rows = new Map<number, Record<string, number | null>>();

  for (const entry of series) {
    for (const point of entry.points) {
      const ts = epoch(point.t);
      let row = rows.get(ts);
      if (!row) {
        row = { ts };
        rows.set(ts, row);
      }
      for (const line of lines) {
        if (line.nodeId !== entry.node_id) continue;
        const raw = line.field.split("|")[1];
        // A derived chart has no stored column behind it: the value is computed
        // from this point's own measured inputs, and comes back null the moment
        // either input is missing. That is why a derived series simply stops
        // rather than interpolating across the gap.
        const value = derive ? derive(point) : point[raw];
        row[line.field] = typeof value === "number" ? value : null;
      }
      if (point.n !== undefined) row[keyOf(entry.node_id, "n")] = point.n;
    }
  }

  return Array.from(rows.values()).sort((a, b) => (a.ts as number) - (b.ts as number));
}

function ExactTooltip({
  active,
  payload,
  label,
  unit,
  lines,
  bucketed,
}: {
  active?: boolean;
  payload?: { dataKey: string; value: number | null; payload: Record<string, number | null> }[];
  label?: number;
  unit: string;
  lines: DrawnLine[];
  bucketed: boolean;
}) {
  if (!active || !payload || payload.length === 0 || label === undefined) return null;

  const when = new Date(label);
  const byField = new Map(lines.map((line) => [line.field, line]));
  const row = payload[0]?.payload ?? {};

  // Samples behind the point, when the window is bucketed. Shown because a
  // reader must be able to tell a measurement from a mean of twenty.
  const counts = Object.entries(row)
    .filter(([key]) => key.endsWith("|n"))
    .map(([, value]) => value)
    .filter((value): value is number => typeof value === "number");

  return (
    <div style={tooltipStyle}>
      <div style={{ fontSize: 11.5, color: TEXT, fontWeight: 600, marginBottom: 6 }}>
        {when.toLocaleTimeString("es-MX", { hour12: false })}
        <span style={{ color: TEXT_MUTED, fontWeight: 400, marginLeft: 6 }}>
          {when.toLocaleDateString("es-MX", { day: "2-digit", month: "short" })}
        </span>
      </div>
      {payload.map((entry) => {
        const line = byField.get(entry.dataKey);
        if (!line) return null;
        return (
          <div
            key={entry.dataKey}
            style={{ display: "flex", justifyContent: "space-between", gap: 18, lineHeight: 1.65 }}
          >
            <span style={{ color: line.color, fontSize: 11.5 }}>{line.label}</span>
            <span style={{ color: TEXT, fontVariantNumeric: "tabular-nums", fontSize: 11.5 }}>
              {fmtUnit(entry.value, unit)}
            </span>
          </div>
        );
      })}
      {bucketed && counts.length > 0 && (
        <div style={{ marginTop: 6, paddingTop: 5, borderTop: `1px solid ${BORDER}`, fontSize: 10.5, color: TEXT_MUTED }}>
          media de {Math.max(...counts)} muestra{Math.max(...counts) === 1 ? "" : "s"}
        </div>
      )}
    </div>
  );
}

export function SeriesChart({ spec, series, nodes, perPhase, resolutionSeconds, paused }: Props) {
  const keyOf = (nodeId: string, key: string) => `${nodeId}|${key}`;
  const bucketed = resolutionSeconds > 0;

  // A node is drawn only if it actually reports this magnitude. The alternative
  // — plotting it as zero — is the single most misleading thing this page could
  // do, because a dead sensor and a de-energised panel would look identical.
  const eligible = nodes.filter((node) => nodeSupports(node, spec));
  const unavailable = nodes.filter((node) => !nodeSupports(node, spec));

  const definitions = perPhase || spec.totals.length === 0 ? spec.phases : spec.totals;
  const multiNode = eligible.length > 1;

  const lines: DrawnLine[] = [];
  eligible.forEach((node, nodeIndex) => {
    for (const definition of definitions) {
      lines.push({
        field: keyOf(node.node_id, definition.key as string),
        label: multiNode ? `${node.node_id} · ${definition.label}` : definition.label,
        // With one node on screen the phase palette identifies the line. With
        // several, a total-only chart has no phase to colour by, so the node
        // becomes the hue instead.
        color:
          definition.phase !== null
            ? PHASE_COLORS[definition.phase]
            : multiNode
              ? NODE_COLORS[nodeIndex % NODE_COLORS.length]
              : TOTAL_COLOR,
        dash: multiNode && definition.phase !== null ? NODE_DASH[nodeIndex % NODE_DASH.length] : "",
        nodeId: node.node_id,
      });
    }
  });

  const drawn = series.filter((entry) => eligible.some((node) => node.node_id === entry.node_id));
  const data = flatten(drawn, lines, keyOf, spec.derived?.compute);
  const latest = data.length ? (data[data.length - 1].ts as number) : null;

  const currentValues = lines.map((line) => {
    for (let index = data.length - 1; index >= 0; index -= 1) {
      const value = data[index][line.field];
      if (value !== null && value !== undefined) return { line, value };
    }
    return { line, value: null as number | null };
  });

  const empty = data.length === 0 || lines.length === 0;

  return (
    <div style={{ ...cardStyle, padding: "15px 16px 10px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 10,
        }}
      >
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 12.5,
              fontWeight: 600,
              color: TEXT,
              letterSpacing: -0.1,
            }}
          >
            {spec.title}
            {spec.unit && (
              <span style={{ color: TEXT_MUTED, fontWeight: 400 }}>
                {" · "}
                {spec.unit === "kWh_reg" ? "kWh" : spec.unit}
              </span>
            )}
            {/* Arithmetic, not an instrument reading. The badge sits beside the
                title rather than in a footnote so it cannot be missed while
                reading the line. */}
            {spec.derived && (
              <span
                style={{
                  fontSize: 9.5,
                  fontWeight: 600,
                  letterSpacing: 0.6,
                  color: WARN,
                  background: `${WARN}14`,
                  border: `1px solid ${WARN}33`,
                  borderRadius: 3,
                  padding: "1.5px 5px",
                  whiteSpace: "nowrap",
                }}
              >
                CALCULADO
              </span>
            )}
            {/* Where the live edge is, in words. The same instant is marked on
                the plot, but the plot is only readable once it has been drawn —
                this is legible immediately, and on an empty or narrow chart. */}
            {latest !== null && (
              <span
                style={{
                  fontSize: 9.5,
                  fontWeight: 500,
                  letterSpacing: 0.5,
                  color: paused ? TEXT_MUTED : OK,
                  background: `${paused ? TEXT_MUTED : OK}14`,
                  border: `1px solid ${paused ? TEXT_MUTED : OK}33`,
                  borderRadius: 3,
                  padding: "1.5px 5px",
                  whiteSpace: "nowrap",
                }}
              >
                {paused ? "PAUSA" : "AHORA"}{" "}
                {new Date(latest).toLocaleTimeString("es-MX", { hour12: false })}
              </span>
            )}
          </div>
          {(spec.note || spec.derived) && (
            <div style={{ fontSize: 10.5, color: TEXT_MUTED, marginTop: 3, maxWidth: 470 }}>
              {spec.derived?.explanation}
              {spec.derived && spec.note ? " " : ""}
              {spec.note}
            </div>
          )}
        </div>

        {/* Current value per line — the "now" reading, next to its own colour,
            so the newest number is legible without hunting for the last pixel. */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          {currentValues.map(({ line, value }) => (
            <div
              key={line.field}
              style={{
                background: SURFACE_INNER,
                border: `1px solid ${BORDER_SOFT}`,
                borderRadius: 6,
                padding: "4px 8px",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 2,
                  background: line.color,
                  borderRadius: 1,
                  display: "inline-block",
                  opacity: line.dash ? 0.55 : 1,
                }}
              />
              <span style={{ fontSize: 10.5, color: TEXT_MUTED }}>{line.label}</span>
              <span
                style={{
                  fontSize: 11.5,
                  color: TEXT,
                  fontWeight: 600,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {fmt(value, spec.unit)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {empty ? (
        <div style={{ padding: "34px 0 40px", textAlign: "center", fontSize: 12, color: TEXT_MUTED }}>
          Sin datos en esta ventana
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={210}>
          <LineChart data={data} margin={{ top: 4, right: 8, left: -6, bottom: 0 }}>
            <CartesianGrid stroke={CHART_GRID} strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(value: number) =>
                new Date(value).toLocaleTimeString("es-MX", {
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: false,
                })
              }
              stroke={TEXT_MUTED}
              tick={{ fontSize: 10.5, fill: TEXT_MUTED }}
              tickLine={false}
              axisLine={{ stroke: BORDER_SOFT }}
              minTickGap={44}
            />
            <YAxis
              domain={spec.zeroBaseline ? [0, "auto"] : ["auto", "auto"]}
              tickFormatter={(value: number) => fmtAxis(value, spec.unit)}
              stroke={TEXT_MUTED}
              tick={{ fontSize: 10.5, fill: TEXT_MUTED }}
              tickLine={false}
              axisLine={false}
              width={52}
            />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: TEXT_MUTED, strokeWidth: 1, strokeDasharray: "3 3" }}
              content={
                <ExactTooltip unit={spec.unit} lines={lines} bucketed={bucketed} />
              }
            />
            {/* Where "now" is. The newest sample in the window, marked on every
                chart so the live edge is never mistaken for the end of the axis. */}
            {latest !== null && (
              <ReferenceLine
                x={latest}
                stroke={paused ? TEXT_MUTED : OK}
                strokeDasharray="3 3"
                strokeOpacity={0.75}
                label={{
                  value: paused ? "PAUSA" : "AHORA",
                  position: "insideTopRight",
                  fill: paused ? TEXT_MUTED : OK,
                  fontSize: 9.5,
                  letterSpacing: 0.5,
                }}
              />
            )}
            {lines.map((line) => (
              <Line
                key={line.field}
                type="monotone"
                dataKey={line.field}
                name={line.label}
                stroke={line.color}
                strokeWidth={1.7}
                strokeDasharray={line.dash || undefined}
                dot={false}
                activeDot={{ r: 3, strokeWidth: 0 }}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}

      {unavailable.length > 0 && (
        <div style={{ ...labelStyle, marginTop: 4, paddingBottom: 4, color: TEXT_SECONDARY }}>
          No disponible en {unavailable.map((node) => node.node_id).join(", ")} — este nodo no
          reporta esta magnitud
        </div>
      )}
    </div>
  );
}
