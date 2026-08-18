/**
 * Widget compacto de Smart Plugs para el Dashboard Ejecutivo.
 *
 * Deliberadamente pequeño: enchufes en línea, potencia total, el contacto de
 * mayor consumo y los últimos dispositivos descubiertos sin asignar.
 */
import {
  AMBER,
  BORDER_SOFT,
  GREEN,
  ACCENT_QUIET,
  SURFACE_INNER,
  TEXT,
  TEXT_FAINT,
  TEXT_MUTED,
  cardStyle,
  fmtNumber,
  fmtOrDash,
} from "./styles";
import { highestConsumer, isPlugAssigned, plugDisplayName, summarize } from "./types";
import { useSmartPlugs } from "./useSmartPlugs";

function Metric({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ background: SURFACE_INNER, border: `1px solid ${BORDER_SOFT}`, borderRadius: 10, padding: "10px 12px" }}>
      <div style={{ fontSize: 10, color: TEXT_FAINT, textTransform: "uppercase", letterSpacing: 0.8, fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 800, color, marginTop: 5 }}>{value}</div>
    </div>
  );
}

export function SmartPlugDashboardWidget() {
  const { plugs, source } = useSmartPlugs();

  const totals = summarize(plugs);
  const top = highestConsumer(plugs);
  const recent = plugs.filter((plug) => !isPlugAssigned(plug)).slice(0, 3);

  return (
    <div style={{ ...cardStyle, marginBottom: 18 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          marginBottom: 14,
        }}
      >
        <div>
          <div style={{ fontSize: 13, fontWeight: 800, color: TEXT }}>Smart Plugs</div>
          <div style={{ fontSize: 11, color: TEXT_MUTED }}>
            Identificación de consumo por contacto individual
          </div>
        </div>
        {source === "error" && (
          <span style={{ fontSize: 10, color: AMBER, fontWeight: 700 }}>Sin conexión</span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10 }}>
        <Metric label="En línea" value={`${totals.online} / ${plugs.length}`} color={GREEN} />
        <Metric label="Potencia total" value={`${fmtNumber(totals.powerW, 1)} W`} color={ACCENT_QUIET} />
        <Metric
          label="Mayor consumo"
          value={top ? `${fmtNumber(top.power_w, 0)} W` : "—"}
          color={TEXT}
        />
        <Metric label="Sin asignar" value={String(totals.unassigned)} color={AMBER} />
      </div>

      {top && (
        <div style={{ fontSize: 11, color: TEXT_MUTED, marginTop: 10 }}>
          Mayor consumo: <b style={{ color: ACCENT_QUIET }}>{plugDisplayName(top)}</b>
          {top.outlet_location ? ` · ${top.outlet_location}` : ""}
        </div>
      )}

      {recent.length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${BORDER_SOFT}` }}>
          <div
            style={{
              fontSize: 10,
              color: TEXT_FAINT,
              textTransform: "uppercase",
              letterSpacing: 0.8,
              fontWeight: 700,
              marginBottom: 8,
            }}
          >
            Descubiertos recientemente
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {recent.map((plug) => (
              <span
                key={plug.id}
                style={{
                  background: `${AMBER}14`,
                  border: `1px solid ${AMBER}33`,
                  color: "#fcd34d",
                  borderRadius: 999,
                  padding: "4px 11px",
                  fontSize: 11,
                  fontWeight: 500,
                }}
              >
                {plug.mac} · {fmtOrDash(plug.node)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
