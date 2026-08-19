/**
 * The footprint layer — the map's main interaction surface.
 *
 * Each feature is a `<Polygon>` rather than one big `<GeoJSON>` layer. That is
 * a deliberate trade: a GeoJSON layer restyles imperatively through
 * `setStyle`, which means selection, hover and mode changes all have to be
 * pushed into Leaflet by hand and can drift out of sync with React state. As
 * discrete polygons the style is a pure function of props, which is also what
 * makes `polygonStyle` testable on its own.
 *
 * Unmonitored footprints are drawn first so that a monitored building is never
 * hidden underneath a neighbour when outlines overlap.
 */

import { Polygon, Tooltip } from "react-leaflet";

import { BuildingTooltip } from "./BuildingTooltip";
import { featureRings } from "./geometry";
import { polygonStyle } from "./statusModel";
import type { Ramp } from "./statusModel";
import type { Footprint, MapBuilding, MapMode } from "./types";

interface Props {
  features: Footprint[];
  buildingsById: Map<number, MapBuilding>;
  mode: MapMode;
  ramp: Ramp | null;
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (featureId: string) => void;
  onHover: (featureId: string | null) => void;
  /** The value each feature contributes in the current magnitude mode. */
  valueByFeature: Map<string, number | null>;
}

export function BuildingGeoJsonLayer({
  features,
  buildingsById,
  mode,
  ramp,
  selectedId,
  hoveredId,
  onSelect,
  onHover,
  valueByFeature,
}: Props) {
  const ordered = [...features].sort((a, b) => {
    const aMapped = a.properties.energy_iq_building_ids.length > 0 ? 1 : 0;
    const bMapped = b.properties.energy_iq_building_ids.length > 0 ? 1 : 0;
    if (aMapped !== bMapped) return aMapped - bMapped;
    return a.id === selectedId ? 1 : b.id === selectedId ? -1 : 0;
  });

  return (
    <>
      {ordered.map((feature) => {
        const rings = featureRings(feature);
        if (rings.length === 0) return null;

        const linked = feature.properties.energy_iq_building_ids
          .map((id) => buildingsById.get(id))
          .filter((b): b is MapBuilding => Boolean(b));

        const style = polygonStyle({
          status: feature.properties.map_status,
          mode,
          value: valueByFeature.get(feature.id) ?? null,
          ramp,
          selected: feature.id === selectedId,
          hovered: feature.id === hoveredId,
        });

        return (
          <Polygon
            key={feature.id}
            positions={rings.length === 1 ? rings[0] : rings}
            pathOptions={style}
            eventHandlers={{
              click: () => onSelect(feature.id),
              mouseover: () => onHover(feature.id),
              mouseout: () => onHover(null),
            }}
          >
            <Tooltip sticky opacity={1} className="campus-map-tooltip">
              <BuildingTooltip feature={feature.properties} buildings={linked} />
            </Tooltip>
          </Polygon>
        );
      })}
    </>
  );
}
