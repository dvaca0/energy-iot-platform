/**
 * Diálogo de asignación de un enchufe a un edificio y despliegue.
 *
 * El padre lo monta con key={plug.id}, por lo que el estado inicial se toma
 * directamente del enchufe seleccionado y no requiere sincronización.
 */
import { useState } from "react";

import {
  BORDER,
  RED,
  SURFACE,
  TEXT,
  TEXT_MUTED,
  fmtOrDash,
  ghostButtonStyle,
  inputStyle,
  primaryButtonStyle,
} from "./styles";
import type { SmartPlug, SmartPlugAssignment } from "./types";

interface SmartPlugAssignDialogProps {
  plug: SmartPlug;
  onClose: () => void;
  onSave: (assignment: SmartPlugAssignment) => Promise<void>;
}

export function SmartPlugAssignDialog({ plug, onClose, onSave }: SmartPlugAssignDialogProps) {
  const [form, setForm] = useState<SmartPlugAssignment>({
    friendly_name: plug.friendly_name || "",
    building: plug.building || "",
    deployment: plug.deployment || "",
    outlet_location: plug.outlet_location || "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (key: keyof SmartPlugAssignment, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const handleSave = async () => {
    if (!form.friendly_name.trim() || !form.building.trim()) {
      setError("El nombre amigable y el edificio son obligatorios.");
      return;
    }

    setSaving(true);
    setError(null);

    try {
      await onSave({
        friendly_name: form.friendly_name.trim(),
        building: form.building.trim(),
        deployment: form.deployment.trim(),
        outlet_location: form.outlet_location.trim(),
      });
      onClose();
    } catch {
      setError("No se pudo guardar la asignación. Intenta de nuevo.");
      setSaving(false);
    }
  };

  const fields: Array<[keyof SmartPlugAssignment, string, string]> = [
    ["friendly_name", "Nombre amigable", "Ej. Rack de switches"],
    ["building", "Edificio", "Ej. Edificio de prueba"],
    ["deployment", "Despliegue", "Ej. Campaña Laboratorio de Redes"],
    ["outlet_location", "Ubicación del contacto", "Ej. Rack A · Contacto 3"],
  ];

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(6,8,10,.7)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        zIndex: 120,
      }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        style={{
          background: SURFACE,
          border: `1px solid ${BORDER}`,
          borderRadius: 12,
          padding: 24,
          width: "100%",
          maxWidth: 460,
          boxShadow: "0 16px 48px rgba(0,0,0,.5)",
        }}
      >
        <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: -0.2, color: TEXT, marginBottom: 4 }}>
          Asignar enchufe
        </div>
        <div style={{ fontSize: 12, color: TEXT_MUTED, marginBottom: 20 }}>
          {plug.model} · {plug.mac} · IP {fmtOrDash(plug.ip)}
        </div>

        <div style={{ display: "grid", gap: 14 }}>
          {fields.map(([key, label, placeholder]) => (
            <label key={key} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span style={{ fontSize: 11, color: TEXT_MUTED, fontWeight: 500 }}>{label}</span>
              <input
                value={form[key]}
                onChange={(event) => update(key, event.target.value)}
                placeholder={placeholder}
                style={inputStyle}
              />
            </label>
          ))}
        </div>

        {error && (
          <div
            style={{
              marginTop: 14,
              background: `${RED}18`,
              border: `1px solid ${RED}44`,
              color: "#fca5a5",
              borderRadius: 6,
              padding: "9px 12px",
              fontSize: 12,
            }}
          >
            {error}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 22 }}>
          <button type="button" onClick={onClose} disabled={saving} style={ghostButtonStyle}>
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            style={{ ...primaryButtonStyle, opacity: saving ? 0.6 : 1 }}
          >
            {saving ? "Guardando..." : "Guardar"}
          </button>
        </div>
      </div>
    </div>
  );
}
