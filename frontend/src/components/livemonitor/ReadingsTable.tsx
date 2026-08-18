/**
 * The last samples, as numbers.
 *
 * Built from the window already in memory rather than from a request of its
 * own — the charts and the table are two readings of one dataset, so they can
 * never disagree, and showing the table costs nothing.
 *
 * When the window is bucketed the rows are bucket means, and the header says
 * so. A table that silently showed averages under a column headed "corriente"
 * would be the most quietly wrong thing on the page.
 */
import { useState } from "react";

import {
  BORDER,
  BORDER_SOFT,
  SURFACE_SUNK,
  TEXT,
  TEXT_MUTED,
  TEXT_SECONDARY,
  buttonStyle,
  cardStyle,
  labelStyle,
} from "./styles";
import type { Point, Series } from "./types";
import { clockTimeWithDate, fmt } from "./types";

const ROWS = 40;

/**
 * A table row is a point plus the node that produced it.
 *
 * Columns are read by key and may legitimately be absent — the backend omits a
 * series it has no value for — so this indexes rather than enumerating. `fmt`
 * turns `undefined` into "—", which is the honest rendering of "the meter did
 * not report this at that instant".
 */
type Row = Point & { nodeId: string };

export function ReadingsTable({
  series,
  resolutionSeconds,
}: {
  series: Series[];
  resolutionSeconds: number;
}) {
  const [open, setOpen] = useState(false);
  const bucketed = resolutionSeconds > 0;

  const rows: Row[] = series
    .flatMap((entry) => entry.points.map((point) => ({ nodeId: entry.node_id, ...point })))
    .sort((a, b) => (a.t < b.t ? 1 : -1))
    .slice(0, ROWS);

  const head = (text: string) => (
    <th
      style={{
        ...labelStyle,
        textAlign: "right",
        padding: "0 9px 8px 0",
        fontWeight: 500,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </th>
  );

  const cell = (value: number | string | null | undefined, unit: string) => (
    <td
      style={{
        textAlign: "right",
        padding: "5px 9px 5px 0",
        fontSize: 11.5,
        color: TEXT,
        fontVariantNumeric: "tabular-nums",
        whiteSpace: "nowrap",
      }}
    >
      {fmt(typeof value === "number" ? value : null, unit)}
    </td>
  );

  return (
    <div style={{ ...cardStyle, padding: open ? "16px 18px" : "13px 18px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <div>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: TEXT }}>
            Últimas lecturas · valores exactos
          </div>
          <div style={{ fontSize: 10.5, color: TEXT_MUTED, marginTop: 2 }}>
            {bucketed
              ? `Medias de cubetas de ${resolutionSeconds} s — no son muestras individuales`
              : "Muestras tal y como se almacenaron"}
            {` · ${Math.min(rows.length, ROWS)} filas más recientes de la ventana`}
          </div>
        </div>
        <button type="button" style={buttonStyle(open)} onClick={() => setOpen((value) => !value)}>
          {open ? "Ocultar" : "Mostrar"}
        </button>
      </div>

      {open && (
        <div style={{ overflowX: "auto", marginTop: 14 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 780 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${BORDER}` }}>
                <th style={{ ...labelStyle, textAlign: "left", padding: "0 12px 8px 0", fontWeight: 500 }}>
                  Instante
                </th>
                <th style={{ ...labelStyle, textAlign: "left", padding: "0 12px 8px 0", fontWeight: 500 }}>
                  Nodo
                </th>
                {head("Ia A")}
                {head("Ib A")}
                {head("Ic A")}
                {head("Va V")}
                {head("Vb V")}
                {head("Vc V")}
                {head("kW")}
                {head("PF")}
                {head("Hz")}
                {bucketed && head("muestras")}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.nodeId}-${row.t}`} style={{ borderBottom: `1px solid ${BORDER_SOFT}` }}>
                  <td
                    style={{
                      padding: "5px 12px 5px 0",
                      fontSize: 11.5,
                      color: TEXT_SECONDARY,
                      whiteSpace: "nowrap",
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {clockTimeWithDate(row.t)}
                  </td>
                  <td style={{ padding: "5px 12px 5px 0", fontSize: 11.5, color: TEXT_SECONDARY }}>
                    {row.nodeId}
                  </td>
                  {cell(row.ia, "A")}
                  {cell(row.ib, "A")}
                  {cell(row.ic, "A")}
                  {cell(row.va, "V")}
                  {cell(row.vb, "V")}
                  {cell(row.vc, "V")}
                  {cell(row.kw, "kW")}
                  {cell(row.pf, "")}
                  {cell(row.hz, "Hz")}
                  {bucketed && (
                    <td
                      style={{
                        textAlign: "right",
                        padding: "5px 9px 5px 0",
                        fontSize: 11.5,
                        color: TEXT_MUTED,
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {row.n ?? "—"}
                    </td>
                  )}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={12} style={{ padding: "18px 0", fontSize: 12, color: TEXT_MUTED }}>
                    Sin lecturas en esta ventana.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <div style={{ marginTop: 10, fontSize: 10.5, color: TEXT_MUTED, background: SURFACE_SUNK, padding: "7px 10px", borderRadius: 6 }}>
            Los valores se muestran con la misma precisión con la que se almacenaron: 2 decimales en
            tensión, 3 en corriente y frecuencia, 4 en potencia y factor de potencia.
          </div>
        </div>
      )}
    </div>
  );
}
