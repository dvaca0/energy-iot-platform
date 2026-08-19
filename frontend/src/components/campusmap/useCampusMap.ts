/**
 * Data for the Campus Map: campus list, per-campus geometry and state, and the
 * campus totals the platform already computes elsewhere.
 *
 * All fetching lives here so the map components stay presentational. Three
 * behaviours worth knowing:
 *
 * **The selected campus is chosen, not hardcoded.** On first load it picks the
 * first campus that has both geometry and a mapped building, then the first
 * with geometry, then simply the first — so the page opens on something useful
 * without Campus Central being written into the code.
 *
 * **A failed campus load does not clear the campus list.** The selector has to
 * keep working so the user can pick a different one; that is what makes a
 * missing GeoJSON degrade instead of dead-ending.
 *
 * **Polling refreshes state, never geometry-driven view.** The 15 s tick
 * matches the old card page. It replaces the payload; the map's viewport and
 * the selected building are component state and survive it.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { getCampusMap, getCampusMapCampuses, getCampusMetrics } from "../../services/api";
import type { CampusMapPayload, CampusMetrics, CampusOption } from "./types";

const REFRESH_MS = 15000;

export interface CampusMapData {
  campuses: CampusOption[];
  campusId: number | null;
  setCampusId: (id: number) => void;
  payload: CampusMapPayload | null;
  metrics: CampusMetrics | null;
  loading: boolean;
  /** Set when the campus payload failed. The selector stays usable. */
  error: string | null;
  refresh: () => void;
}

function preferredCampus(campuses: CampusOption[]): number | null {
  if (campuses.length === 0) return null;
  const mapped = campuses.find((c) => c.has_geometry && c.mapped_buildings > 0);
  if (mapped) return mapped.id;
  const traced = campuses.find((c) => c.has_geometry);
  if (traced) return traced.id;
  return campuses[0].id;
}

export function useCampusMap(): CampusMapData {
  const [campuses, setCampuses] = useState<CampusOption[]>([]);
  const [campusesLoaded, setCampusesLoaded] = useState(false);
  const [campusId, setCampusId] = useState<number | null>(null);
  const [tick, setTick] = useState(0);

  // The payload carries the campus it belongs to. Keeping them in one piece of
  // state is what lets `loading` be derived rather than toggled from inside an
  // effect, and it makes a stale response for the previous campus impossible to
  // render: the id would not match.
  const [result, setResult] = useState<{
    campusId: number;
    payload: CampusMapPayload | null;
    metrics: CampusMetrics | null;
    error: string | null;
  } | null>(null);

  // Guards against a slow response for campus A landing after the user has
  // already switched to campus B.
  const requested = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCampusMapCampuses()
      .then((data) => {
        if (cancelled) return;
        const list: CampusOption[] = data?.campuses || [];
        setCampuses(list);
        setCampusId((current) => current ?? preferredCampus(list));
        setCampusesLoaded(true);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("Campus map campuses API error:", err);
        setCampuses([]);
        setCampusesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (campusId === null) return;
    let cancelled = false;
    requested.current = campusId;

    Promise.allSettled([getCampusMap(campusId), getCampusMetrics()]).then(
      ([mapResult, metricsResult]) => {
        if (cancelled || requested.current !== campusId) return;

        let payload: CampusMapPayload | null = null;
        let error: string | null = null;
        if (mapResult.status === "fulfilled") {
          payload = mapResult.value;
        } else {
          console.error("Campus map API error:", mapResult.reason);
          error = "No fue posible cargar el mapa de este campus.";
        }

        let metrics: CampusMetrics | null = null;
        if (metricsResult.status === "fulfilled") {
          const rows: CampusMetrics[] = metricsResult.value?.campuses || [];
          metrics = rows.find((row) => row.id === campusId) ?? null;
        } else {
          // Totals are a nice-to-have; the map itself is not blocked by them.
          console.error("Campus metrics API error:", metricsResult.reason);
        }

        setResult({ campusId, payload, metrics, error });
      },
    );

    return () => {
      cancelled = true;
    };
  }, [campusId, tick]);

  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  const refresh = useCallback(() => setTick((n) => n + 1), []);
  const current = result && result.campusId === campusId ? result : null;

  return {
    campuses,
    campusId,
    setCampusId,
    payload: current?.payload ?? null,
    metrics: current?.metrics ?? null,
    loading: !campusesLoaded || (campusId !== null && current === null),
    error: campusesLoaded && campuses.length === 0
      ? "No fue posible cargar la lista de campus."
      : (current?.error ?? null),
    refresh,
  };
}
