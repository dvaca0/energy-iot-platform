/**
 * The hover card. Deliberately three lines at most.
 *
 * Hover answers "what is this and is it being watched"; everything else waits
 * for a click. It is rendered as plain markup so it can be used inside a
 * Leaflet `Tooltip` and in tests without a map.
 */

import { displayName, formatNumber, statusAccent, statusCaption } from "./statusModel";
import { TEXT, TEXT_MUTED } from "./styles";
import type { FootprintProperties, MapBuilding } from "./types";

interface Props {
  feature: FootprintProperties;
  buildings: MapBuilding[];
}

export function BuildingTooltip({ feature, buildings }: Props) {
  const primary = buildings[0] ?? null;
  // Same name priority as the panel, from the one place that defines it.
  const title = displayName(feature, buildings);

  return (
    <div style={{ minWidth: 150, lineHeight: 1.45 }}>
      <div style={{ fontSize: 12.5, fontWeight: 600, color: TEXT }}>{title}</div>

      {primary && primary.telemetry.is_live && primary.latest_reading?.power_kw !== null && (
        <div style={{ fontSize: 14, fontWeight: 600, color: statusAccent(primary.map_status) }}>
          {formatNumber(primary.latest_reading?.power_kw ?? null, 2, "kW")}
        </div>
      )}

      <div style={{ fontSize: 11, color: TEXT_MUTED }}>
        {primary ? statusCaption(primary) : "Sin monitoreo"}
      </div>

      {buildings.length > 1 && (
        <div style={{ fontSize: 10.5, color: TEXT_MUTED }}>
          {buildings.length} edificios Energy IQ en esta huella
        </div>
      )}
    </div>
  );
}
