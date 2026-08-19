/**
 * Which quantity the polygons are coloured by.
 *
 * STATUS is the default and the only mode that carries judgement. The other
 * four are magnitudes on a neutral ramp — see the note at the top of
 * `statusModel.ts` for why they are kept apart.
 *
 * Adding a mode is a two-line change: a key in `MapMode`, an entry in
 * `MODE_META`, and a case in `modeValue`. Nothing here needs touching.
 */

import { MODE_META } from "./statusModel";
import { ACCENT, BORDER, SURFACE_INNER, TEXT, TEXT_MUTED } from "./styles";
import type { MapMode } from "./types";

const ORDER: MapMode[] = ["status", "power", "energy", "cost", "power_factor"];

interface Props {
  value: MapMode;
  onChange: (mode: MapMode) => void;
  /** Modes with nothing to draw are shown disabled rather than removed. */
  availability: Record<MapMode, boolean>;
}

export function MapModeSelector({ value, onChange, availability }: Props) {
  return (
    <div>
      <div
        role="group"
        aria-label="Modo de visualización del mapa"
        style={{
          display: "inline-flex",
          background: SURFACE_INNER,
          border: `1px solid ${BORDER}`,
          borderRadius: 7,
          padding: 3,
          gap: 2,
          flexWrap: "wrap",
        }}
      >
        {ORDER.map((mode) => {
          const active = mode === value;
          const enabled = availability[mode];
          return (
            <button
              key={mode}
              type="button"
              onClick={() => enabled && onChange(mode)}
              disabled={!enabled}
              aria-pressed={active}
              title={enabled ? MODE_META[mode].hint : "Sin datos para este modo en este campus"}
              style={{
                background: active ? ACCENT : "transparent",
                color: active ? "#fff" : enabled ? TEXT : TEXT_MUTED,
                border: "none",
                borderRadius: 5,
                padding: "6px 12px",
                fontSize: 12,
                fontWeight: active ? 600 : 500,
                cursor: enabled ? "pointer" : "not-allowed",
                opacity: enabled ? 1 : 0.45,
              }}
            >
              {MODE_META[mode].label}
            </button>
          );
        })}
      </div>
      <p style={{ fontSize: 11, color: TEXT_MUTED, marginTop: 7, maxWidth: 620, lineHeight: 1.5 }}>
        {MODE_META[value].hint}
      </p>
    </div>
  );
}
