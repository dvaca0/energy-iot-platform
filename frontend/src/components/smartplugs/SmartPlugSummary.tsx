/**
 * Resumen superior de la página de Smart Plugs. Replica el bloque de
 * StatCard usado en el Dashboard Ejecutivo y en Infraestructura.
 */
import {
  AMBER,
  GRAY,
  GREEN,
  ACCENT,
  ACCENT_QUIET,
  TEXT,
  TEXT_MUTED,
  cardStyle,
  fmtNumber,
} from "./styles";
import type { SmartPlug } from "./types";
import { summarize } from "./types";

interface StatProps {
  label: string;
  value: string;
  sub: string;
  color: string;
}

function Stat({ label, value, sub, color }: StatProps) {
  return (
    <div style={{ ...cardStyle, flex: 1, minWidth: 150, borderTop: `1px solid ${color}55` }}>
      <div
        style={{
          fontSize: 10,
          color: TEXT_MUTED,
          textTransform: "uppercase",
          letterSpacing: 1.2,
          fontWeight: 700,
          marginBottom: 8,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 27, fontWeight: 760, color: TEXT, letterSpacing: -0.8, lineHeight: 1.05 }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: TEXT_MUTED, marginTop: 8 }}>{sub}</div>
    </div>
  );
}

export function SmartPlugSummary({ plugs }: { plugs: SmartPlug[] }) {
  const totals = summarize(plugs);

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 22 }}>
      <Stat
        label="En línea"
        value={String(totals.online)}
        sub={`${plugs.length} enchufe${plugs.length === 1 ? "" : "s"} en inventario`}
        color={GREEN}
      />
      <Stat
        label="Fuera de línea"
        value={String(totals.offline)}
        sub="Sin respuesta de la Raspberry"
        color={GRAY}
      />
      <Stat
        label="Sin asignar"
        value={String(totals.unassigned)}
        sub="Descubiertos y pendientes"
        color={AMBER}
      />
      <Stat
        label="Potencia actual"
        value={`${fmtNumber(totals.powerW, 1)} W`}
        sub="Suma de enchufes en línea"
        color={ACCENT}
      />
      <Stat
        label="Energía hoy"
        value={`${fmtNumber(totals.energyTodayKwh, 3)} kWh`}
        sub="Acumulado del día"
        color={ACCENT_QUIET}
      />
    </div>
  );
}
