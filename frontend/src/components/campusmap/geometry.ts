/**
 * GeoJSON → Leaflet coordinate plumbing.
 *
 * GeoJSON positions are `[lon, lat]`; Leaflet takes `[lat, lng]`. Getting that
 * backwards puts Colima in the Indian Ocean, so the swap happens in exactly one
 * place. Pure functions, no Leaflet import — they are just array maths, and
 * they are unit-testable because of it.
 */

import type { Footprint } from "./types";

export type LatLng = [number, number];

/** Every outer ring of a feature, as Leaflet positions. */
export function featureRings(feature: Footprint): LatLng[][] {
  const geometry = feature.geometry;
  const swap = (ring: number[][]): LatLng[] => ring.map(([lon, lat]) => [lat, lon]);

  if (geometry.type === "Polygon") {
    return (geometry.coordinates as number[][][]).map(swap);
  }
  if (geometry.type === "MultiPolygon") {
    return (geometry.coordinates as number[][][][]).flatMap((polygon) => polygon.map(swap));
  }
  return [];
}

/**
 * Area centroid of the first ring — where a label goes.
 *
 * **The ring is translated to its own first vertex before the shoelace sum.**
 * At Colima's coordinates the untranslated form is numerically worthless: each
 * term is `x0*y1 - x1*y0` with both products near -1969, while their
 * difference for a 20 m building is about 1e-8. Eleven of a double's sixteen
 * digits cancel and what remains is noise, which put labels hundreds of metres
 * from their buildings. The Python curation script had the identical bug and
 * carries the same note.
 *
 * Falls back to the vertex mean for a degenerate ring so a malformed footprint
 * yields a slightly-off label rather than `NaN`, which Leaflet would throw on.
 */
export function ringCentroid(ring: LatLng[]): LatLng | null {
  if (ring.length < 3) return null;
  const [originLat, originLng] = ring[0];
  let area = 0;
  let lat = 0;
  let lng = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const ax = ring[i][1] - originLng;
    const ay = ring[i][0] - originLat;
    const bx = ring[i + 1][1] - originLng;
    const by = ring[i + 1][0] - originLat;
    const cross = ax * by - bx * ay;
    area += cross;
    lng += (ax + bx) * cross;
    lat += (ay + by) * cross;
  }

  // Degeneracy is judged against the ring's own extent: a fixed epsilon large
  // enough to catch a collapsed ring would also catch a real small building,
  // whose translated shoelace sum is only about 1e-9.
  const lats = ring.map((p) => p[0]);
  const lngs = ring.map((p) => p[1]);
  const spanArea = (Math.max(...lats) - Math.min(...lats)) * (Math.max(...lngs) - Math.min(...lngs));
  if (Math.abs(area) < 1e-6 * Math.max(spanArea, 1e-18)) {
    return [
      ring.reduce((sum, p) => sum + p[0], 0) / ring.length,
      ring.reduce((sum, p) => sum + p[1], 0) / ring.length,
    ];
  }
  area *= 0.5;
  return [originLat + lat / (6 * area), originLng + lng / (6 * area)];
}

export function featureCentroid(feature: Footprint): LatLng | null {
  const rings = featureRings(feature);
  return rings.length > 0 ? ringCentroid(rings[0]) : null;
}

/** The campus outline's rings, swapped to Leaflet order. */
export function groundsRings(grounds: number[][][] | null | undefined): LatLng[][] {
  if (!grounds) return [];
  return grounds.map((ring) => ring.map(([lon, lat]) => [lat, lon] as LatLng));
}

/**
 * What the viewport should frame: the campus outline together with its
 * buildings.
 *
 * The outline is included rather than ignored because some sites have very few
 * traced buildings and one — the Santiago bachillerato — has none at all.
 * Fitting to footprints alone would frame three rooftops, or nothing.
 */
export function campusBounds(
  features: Footprint[],
  grounds: number[][][] | null | undefined,
): [LatLng, LatLng] | null {
  const fromFeatures = collectionBounds(features);
  const fromGrounds = ringsBounds(groundsRings(grounds));
  if (!fromFeatures) return fromGrounds;
  if (!fromGrounds) return fromFeatures;
  return [
    [Math.min(fromFeatures[0][0], fromGrounds[0][0]), Math.min(fromFeatures[0][1], fromGrounds[0][1])],
    [Math.max(fromFeatures[1][0], fromGrounds[1][0]), Math.max(fromFeatures[1][1], fromGrounds[1][1])],
  ];
}

export function ringsBounds(rings: LatLng[][]): [LatLng, LatLng] | null {
  let south = Infinity;
  let west = Infinity;
  let north = -Infinity;
  let east = -Infinity;
  for (const ring of rings) {
    for (const [lat, lng] of ring) {
      if (lat < south) south = lat;
      if (lat > north) north = lat;
      if (lng < west) west = lng;
      if (lng > east) east = lng;
    }
  }
  if (!Number.isFinite(south) || !Number.isFinite(west)) return null;
  return [
    [south, west],
    [north, east],
  ];
}

/** `[[southLat, westLng], [northLat, eastLng]]`, or `null` for no features. */
export function collectionBounds(features: Footprint[]): [LatLng, LatLng] | null {
  let south = Infinity;
  let west = Infinity;
  let north = -Infinity;
  let east = -Infinity;

  for (const feature of features) {
    for (const ring of featureRings(feature)) {
      for (const [lat, lng] of ring) {
        if (lat < south) south = lat;
        if (lat > north) north = lat;
        if (lng < west) west = lng;
        if (lng > east) east = lng;
      }
    }
  }

  if (!Number.isFinite(south) || !Number.isFinite(west)) return null;
  return [
    [south, west],
    [north, east],
  ];
}
