/**
 * Monitoreo en Vivo — the technical view.
 *
 * The page a technician opens standing next to a panel. It answers, in order of
 * how fast they need the answer: is this node measuring, what is it measuring
 * right now, how has each quantity moved over the last minutes or hours, do the
 * phases agree, do the nodes agree, and is the node itself healthy.
 *
 * Everything drawn here is a stored measurement. Nothing is derived to fill a
 * gap and nothing is defaulted to zero: a quantity the platform does not hold
 * for a node is labelled "no disponible" wherever it would otherwise appear.
 * The inventory of what is and is not stored — including the Shelly fields the
 * meter publishes but the collector does not forward — lives in
 * `docs/Live-Monitoring.md`.
 */
import { useEffect, useMemo, useState } from "react";

import { NodeSummaryCard } from "../components/livemonitor/NodeSummaryCard";
import { ReadingsTable } from "../components/livemonitor/ReadingsTable";
import { SeriesChart } from "../components/livemonitor/SeriesChart";
import {
  BORDER,
  BORDER_SOFT,
  CRIT,
  OK,
  SURFACE_INNER,
  TEXT,
  TEXT_MUTED,
  TEXT_SECONDARY,
  WARN,
  buttonStyle,
  cardStyle,
  labelStyle,
} from "../components/livemonitor/styles";
import type { DeploymentSpan, Range } from "../components/livemonitor/types";
import { CHARTS, RANGES, clockTime, humanAge, nodeSupports } from "../components/livemonitor/types";
import { SNAPSHOT_MS, useLiveMonitor } from "../components/livemonitor/useLiveMonitor";
import { getLiveDeployments, getNodes } from "../services/api";

interface NodeOption {
  id: string;
  name: string;
  hardware_kind: string | null;
  online: boolean;
}

function Toolbar({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      <span style={{ ...labelStyle, marginRight: 2 }}>{label}</span>
      {children}
    </div>
  );
}

export default function PageLiveMonitor() {
  const [options, setOptions] = useState<NodeOption[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [range, setRange] = useState<Range>("15m");
  const [perPhase, setPerPhase] = useState(true);
  const [deployments, setDeployments] = useState<DeploymentSpan[]>([]);
  const [deploymentId, setDeploymentId] = useState<number | null>(null);
  const deploymentMode = range === "deployment";

  // The node list is inventory, not telemetry: fetched once, not polled. Its
  // liveness comes from the snapshot, which is polled.
  useEffect(() => {
    getNodes()
      .then((rows: NodeOption[]) => {
        setOptions(rows);
        setSelected((current) => {
          if (current.length > 0) return current;
          // Open on the nodes that are actually reporting. A technician arriving
          // at the page wants the working fleet first, not an empty chart for a
          // node that has been in storage for a month.
          const live = rows.filter((row) => row.online).map((row) => row.id);
          return live.length > 0 ? live : rows.slice(0, 1).map((row) => row.id);
        });
      })
      .catch((error) => console.error("Node list API error:", error));
  }, []);

  // Campaign inventory, fetched once. Only activated deployments appear: a
  // planned one has no readings and no bounds, so charting it is meaningless.
  useEffect(() => {
    getLiveDeployments()
      .then((rows: DeploymentSpan[]) => {
        setDeployments(rows);
        setDeploymentId((current) => current ?? rows[0]?.deployment_id ?? null);
      })
      .catch((cause) => console.error("Deployment list API error:", cause));
  }, []);

  const { snapshot, history, paused, pause, resume, error, perf, refreshMs } = useLiveMonitor(
    selected,
    range,
    deploymentMode ? deploymentId : null,
  );

  const activeDeployment = history?.deployments?.[0] ?? null;

  // Which nodes the page is about. On the chronological ranges that is the
  // technician's selection; in deployment mode the campaign decides, because
  // the server scopes the window by deployment_id and answering "deployment 4,
  // but only N002" with an empty chart would look like a fault rather than a
  // category error.
  const scopedCodes = useMemo(() => {
    if (!deploymentMode) return selected;
    const fromData = history?.series.map((entry) => entry.node_id) ?? [];
    const declared = activeDeployment?.node_id ? [activeDeployment.node_id] : [];
    const union = Array.from(new Set([...fromData, ...declared]));
    return union.length > 0 ? union : selected;
  }, [deploymentMode, selected, history, activeDeployment]);

  const nodes = useMemo(
    () => (snapshot ? snapshot.nodes.filter((node) => scopedCodes.includes(node.node_id)) : []),
    [snapshot, scopedCodes],
  );
  const multiNode = nodes.length > 1;

  const newestReading = useMemo(() => {
    const stamps = nodes
      .map((node) => node.reading?.timestamp)
      .filter((value): value is string => Boolean(value));
    return stamps.length ? stamps.sort().at(-1)! : null;
  }, [nodes]);

  const newestAge = useMemo(() => {
    const ages = nodes
      .map((node) => node.reading?.age_seconds)
      .filter((value): value is number => value !== null && value !== undefined);
    return ages.length ? Math.min(...ages) : null;
  }, [nodes]);

  const toggleNode = (id: string) =>
    setSelected((current) =>
      current.includes(id)
        ? current.length === 1
          ? current // never leave the page with nothing selected
          : current.filter((entry) => entry !== id)
        : [...current, id].sort(),
    );

  const bucketed = (history?.resolution_seconds ?? 0) > 0;

  // A chart is drawn when at least one selected node can supply it. The rest are
  // named in one place instead of rendered as empty axes.
  const drawable = useMemo(
    () => CHARTS.filter((spec) => nodes.some((node) => nodeSupports(node, spec))),
    [nodes],
  );
  const hidden = useMemo(
    () => CHARTS.filter((spec) => !nodes.some((node) => nodeSupports(node, spec))),
    [nodes],
  );

  return (
    <div>
      <style>{`@keyframes lmPulse{0%,100%{opacity:1}50%{opacity:.4}}`}</style>

      {/* ------------------------------------------------------------ status */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 14,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            background: paused ? `${TEXT_MUTED}14` : `${OK}14`,
            border: `1px solid ${paused ? `${TEXT_MUTED}33` : `${OK}33`}`,
            borderRadius: 4,
            padding: "4px 10px",
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: paused ? TEXT_MUTED : OK,
              animation: paused ? undefined : "lmPulse 2.4s ease-in-out infinite",
            }}
          />
          <span
            style={{
              fontSize: 11,
              color: paused ? TEXT_MUTED : OK,
              fontWeight: 500,
              letterSpacing: 0.3,
            }}
          >
            {paused ? "EN PAUSA" : "EN VIVO"}
          </span>
        </div>

        <span style={{ fontSize: 11.5, color: TEXT_MUTED }}>
          {paused
            ? "Vista congelada — la adquisición del nodo continúa sin cambios"
            : `Actualización cada ${SNAPSHOT_MS / 1000} s`}
          {newestReading && ` · última lectura ${clockTime(newestReading)}`}
          {newestAge !== null && ` (hace ${humanAge(newestAge)})`}
        </span>

        <button
          type="button"
          style={{ ...buttonStyle(paused), marginLeft: "auto" }}
          onClick={() => (paused ? resume() : pause())}
        >
          {paused ? "Reanudar" : "Pausar"}
        </button>
      </div>

      {error && (
        <div
          style={{
            ...cardStyle,
            borderColor: `${CRIT}44`,
            padding: "10px 14px",
            marginBottom: 14,
            fontSize: 12,
            color: TEXT_SECONDARY,
          }}
        >
          No se pudo leer la API: {error}
        </div>
      )}

      {/* ----------------------------------------------------------- controls */}
      <div
        style={{
          ...cardStyle,
          padding: "12px 16px",
          marginBottom: 18,
          display: "flex",
          gap: 22,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        {deploymentMode ? (
          <Toolbar label="Despliegue">
            <select
              value={deploymentId ?? ""}
              onChange={(event) => setDeploymentId(Number(event.target.value) || null)}
              style={{
                ...buttonStyle(true),
                appearance: "auto",
                padding: "5px 9px",
                maxWidth: 420,
              }}
            >
              {deployments.map((entry) => (
                <option key={entry.deployment_id} value={entry.deployment_id}>
                  #{entry.deployment_id} · {entry.node_id} · {entry.building ?? "sin edificio"} ·{" "}
                  {(entry.activated_at ?? "").slice(0, 10)} →{" "}
                  {entry.closed_at ? entry.closed_at.slice(0, 10) : "abierto"} ({entry.status})
                </option>
              ))}
            </select>
            <span style={{ fontSize: 10.5, color: TEXT_MUTED, maxWidth: 300 }}>
              El despliegue define el nodo y la ventana. La comparación entre nodos vive en los
              rangos cronológicos.
            </span>
          </Toolbar>
        ) : (
        <Toolbar label="Nodos">
          {options.map((option) => {
            const active = selected.includes(option.id);
            return (
              <button
                key={option.id}
                type="button"
                style={buttonStyle(active)}
                onClick={() => toggleNode(option.id)}
                title={`${option.name} · ${option.hardware_kind ?? "hardware sin declarar"}`}
              >
                <span style={{ marginRight: 6, opacity: active ? 1 : 0.4 }}>{active ? "✓" : "○"}</span>
                {option.id}
              </button>
            );
          })}
        </Toolbar>
        )}

        <Toolbar label="Rango">
          {RANGES.map((entry) => (
            <button
              key={entry.id}
              type="button"
              style={buttonStyle(range === entry.id)}
              onClick={() => setRange(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </Toolbar>

        <Toolbar label="Series">
          <button type="button" style={buttonStyle(perPhase)} onClick={() => setPerPhase(true)}>
            Por fase
          </button>
          <button type="button" style={buttonStyle(!perPhase)} onClick={() => setPerPhase(false)}>
            Sólo totales
          </button>
        </Toolbar>
      </div>

      {/* -------------------------------------------------------- snapshot */}
      <div style={{ marginBottom: 8 }}>
        <h2 style={{ fontSize: 14, fontWeight: 600, color: TEXT, letterSpacing: -0.1 }}>
          Resumen instantáneo
        </h2>
        <p style={{ fontSize: 11.5, color: TEXT_MUTED, marginTop: 3 }}>
          Última lectura almacenada de cada nodo, con el estado del Raspberry Pi que la produjo.
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 26 }}>
        {nodes.length === 0 ? (
          <div style={{ ...cardStyle, fontSize: 12.5, color: TEXT_MUTED }}>
            {snapshot ? "Ningún nodo seleccionado." : "Cargando estado de los nodos…"}
          </div>
        ) : (
          nodes.map((node) => (
            <NodeSummaryCard key={node.node_id} node={node} limits={snapshot!.limits} />
          ))
        )}
      </div>

      {/* ----------------------------------------------------------- series */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 14, flexWrap: "wrap" }}>
          <div>
            <h2 style={{ fontSize: 14, fontWeight: 600, color: TEXT, letterSpacing: -0.1 }}>
              Series temporales
            </h2>
            <p style={{ fontSize: 11.5, color: TEXT_MUTED, marginTop: 3 }}>
              Una gráfica por magnitud. Pase el cursor por cualquier punto para leer el valor exacto.
              {multiNode && " Al comparar nodos, el color indica la fase y el trazo indica el nodo."}
            </p>
          </div>
          {history && (
            <div
              style={{
                background: SURFACE_INNER,
                border: `1px solid ${BORDER_SOFT}`,
                borderRadius: 6,
                padding: "6px 11px",
                fontSize: 10.5,
                color: TEXT_MUTED,
                lineHeight: 1.6,
              }}
            >
              <div>
                <span style={{ color: TEXT_SECONDARY }}>Resolución:</span>{" "}
                {bucketed
                  ? `media en cubetas de ${history.resolution_seconds} s`
                  : "muestras crudas, sin agregar"}
              </div>
              {activeDeployment && (
                <div>
                  <span style={{ color: TEXT_SECONDARY }}>Despliegue:</span> #
                  {activeDeployment.deployment_id} · {activeDeployment.node_id} ·{" "}
                  {activeDeployment.building ?? "sin edificio"} ({activeDeployment.status})
                </div>
              )}
              <div>
                <span style={{ color: TEXT_SECONDARY }}>Puntos en pantalla:</span>{" "}
                {history.point_count.toLocaleString("es-MX")}
                {bucketed && ` · refresco completo cada ${Math.round(refreshMs / 1000)} s`}
                {!bucketed && " · ampliación incremental"}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* A campaign can own readings its own dates do not cover. Attribution is
          written once at ingest from each measurement's captured_at and never
          recomputed (ADR-0004), so a window entered wrongly leaves the chart
          legitimately empty. Saying so beats an unexplained blank axis, and
          widening the window to hide it would be the retroactive attribution the
          platform forbids. */}
      {activeDeployment &&
        activeDeployment.readings_in_window === 0 &&
        (activeDeployment.readings_outside_window ?? 0) > 0 && (
          <div
            style={{
              ...cardStyle,
              padding: "11px 16px",
              marginBottom: 14,
              borderColor: `${CRIT}44`,
              fontSize: 11.5,
              color: TEXT_SECONDARY,
              lineHeight: 1.6,
            }}
          >
            <strong style={{ color: TEXT }}>
              Este despliegue no tiene lecturas dentro de su propia ventana.
            </strong>{" "}
            Declara {(activeDeployment.activated_at ?? "").slice(0, 10)} →{" "}
            {activeDeployment.closed_at ? activeDeployment.closed_at.slice(0, 10) : "abierto"}, pero
            las {activeDeployment.readings_outside_window?.toLocaleString("es-MX")} lecturas
            atribuidas a él están fechadas fuera de ese rango. La gráfica está vacía porque no hay
            nada que dibujar, no porque falle. La atribución se escribe una sola vez en la ingesta y
            no se recalcula al leer: corregirlo es editar la ventana del despliegue, no esta página.
          </div>
        )}

      {activeDeployment &&
        (activeDeployment.readings_outside_window ?? 0) > 0 &&
        (activeDeployment.readings_in_window ?? 0) > 0 && (
          <div
            style={{
              ...cardStyle,
              padding: "10px 16px",
              marginBottom: 14,
              borderColor: `${WARN}33`,
              fontSize: 11,
              color: TEXT_MUTED,
            }}
          >
            {activeDeployment.readings_in_window?.toLocaleString("es-MX")} lecturas dentro de la
            ventana declarada y {activeDeployment.readings_outside_window?.toLocaleString("es-MX")}{" "}
            fuera. Sólo se grafican las de dentro.
          </div>
        )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(430px, 1fr))",
          gap: 14,
          marginBottom: 14,
        }}
      >
        {history &&
          nodes.length > 0 &&
          drawable.map((spec) => (
            <SeriesChart
              key={spec.id}
              spec={spec}
              series={history.series}
              nodes={nodes}
              perPhase={perPhase}
              resolutionSeconds={history.resolution_seconds}
              paused={paused}
            />
          ))}
        {!history && (
          <div style={{ ...cardStyle, fontSize: 12.5, color: TEXT_MUTED }}>Cargando series…</div>
        )}
      </div>

      {/* Quantities no selected node reports. Listed rather than drawn as a row
          of empty axes: the information a technician needs is "the platform has
          nothing here", and one honest line says that better than six blank
          charts. */}
      {history && nodes.length > 0 && hidden.length > 0 && (
        <div
          style={{
            ...cardStyle,
            padding: "12px 16px",
            marginBottom: 22,
            borderStyle: "dashed",
          }}
        >
          <div style={{ ...labelStyle, marginBottom: 7 }}>
            Sin datos para {nodes.map((node) => node.node_id).join(", ")}
          </div>
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 8 }}>
            {hidden.map((spec) => (
              <span
                key={spec.id}
                style={{
                  background: SURFACE_INNER,
                  border: `1px solid ${BORDER_SOFT}`,
                  borderRadius: 5,
                  padding: "3px 8px",
                  fontSize: 11,
                  color: TEXT_SECONDARY,
                }}
              >
                {spec.title}
              </span>
            ))}
          </div>
          <div style={{ fontSize: 10.5, color: TEXT_MUTED, lineHeight: 1.55 }}>
            El medidor mide estas magnitudes y la plataforma ya tiene columnas para ellas, pero
            ninguna lectura almacenada las trae todavía: el colector de los nodos aún no las envía.
            No se dibujan en cero — no hay dato.
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------ table */}
      {history && (
        <div style={{ marginBottom: 18 }}>
          <ReadingsTable series={history.series} resolutionSeconds={history.resolution_seconds} />
        </div>
      )}

      {/* Instrumentation, kept visible on purpose: this page is meant to stay
          open all day, and the cost of doing so should not be a mystery. */}
      <div
        style={{
          border: `1px solid ${BORDER}`,
          borderRadius: 8,
          padding: "9px 13px",
          fontSize: 10.5,
          color: TEXT_MUTED,
          display: "flex",
          gap: 18,
          flexWrap: "wrap",
        }}
      >
        <span>peticiones en esta sesión: {perf.requests.toLocaleString("es-MX")}</span>
        <span>snapshot: {perf.lastSnapshotMs ?? "—"} ms</span>
        <span>histórico: {perf.lastHistoryMs ?? "—"} ms</span>
        <span>
          último payload:{" "}
          {perf.lastHistoryBytes ? `${(perf.lastHistoryBytes / 1024).toFixed(1)} KB` : "—"}
        </span>
        <span>puntos en memoria: {perf.points.toLocaleString("es-MX")}</span>
      </div>
    </div>
  );
}
