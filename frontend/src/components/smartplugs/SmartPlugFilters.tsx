/**
 * Barra de filtros: búsqueda libre, estado, edificio, despliegue y nodo.
 * Las opciones se derivan del inventario recibido, no de listas fijas.
 */
import { BORDER_STRONG, SURFACE_INNER, TEXT, TEXT_MUTED, inputStyle } from "./styles";
import type { SmartPlug, SmartPlugFilterState, SmartPlugStatusFilter } from "./types";
import { distinctValues } from "./types";

const selectStyle = {
  ...inputStyle,
  background: SURFACE_INNER,
  border: `1px solid ${BORDER_STRONG}`,
  color: TEXT,
};

interface SelectFilterProps {
  label: string;
  value: string;
  options: string[];
  allLabel: string;
  onChange: (value: string) => void;
}

function SelectFilter({ label, value, options, allLabel, onChange }: SelectFilterProps) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 170, flex: 1 }}>
      <span style={{ fontSize: 11, color: TEXT_MUTED, fontWeight: 700 }}>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} style={selectStyle}>
        <option value="all">{allLabel}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

interface SmartPlugFiltersProps {
  plugs: SmartPlug[];
  filters: SmartPlugFilterState;
  onChange: (filters: SmartPlugFilterState) => void;
}

export function SmartPlugFilters({ plugs, filters, onChange }: SmartPlugFiltersProps) {
  const update = (patch: Partial<SmartPlugFilterState>) => onChange({ ...filters, ...patch });

  return (
    <div
      style={{
        display: "flex",
        gap: 12,
        flexWrap: "wrap",
        alignItems: "flex-end",
        marginBottom: 22,
      }}
    >
      <label style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 240, flex: 2 }}>
        <span style={{ fontSize: 11, color: TEXT_MUTED, fontWeight: 700 }}>Búsqueda</span>
        <input
          value={filters.search}
          onChange={(event) => update({ search: event.target.value })}
          placeholder="Nombre, MAC, IP, hostname, ubicación..."
          style={inputStyle}
        />
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 170, flex: 1 }}>
        <span style={{ fontSize: 11, color: TEXT_MUTED, fontWeight: 700 }}>Estado</span>
        <select
          value={filters.status}
          onChange={(event) => update({ status: event.target.value as SmartPlugStatusFilter })}
          style={selectStyle}
        >
          <option value="all">Todos los estados</option>
          <option value="online">En línea</option>
          <option value="offline">Fuera de línea</option>
          <option value="unassigned">Sin asignar</option>
        </select>
      </label>

      <SelectFilter
        label="Edificio"
        value={filters.building}
        options={distinctValues(plugs, "building")}
        allLabel="Todos los edificios"
        onChange={(building) => update({ building })}
      />

      <SelectFilter
        label="Despliegue"
        value={filters.deployment}
        options={distinctValues(plugs, "deployment")}
        allLabel="Todos los despliegues"
        onChange={(deployment) => update({ deployment })}
      />

      <SelectFilter
        label="Nodo"
        value={filters.node}
        options={distinctValues(plugs, "node")}
        allLabel="Todos los nodos"
        onChange={(node) => update({ node })}
      />
    </div>
  );
}
