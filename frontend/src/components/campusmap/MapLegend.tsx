/**
 * The legend, which changes with the mode.
 *
 * In STATUS mode it is the semantic key. In a magnitude mode it is a ramp with
 * its real minimum and maximum, plus an explicit entry for "no measured value
 * in this mode" — the dashed footprints — because an unlabelled absence on a
 * choropleth reads as zero.
 */

import { LEGEND_ORDER, MODE_META, STATUS_META, formatNumber } from "./statusModel";
import { BORDER_SOFT, SURFACE_INNER, TEXT_MUTED, TEXT_SECONDARY } from "./styles";
import type { MapMode, MapStatus } from "./types";
import type { Ramp } from "./statusModel";

interface Props {
  mode: MapMode;
  ramp: Ramp | null;
  /** How many footprints currently carry each status, for the counts. */
  counts: Partial<Record<MapStatus, number>>;
}

const box = (color: string, opacity: number) => ({
  width: 12,
  height: 12,
  borderRadius: 3,
  border: `1px solid ${color}`,
  background: color,
  opacity: Math.max(opacity, 0.35),
  flexShrink: 0,
});

export function MapLegend({ mode, ramp, counts }: Props) {
  return (
    <div
      style={{
        background: SURFACE_INNER,
        border: `1px solid ${BORDER_SOFT}`,
        borderRadius: 8,
        padding: "12px 14px",
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: TEXT_MUTED,
          textTransform: "uppercase",
          letterSpacing: 0.9,
          fontWeight: 600,
          marginBottom: 10,
        }}
      >
        {mode === "status" ? "Leyenda — estado" : `Leyenda — ${MODE_META[mode].label}`}
      </div>

      {mode === "status" ? (
        <div style={{ display: "grid", gap: 7 }}>
          {LEGEND_ORDER.map((status) => {
            const meta = STATUS_META[status];
            const count = counts[status] ?? 0;
            return (
              <div key={status} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={box(meta.color, meta.fillOpacity)} />
                <span style={{ fontSize: 11.5, color: TEXT_SECONDARY, flex: 1 }}>{meta.label}</span>
                <span style={{ fontSize: 11, color: TEXT_MUTED, fontVariantNumeric: "tabular-nums" }}>
                  {count}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ display: "grid", gap: 9 }}>
          {ramp ? (
            <>
              <div style={{ display: "flex", height: 10, borderRadius: 3, overflow: "hidden" }}>
                {ramp.stops.map((stop) => (
                  <span key={stop} style={{ flex: 1, background: stop }} />
                ))}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: TEXT_SECONDARY }}>
                <span>{formatNumber(ramp.min, mode === "power_factor" ? 3 : 2)}</span>
                <span>{formatNumber(ramp.max, mode === "power_factor" ? 3 : 2)}</span>
              </div>
              <div style={{ fontSize: 10.5, color: TEXT_MUTED }}>{MODE_META[mode].unit}</div>
            </>
          ) : (
            <div style={{ fontSize: 11.5, color: TEXT_MUTED }}>
              Ningún edificio de este campus reporta esta magnitud ahora.
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
            <span
              style={{
                width: 12,
                height: 12,
                borderRadius: 3,
                border: "1px dashed #6b7280",
                background: "transparent",
                flexShrink: 0,
              }}
            />
            <span style={{ fontSize: 11.5, color: TEXT_SECONDARY }}>Sin valor medido</span>
          </div>
        </div>
      )}

      <p style={{ fontSize: 10.5, color: TEXT_MUTED, marginTop: 11, lineHeight: 1.5 }}>
        {mode === "status"
          ? "El color indica la salud de la medición, nunca el consumo."
          : "Escala de magnitud. Un consumo alto no es una anomalía."}
      </p>
      <p style={{ fontSize: 10, color: TEXT_MUTED, marginTop: 6, lineHeight: 1.5 }}>
        Huellas de edificio: © OpenStreetMap contributors (ODbL).
      </p>
    </div>
  );
}
