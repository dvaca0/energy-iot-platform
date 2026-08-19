/**
 * What is selected on the map, and how it survives (or does not) a campus change.
 *
 * The selection identity is the **physical** feature — the OSM `type/id` the
 * curated GeoJSON carries — and never an Energy IQ `building_id`. A footprint
 * is selectable whether Energy IQ has zero, one or several buildings behind it;
 * the association is something the panel resolves *after* selection, not a
 * precondition for it. Most footprints on every campus have no association at
 * all, so making selection depend on one would make most of the map dead.
 *
 * The campus is stored alongside the feature so the selection can be *derived*
 * per campus rather than reset by an effect. Deriving means there is never a
 * render in which the panel describes a building belonging to a campus that is
 * no longer on screen.
 */

export interface MapSelection {
  campusId: number;
  featureId: string;
}

/** The feature id to treat as selected while viewing `campusId`. */
export function resolveSelection(
  selection: MapSelection | null,
  campusId: number | null,
): string | null {
  if (!selection || campusId === null) return null;
  return selection.campusId === campusId ? selection.featureId : null;
}

/**
 * The selection to store for a click.
 *
 * `null` clears. Note what is deliberately absent: any check on whether the
 * feature has an Energy IQ building behind it.
 */
export function makeSelection(
  featureId: string | null,
  campusId: number | null,
): MapSelection | null {
  if (featureId === null || campusId === null) return null;
  return { campusId, featureId };
}
