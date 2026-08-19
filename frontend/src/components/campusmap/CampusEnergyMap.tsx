/**
 * The Leaflet surface: base tiles, footprints, labels and the viewport.
 *
 * The only component in the module that imports Leaflet. Everything it renders
 * is decided elsewhere — `statusModel` for colour, `geometry` for coordinates,
 * `useCampusMap` for data — which is what keeps the map replaceable and the
 * rules testable in Node, where Leaflet cannot run.
 *
 * The viewport is fitted to the campus's own footprints on every campus change.
 * It is not fitted on every render: doing that would yank the map back to the
 * whole campus each time the 15 s poll returned, undoing whatever the user had
 * just panned to.
 */

import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Polygon, TileLayer, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { BuildingGeoJsonLayer } from "./BuildingGeoJsonLayer";
import { campusBounds, featureCentroid, groundsRings } from "./geometry";
import type { Ramp } from "./statusModel";
import { ACCENT_QUIET, MAP_HEIGHT, TEXT_MUTED, TILE_ATTRIBUTION, TILE_URL } from "./styles";
import type { Footprint, MapBuilding, MapMode } from "./types";

/** Below this, labels are omitted entirely — they would be unreadable clutter. */
const LABEL_MIN_ZOOM = 17;

interface Props {
  features: Footprint[];
  buildingsById: Map<number, MapBuilding>;
  mode: MapMode;
  ramp: Ramp | null;
  valueByFeature: Map<string, number | null>;
  /** Campus property outline, drawn beneath everything and never clickable. */
  grounds: number[][][] | null;
  selectedId: string | null;
  onSelect: (featureId: string | null) => void;
  /** Changes when the campus does; drives exactly one refit. */
  fitKey: string;
  fallbackCenter: [number, number] | null;
  fallbackZoom: number | null;
}

function FitToCampus({
  features,
  grounds,
  fitKey,
  fallbackCenter,
  fallbackZoom,
}: Pick<Props, "features" | "grounds" | "fitKey" | "fallbackCenter" | "fallbackZoom">) {
  const map = useMap();
  useEffect(() => {
    const bounds = campusBounds(features, grounds);
    if (bounds) {
      map.fitBounds(bounds, { padding: [26, 26] });
    } else if (fallbackCenter) {
      map.setView(fallbackCenter, fallbackZoom ?? 16);
    }
    // `fitKey` alone: refit when the campus changes, never when the poll
    // returns a new object for the same campus.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);
  return null;
}

function ZoomWatcher({ onZoom }: { onZoom: (zoom: number) => void }) {
  const map = useMapEvents({ zoomend: () => onZoom(map.getZoom()) });
  useEffect(() => onZoom(map.getZoom()), [map, onZoom]);
  return null;
}

/**
 * Names over the buildings that matter, once the map is close enough.
 *
 * Priority is monitored → registered → selected, and nothing else is labelled.
 * Labelling all 130 footprints of Campus Central would bury the six that carry
 * information.
 */
function BuildingLabels({
  features,
  buildingsById,
  zoom,
  selectedId,
}: {
  features: Footprint[];
  buildingsById: Map<number, MapBuilding>;
  zoom: number;
  selectedId: string | null;
}) {
  const labelled = useMemo(() => {
    return features
      .map((feature) => {
        const linked = feature.properties.energy_iq_building_ids
          .map((id) => buildingsById.get(id))
          .filter((b): b is MapBuilding => Boolean(b));
        const isSelected = feature.id === selectedId;
        if (linked.length === 0 && !isSelected) return null;

        const text = linked[0]?.name ?? feature.properties.osm_name;
        if (!text) return null;
        const centre = featureCentroid(feature);
        if (!centre) return null;
        return { id: feature.id, text, centre, selected: isSelected };
      })
      .filter((entry): entry is NonNullable<typeof entry> => Boolean(entry));
  }, [features, buildingsById, selectedId]);

  if (zoom < LABEL_MIN_ZOOM) return null;

  return (
    <>
      {labelled.map((entry) => (
        <Marker
          key={entry.id}
          position={entry.centre}
          interactive={false}
          keyboard={false}
          icon={L.divIcon({
            className: "campus-map-label",
            html: `<span${entry.selected ? ' data-selected="true"' : ""}>${entry.text.replace(/[<>&]/g, "")}</span>`,
            iconSize: [0, 0],
          })}
        />
      ))}
    </>
  );
}

export function CampusEnergyMap({
  features,
  buildingsById,
  mode,
  ramp,
  valueByFeature,
  grounds,
  selectedId,
  onSelect,
  fitKey,
  fallbackCenter,
  fallbackZoom,
}: Props) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(16);

  const outline = useMemo(() => groundsRings(grounds), [grounds]);

  const initialCentre = useMemo<[number, number]>(() => {
    const bounds = campusBounds(features, grounds);
    if (bounds) {
      return [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2];
    }
    return fallbackCenter ?? [19.2472, -103.7002];
  }, [features, grounds, fallbackCenter]);

  return (
    <div style={{ position: "relative", height: MAP_HEIGHT, borderRadius: 10, overflow: "hidden" }}>
      <MapContainer
        center={initialCentre}
        zoom={fallbackZoom ?? 16}
        scrollWheelZoom
        style={{ height: "100%", width: "100%", background: "#0b0d10" }}
      >
        <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} maxZoom={20} />
        <FitToCampus
          features={features}
          grounds={grounds}
          fitKey={fitKey}
          fallbackCenter={fallbackCenter}
          fallbackZoom={fallbackZoom}
        />
        <ZoomWatcher onZoom={setZoom} />
        <BaseClickHandler onClear={() => onSelect(null)} />
        {outline.length > 0 && (
          <Polygon
            positions={outline}
            interactive={false}
            pathOptions={{
              color: ACCENT_QUIET,
              weight: 1.2,
              opacity: 0.45,
              dashArray: "6 6",
              fill: false,
            }}
          />
        )}
        <BuildingGeoJsonLayer
          features={features}
          buildingsById={buildingsById}
          mode={mode}
          ramp={ramp}
          selectedId={selectedId}
          hoveredId={hoveredId}
          onSelect={onSelect}
          onHover={setHoveredId}
          valueByFeature={valueByFeature}
        />
        <BuildingLabels
          features={features}
          buildingsById={buildingsById}
          zoom={zoom}
          selectedId={selectedId}
        />
      </MapContainer>

      {zoom < LABEL_MIN_ZOOM && (
        <div
          style={{
            position: "absolute",
            left: 12,
            bottom: 12,
            zIndex: 500,
            fontSize: 10.5,
            color: TEXT_MUTED,
            background: "#0e1114cc",
            border: "1px solid #1e2227",
            borderRadius: 5,
            padding: "4px 8px",
            pointerEvents: "none",
          }}
        >
          Acerca el mapa para ver los nombres de los edificios
        </div>
      )}
    </div>
  );
}

function BaseClickHandler({ onClear }: { onClear: () => void }) {
  useMapEvents({ click: () => onClear() });
  return null;
}
