/**
 * Tarjeta de un enchufe inteligente.
 *
 * variant="discovered": dispositivo hallado por la Raspberry y aún sin
 * asignar. Muestra la identidad de hardware y el botón de asignación.
 *
 * variant="assigned": dispositivo ya ubicado en un edificio y despliegue.
 * Muestra la telemetría operativa y despliega el detalle técnico completo.
 */
import { useState } from "react";

import { SmartPlugStatusBadge } from "./SmartPlugStatusBadge";
import {
  AMBER,
  BORDER,
  BORDER_SOFT,
  ACCENT_QUIET,
  SURFACE_DEEP,
  SURFACE_INNER,
  TEXT,
  TEXT_FAINT,
  TEXT_MUTED,
  cardStyle,
  fieldLabelStyle,
  fieldValueStyle,
  fmtDateTime,
  fmtNumber,
  fmtOrDash,
  ghostButtonStyle,
  primaryButtonStyle,
  rssiColor,
} from "./styles";
import type { SmartPlug } from "./types";
import { plugDisplayName, plugVariant } from "./types";

interface FieldProps {
  label: string;
  value: string;
  color?: string;
  mono?: boolean;
}

function Field({ label, value, color, mono = false }: FieldProps) {
  return (
    <div>
      <div style={fieldLabelStyle}>{label}</div>
      <div
        style={{
          ...fieldValueStyle,
          ...(color ? { color } : {}),
          ...(mono ? { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12 } : {}),
        }}
      >
        {value}
      </div>
    </div>
  );
}

const gridStyle = (min: number) => ({
  display: "grid",
  gridTemplateColumns: `repeat(auto-fit,minmax(${min}px,1fr))`,
  gap: 14,
});

const powerText = (plug: SmartPlug): string =>
  plug.online ? `${fmtNumber(plug.power_w, 1)} W` : "—";

interface SmartPlugCardProps {
  plug: SmartPlug;
  variant: "discovered" | "assigned";
  onAssign: (plug: SmartPlug) => void;
}

export function SmartPlugCard({ plug, variant, onAssign }: SmartPlugCardProps) {
  const [expanded, setExpanded] = useState(false);
  const discovered = variant === "discovered";

  return (
    <div
      style={{
        ...cardStyle,
        border: `1px solid ${discovered ? `${AMBER}44` : BORDER}`,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 14,
          flexWrap: "wrap",
          marginBottom: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, color: TEXT, marginBottom: 4 }}>
            {discovered ? plug.model : plugDisplayName(plug)}
          </div>
          <div style={{ fontSize: 11, color: TEXT_MUTED }}>
            {discovered
              ? `Descubierto por ${fmtOrDash(plug.node)} · ${fmtDateTime(plug.last_seen)}`
              : [plug.building, plug.deployment, plug.outlet_location].filter(Boolean).join(" · ")}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <SmartPlugStatusBadge variant={plugVariant(plug)} />
          {discovered && (
            <button type="button" onClick={() => onAssign(plug)} style={primaryButtonStyle}>
              Asignar
            </button>
          )}
        </div>
      </div>

      {discovered ? (
        <div style={gridStyle(130)}>
          <Field label="Modelo" value={plug.model} />
          <Field label="MAC" value={plug.mac} mono />
          <Field label="IP" value={fmtOrDash(plug.ip)} mono />
          <Field
            label="RSSI WiFi"
            value={plug.rssi === null ? "—" : `${plug.rssi} dBm`}
            color={rssiColor(plug.rssi)}
          />
          <Field label="Firmware" value={fmtOrDash(plug.firmware)} />
          <Field
            label="Temperatura"
            value={plug.temperature_c === null ? "—" : `${fmtNumber(plug.temperature_c, 1)} °C`}
          />
          <Field label="Potencia" value={powerText(plug)} color={ACCENT_QUIET} />
          <Field
            label="Corriente"
            value={plug.current_a === null ? "—" : `${fmtNumber(plug.current_a, 2)} A`}
          />
          <Field
            label="Tensión"
            value={plug.voltage_v === null ? "—" : `${fmtNumber(plug.voltage_v, 1)} V`}
          />
        </div>
      ) : (
        <>
          <div style={gridStyle(120)}>
            <Field label="Nodo" value={fmtOrDash(plug.node)} />
            <Field label="Potencia" value={powerText(plug)} color={ACCENT_QUIET} />
            <Field
              label="Tensión"
              value={plug.voltage_v === null ? "—" : `${fmtNumber(plug.voltage_v, 1)} V`}
            />
            <Field
              label="Corriente"
              value={plug.current_a === null ? "—" : `${fmtNumber(plug.current_a, 2)} A`}
            />
            <Field label="Energía hoy" value={`${fmtNumber(plug.energy_today_kwh, 3)} kWh`} />
            <Field
              label="Factor de potencia"
              value={plug.power_factor === null ? "—" : fmtNumber(plug.power_factor, 3)}
            />
          </div>

          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              marginTop: 16,
            }}
          >
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              style={{ ...ghostButtonStyle, padding: "7px 14px" }}
            >
              {expanded ? "Ocultar detalles" : "Ver detalles"}
            </button>
            <button
              type="button"
              onClick={() => onAssign(plug)}
              style={{ ...ghostButtonStyle, padding: "7px 14px" }}
            >
              Editar asignación
            </button>
          </div>

          {expanded && (
            <div
              style={{
                marginTop: 14,
                paddingTop: 16,
                borderTop: `1px solid ${BORDER_SOFT}`,
                background: SURFACE_DEEP,
                borderRadius: 10,
                padding: 16,
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  color: TEXT_FAINT,
                  textTransform: "uppercase",
                  letterSpacing: 1.2,
                  fontWeight: 700,
                  marginBottom: 14,
                }}
              >
                Detalle técnico del dispositivo
              </div>

              <div style={gridStyle(150)}>
                <Field label="MAC" value={plug.mac} mono />
                <Field label="IP actual" value={fmtOrDash(plug.ip)} mono />
                <Field label="Hostname" value={fmtOrDash(plug.hostname)} mono />
                <Field label="Firmware" value={fmtOrDash(plug.firmware)} />
                <Field
                  label="RSSI WiFi"
                  value={plug.rssi === null ? "—" : `${plug.rssi} dBm`}
                  color={rssiColor(plug.rssi)}
                />
                <Field
                  label="Temperatura"
                  value={plug.temperature_c === null ? "—" : `${fmtNumber(plug.temperature_c, 1)} °C`}
                />
                <Field label="Última vez visto" value={fmtDateTime(plug.last_seen)} />
                <Field label="Serie" value={fmtOrDash(plug.serial)} mono />
              </div>

              <div
                style={{
                  marginTop: 14,
                  background: SURFACE_INNER,
                  borderRadius: 8,
                  padding: "9px 12px",
                  fontSize: 11,
                  color: TEXT_MUTED,
                }}
              >
                El dispositivo se identifica por su dirección MAC. La IP puede cambiar entre
                renovaciones de DHCP sin afectar el historial.
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
