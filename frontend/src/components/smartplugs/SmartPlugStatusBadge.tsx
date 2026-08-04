/**
 * Insignia de estado de un enchufe. Misma forma de píldora que el resto de la
 * plataforma (Nodos, Despliegues) para no introducir un segundo estilo.
 */
import { AMBER, GRAY, GREEN } from "./styles";
import type { SmartPlugBadgeVariant } from "./types";

const VARIANT_META: Record<SmartPlugBadgeVariant, { label: string; color: string }> = {
  online: { label: "En línea", color: GREEN },
  offline: { label: "Fuera de línea", color: GRAY },
  unassigned: { label: "Sin asignar", color: AMBER },
};

export function SmartPlugStatusBadge({ variant }: { variant: SmartPlugBadgeVariant }) {
  const meta = VARIANT_META[variant];

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        background: `${meta.color}18`,
        color: meta.color,
        border: `1px solid ${meta.color}44`,
        borderRadius: 999,
        padding: "4px 11px",
        fontSize: 11,
        fontWeight: 800,
        letterSpacing: 0.4,
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          background: meta.color,
          boxShadow: `0 0 6px ${meta.color}`,
        }}
      />
      {meta.label}
    </span>
  );
}
