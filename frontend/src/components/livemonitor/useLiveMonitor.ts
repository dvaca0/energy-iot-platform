/**
 * Data plumbing for the live technical view.
 *
 * The page has to feel live and stay open all day, and those two goals pull
 * against each other. The resolution is to treat the instantaneous snapshot and
 * the historical window as separate resources with separate cadences:
 *
 * - **Snapshot** — ~5 KB, refetched every `SNAPSHOT_MS`. Cheap enough to poll.
 * - **History, un-bucketed ranges** — fetched once in full, then *extended*
 *   with `?since=`, which returns only the samples that appeared since the last
 *   tick (typically one or two points, a few hundred bytes). The window is
 *   trimmed client-side, so memory is bounded by the range, not by uptime.
 * - **History, bucketed ranges** — a bucket's mean changes while the bucket
 *   fills, so an incremental slice would hand back averages the client could
 *   never correct. Those ranges refetch the whole window on the slower
 *   `SLOW_HISTORY_MS` cadence instead.
 *
 * Three further rules keep a long-lived tab from degrading:
 *
 * **One request at a time per resource.** A tick that arrives while the
 * previous fetch is still open is dropped, so a slow backend produces a slower
 * page rather than an ever-growing queue of overlapping requests.
 *
 * **A hidden tab polls nothing.** Returning to it triggers a full refetch, so
 * the technician never reads a window that silently stopped advancing.
 *
 * **Pause stops the polling, not the platform.** It freezes what is on screen
 * so a point can be inspected. Nothing about the collector, the buffer or the
 * node's own acquisition is affected — the page is a reader.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getLiveHistory, getLiveSnapshot } from "../../services/api";
import type { History, Point, Range, Series, Snapshot } from "./types";
import { RANGES, RAW_RANGES } from "./types";

export const SNAPSHOT_MS = 3000;
/** Floor for windows that must be refetched whole. */
export const SLOW_HISTORY_MS = 30000;
/** Ceiling, so even the widest window still refreshes while someone watches. */
export const MAX_HISTORY_MS = 300000;

/**
 * How often a bucketed window is worth refetching.
 *
 * Paced to the bucket, not to the clock. A point that averages five minutes of
 * samples cannot change meaningfully in three seconds, and a point that
 * averages an hour changes once an hour — so refetching either at the snapshot
 * cadence spends real backend time redrawing an identical line.
 *
 * That time is not free here. The backend runs a single worker, and the widest
 * window (a 65-day deployment across three nodes) costs ~1.9 s, of which ~1.4 s
 * is the energy service resolving measurement eras with a window function over
 * 300,000 readings. Refetching that every 30 s would put one chart at 6 % of the
 * whole backend; at a quarter of the bucket width it is well under 1 %, and the
 * chart is no less current because the data behind it did not move.
 */
export function historyIntervalMs(bucketSeconds: number): number {
  if (bucketSeconds <= 0) return SNAPSHOT_MS;
  return Math.min(MAX_HISTORY_MS, Math.max(SLOW_HISTORY_MS, (bucketSeconds * 1000) / 4));
}

/**
 * The trim horizon comes from the server, not from a table here.
 *
 * There used to be a `Record<Range, number>` of window lengths, which worked
 * only while every range was "now minus a fixed span". The deployment range is
 * not: its bounds are the campaign's own `activated_at`/`closed_at`, which the
 * client cannot know. Reading `window_start` off the response makes the client
 * agree with the server by construction, and removes a second place where a new
 * range has to be registered.
 */
function trimHorizon(history: History): number {
  const parsed = Date.parse(
    history.window_start.endsWith("Z") ? history.window_start : `${history.window_start}Z`,
  );
  return Number.isNaN(parsed) ? 0 : parsed;
}

export interface Perf {
  requests: number;
  lastSnapshotMs: number | null;
  lastHistoryMs: number | null;
  lastHistoryBytes: number | null;
  points: number;
}

function mergeSeries(previous: Series[], incoming: Series[], cutoffMs: number): Series[] {
  const byNode = new Map(previous.map((series) => [series.node_id, series]));

  return incoming.map((series) => {
    const held = byNode.get(series.node_id);
    if (!held) return series;

    // The watermark is the newest point already held, so the server never
    // returns a duplicate — but a retried request could, and a duplicated
    // timestamp draws a spur on the line. Filter defensively.
    const newest = held.points.length ? held.points[held.points.length - 1].t : "";
    const fresh = series.points.filter((point) => point.t > newest);
    const merged = held.points.concat(fresh);

    let start = 0;
    while (start < merged.length && Date.parse(`${merged[start].t}Z`) < cutoffMs) start += 1;

    return { ...series, points: start > 0 ? merged.slice(start) : merged };
  });
}

export function useLiveMonitor(
  selected: string[],
  range: Range,
  deploymentId: number | null,
) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  // Tagged with the query it answers. A window fetched for N001 over 15 min is
  // not an answer to a question about N002 over 6 h, and tagging it lets the
  // stale one be discarded at render time — rather than cleared from inside an
  // effect, which would cost an extra render on every control change.
  const [held, setHeld] = useState<{ key: string; data: History } | null>(null);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [perf, setPerf] = useState<Perf>({
    requests: 0,
    lastSnapshotMs: null,
    lastHistoryMs: null,
    lastHistoryBytes: null,
    points: 0,
  });

  const nodeParam = useMemo(() => selected.join(","), [selected]);
  const incremental = RAW_RANGES.includes(range);
  // The deployment is part of the question, so a window fetched for one
  // campaign is never shown under another.
  const queryKey = `${nodeParam}|${range}|${deploymentId ?? ""}`;

  // Refs, not state: these coordinate the polling loop and must not re-trigger
  // the effect that owns it.
  const inFlight = useRef({ snapshot: false, history: false });
  const watermark = useRef<string | null>(null);
  const seriesRef = useRef<Series[]>([]);
  const lastFullFetch = useRef(0);
  // The bucket width the server chose for the current window. A ref because the
  // polling effect reads it without needing to be rebuilt when it changes.
  const bucketRef = useRef(0);

  const bump = useCallback((patch: Partial<Perf>) => {
    setPerf((current) => ({ ...current, ...patch, requests: current.requests + 1 }));
  }, []);

  const loadSnapshot = useCallback(async () => {
    if (inFlight.current.snapshot || !nodeParam) return;
    inFlight.current.snapshot = true;
    const started = performance.now();
    try {
      const data = await getLiveSnapshot(nodeParam);
      setSnapshot(data);
      setError(null);
      bump({ lastSnapshotMs: Math.round(performance.now() - started) });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Error al leer el snapshot");
    } finally {
      inFlight.current.snapshot = false;
    }
  }, [nodeParam, bump]);

  const loadHistory = useCallback(
    async (full: boolean) => {
      if (inFlight.current.history || !nodeParam) return;
      inFlight.current.history = true;
      const started = performance.now();
      const since = full || !incremental ? undefined : watermark.current ?? undefined;

      try {
        const data: History = await getLiveHistory(nodeParam, range, since, deploymentId);
        const bytes = JSON.stringify(data).length;
        const cutoff = trimHorizon(data);

        const series =
          data.incremental && !full ? mergeSeries(seriesRef.current, data.series, cutoff) : data.series;

        seriesRef.current = series;
        bucketRef.current = data.resolution_seconds;
        let newest: string | null = null;
        let points = 0;
        for (const entry of series) {
          points += entry.points.length;
          const last = entry.points[entry.points.length - 1];
          if (last && (newest === null || last.t > newest)) newest = last.t;
        }
        watermark.current = newest;
        if (full) lastFullFetch.current = Date.now();

        setHeld({ key: queryKey, data: { ...data, series } });
        setError(null);
        bump({
          lastHistoryMs: Math.round(performance.now() - started),
          lastHistoryBytes: bytes,
          points,
        });
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Error al leer el histórico");
      } finally {
        inFlight.current.history = false;
      }
    },
    [nodeParam, range, incremental, queryKey, deploymentId, bump],
  );

  // A change of node set or range invalidates the held window entirely: the
  // watermark belongs to the old query, and reusing it would splice two
  // different windows together. Only the refs are reset here — the held window
  // carries the key of the query it answered and is discarded at render.
  //
  // `set-state-in-effect` is suppressed rather than worked around. Both loaders
  // are async and reach their first `await` before touching state, so nothing
  // is set synchronously here; the rule cannot see through the call. Fetching
  // on mount and on a changed query is the case effects exist for.
  useEffect(() => {
    seriesRef.current = [];
    watermark.current = null;
    if (!nodeParam) return;
    /* eslint-disable react-hooks/set-state-in-effect */
    void loadSnapshot();
    void loadHistory(true);
    /* eslint-enable react-hooks/set-state-in-effect */
    // The loaders are intentionally not dependencies: they are rebuilt whenever
    // `nodeParam` or `range` changes, which is exactly what this effect already
    // keys on, so listing them would only add a redundant identity check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeParam, range, deploymentId]);

  useEffect(() => {
    if (paused || !nodeParam) return undefined;

    const tick = () => {
      if (document.visibilityState !== "visible") return;
      void loadSnapshot();
      if (incremental) {
        void loadHistory(false);
      } else if (Date.now() - lastFullFetch.current >= historyIntervalMs(bucketRef.current)) {
        void loadHistory(true);
      }
    };

    const timer = window.setInterval(tick, SNAPSHOT_MS);

    // Coming back to a hidden tab, the held window is as stale as the time it
    // spent hidden. Refetch it whole rather than extending a stale window.
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        void loadSnapshot();
        void loadHistory(true);
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [paused, nodeParam, incremental, loadSnapshot, loadHistory]);

  const resume = useCallback(() => {
    setPaused(false);
    void loadSnapshot();
    void loadHistory(true);
  }, [loadSnapshot, loadHistory]);

  return {
    snapshot,
    // Never hand back a window fetched for a different question.
    history: held && held.key === queryKey ? held.data : null,
    paused,
    pause: () => setPaused(true),
    resume,
    error,
    perf,
    refreshMs: held ? historyIntervalMs(held.data.resolution_seconds) : SNAPSHOT_MS,
    rangeLabel: RANGES.find((entry) => entry.id === range)?.label ?? range,
  };
}

export type { Point };
