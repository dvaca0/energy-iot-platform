/**
 * Página de gestión de Smart Plugs (Shelly Plug US Gen4).
 *
 * Los enchufes no sustituyen al Shelly Pro 3EM: sirven para identificar qué
 * contacto o equipo individual consume más durante un despliegue.
 *
 * El descubrimiento ocurre en cada Raspberry, no en el backend. Esta página
 * sólo consume el inventario ya reportado y permite asignarlo.
 */
import { useMemo, useState } from "react";

import { SmartPlugAssignDialog } from "../components/smartplugs/SmartPlugAssignDialog";
import { SmartPlugCard } from "../components/smartplugs/SmartPlugCard";
import { SmartPlugFilters } from "../components/smartplugs/SmartPlugFilters";
import { SmartPlugSummary } from "../components/smartplugs/SmartPlugSummary";
import {
  AMBER,
  BORDER,
  TEXT,
  TEXT_MUTED,
  cardStyle,
} from "../components/smartplugs/styles";
import type { SmartPlug, SmartPlugAssignment } from "../components/smartplugs/types";
import { EMPTY_FILTERS, applyFilters, isPlugAssigned } from "../components/smartplugs/types";
import { useSmartPlugs } from "../components/smartplugs/useSmartPlugs";

function SectionHeading({ title, sub, count }: { title: string; sub: string; count: number }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 16 }}>
      <div>
        <h2 style={{ fontSize: 17, fontWeight: 700, color: TEXT }}>{title}</h2>
        <p style={{ fontSize: 12, color: TEXT_MUTED, marginTop: 3 }}>{sub}</p>
      </div>
      <span style={{ fontSize: 12, color: TEXT_MUTED }}>
        {count} enchufe{count === 1 ? "" : "s"}
      </span>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return <div style={{ ...cardStyle, fontSize: 13, color: TEXT_MUTED }}>{message}</div>;
}

export default function PageSmartPlugs() {
  const { plugs, source, assign } = useSmartPlugs();
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [editing, setEditing] = useState<SmartPlug | null>(null);

  const filtered = useMemo(() => applyFilters(plugs, filters), [plugs, filters]);
  const discovered = filtered.filter((plug) => !isPlugAssigned(plug));
  const assigned = filtered.filter(isPlugAssigned);

  const handleSave = async (assignment: SmartPlugAssignment) => {
    if (!editing) return;
    await assign(editing.id, assignment);
  };

  return (
    <div>
      {source === "error" && (
        <div
          style={{
            background: `${AMBER}14`,
            border: `1px solid ${AMBER}44`,
            color: "#fcd34d",
            borderRadius: 10,
            padding: "11px 14px",
            fontSize: 12,
            marginBottom: 18,
          }}
        >
          Sin conexión con <b>/api/smart-plugs</b>. Se muestra el último inventario recibido;
          reintentando cada 15 s.
        </div>
      )}

      <SmartPlugSummary plugs={plugs} />

      <SmartPlugFilters plugs={plugs} filters={filters} onChange={setFilters} />

      <div style={{ marginBottom: 30 }}>
        <SectionHeading
          title="Dispositivos recién descubiertos"
          sub="Detectados automáticamente por las Raspberry y aún sin asignar"
          count={discovered.length}
        />
        {discovered.length === 0 ? (
          <EmptyState message="No hay dispositivos pendientes de asignación con los filtros actuales." />
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            {discovered.map((plug) => (
              <SmartPlugCard key={plug.id} plug={plug} variant="discovered" onAssign={setEditing} />
            ))}
          </div>
        )}
      </div>

      <div style={{ borderTop: `1px solid ${BORDER}`, paddingTop: 24 }}>
        <SectionHeading
          title="Dispositivos asignados"
          sub="Enchufes ubicados en un edificio y despliegue"
          count={assigned.length}
        />
        {assigned.length === 0 ? (
          <EmptyState message="Todavía no hay enchufes asignados con los filtros actuales." />
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            {assigned.map((plug) => (
              <SmartPlugCard key={plug.id} plug={plug} variant="assigned" onAssign={setEditing} />
            ))}
          </div>
        )}
      </div>

      {editing && (
        <SmartPlugAssignDialog
          key={editing.id}
          plug={editing}
          onClose={() => setEditing(null)}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
