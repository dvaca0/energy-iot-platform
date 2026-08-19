/**
 * Campus picker. Driven entirely by `/api/campus-map/campuses`, which is driven
 * by the `campuses` table — no campus is written into this file.
 *
 * A campus with no traced geometry is listed and selectable, marked "sin
 * geometría". Hiding it would make the map quietly disagree with the rest of
 * the platform about which campuses exist.
 */

import type { CampusOption } from "./types";
import { BORDER, SURFACE_INNER, TEXT, TEXT_MUTED } from "./styles";

interface Props {
  campuses: CampusOption[];
  value: number | null;
  onChange: (id: number) => void;
}

export function CampusSelector({ campuses, value, onChange }: Props) {
  const selected = campuses.find((c) => c.id === value) ?? null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
      <label
        htmlFor="campus-map-selector"
        style={{
          fontSize: 10.5,
          color: TEXT_MUTED,
          textTransform: "uppercase",
          letterSpacing: 0.9,
          fontWeight: 600,
        }}
      >
        Campus
      </label>
      <select
        id="campus-map-selector"
        value={value ?? ""}
        onChange={(event) => onChange(Number(event.target.value))}
        style={{
          background: SURFACE_INNER,
          color: TEXT,
          border: `1px solid ${BORDER}`,
          borderRadius: 6,
          padding: "8px 11px",
          fontSize: 13,
          minWidth: 230,
        }}
      >
        {campuses.length === 0 && <option value="">Sin campus disponibles</option>}
        {campuses.map((campus) => (
          <option key={campus.id} value={campus.id}>
            {campus.name}
            {campus.has_geometry ? "" : " — sin geometría"}
          </option>
        ))}
      </select>

      {selected && (
        <span style={{ fontSize: 11.5, color: TEXT_MUTED }}>
          {selected.delegation} · {selected.footprint_count} huellas OSM ·{" "}
          {selected.mapped_buildings}/{selected.energy_iq_buildings} edificios Energy IQ ubicados
        </span>
      )}
    </div>
  );
}
