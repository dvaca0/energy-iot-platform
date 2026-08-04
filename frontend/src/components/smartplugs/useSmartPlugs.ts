/**
 * Fuente de datos única del módulo Smart Plugs.
 *
 * Consume GET /api/smart-plugs, el inventario real que cada Raspberry reporta
 * al backend. No existen datos de demostración: si el endpoint falla se informa
 * el error y la lista queda vacía, nunca se inventan dispositivos.
 *
 * La página y el widget del dashboard comparten este hook para no duplicar la
 * lógica de carga.
 *
 * El sondeo es de 15 s, la misma cadencia con la que cada Raspberry sondea
 * sus enchufes conocidos.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { assignSmartPlug, getSmartPlugs } from "../../services/api";
import type { SmartPlug, SmartPlugAssignment } from "./types";

export const POLL_INTERVAL_MS = 15000;

export type SmartPlugSource = "loading" | "api" | "error";

const toNumberOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const toStringOrNull = (value: unknown): string | null => {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
};

/**
 * El backend es la autoridad sobre el contrato, pero la UI no debe romperse
 * si un campo llega ausente o con otro tipo: se normaliza a la forma tipada.
 */
const normalize = (raw: Record<string, unknown>): SmartPlug => {
  const mac = String(raw.mac ?? "").toUpperCase();

  return {
    id: String(raw.id ?? mac.replace(/:/g, "").toLowerCase()),
    mac,
    model: String(raw.model ?? "Shelly Plug US Gen4"),
    ip: toStringOrNull(raw.ip),
    hostname: toStringOrNull(raw.hostname),
    serial: toStringOrNull(raw.serial),
    firmware: toStringOrNull(raw.firmware),
    rssi: toNumberOrNull(raw.rssi),
    temperature_c: toNumberOrNull(raw.temperature_c),
    node: toStringOrNull(raw.node),
    building: toStringOrNull(raw.building),
    deployment: toStringOrNull(raw.deployment),
    friendly_name: toStringOrNull(raw.friendly_name),
    outlet_location: toStringOrNull(raw.outlet_location),
    online: Boolean(raw.online),
    last_seen: toStringOrNull(raw.last_seen),
    power_w: toNumberOrNull(raw.power_w),
    voltage_v: toNumberOrNull(raw.voltage_v),
    current_a: toNumberOrNull(raw.current_a),
    power_factor: toNumberOrNull(raw.power_factor),
    energy_today_kwh: toNumberOrNull(raw.energy_today_kwh),
  };
};

export interface UseSmartPlugsResult {
  plugs: SmartPlug[];
  source: SmartPlugSource;
  assign: (plugId: string, assignment: SmartPlugAssignment) => Promise<void>;
  reload: () => void;
}

export function useSmartPlugs(deploymentId?: number | null): UseSmartPlugsResult {
  const [plugs, setPlugs] = useState<SmartPlug[]>([]);
  const [source, setSource] = useState<SmartPlugSource>("loading");

  const sourceRef = useRef<SmartPlugSource>("loading");

  const setSourceTracked = useCallback((next: SmartPlugSource) => {
    sourceRef.current = next;
    setSource(next);
  }, []);

  const load = useCallback(async () => {
    try {
      // Sin despliegue seleccionado se pide el inventario completo, igual que
      // antes; con uno, sólo los enchufes asignados a ese despliegue.
      const data = await getSmartPlugs(deploymentId);
      const list = Array.isArray(data) ? data : data?.smart_plugs || [];
      setPlugs(list.map(normalize));
      setSourceTracked("api");
    } catch {
      // Un fallo de red no debe borrar el último inventario bueno en pantalla:
      // se conserva lo mostrado y sólo se marca el estado como error.
      setSourceTracked("error");
    }
  }, [setSourceTracked, deploymentId]);

  useEffect(() => {
    // La primera carga también se agenda en el temporizador: así el estado
    // sólo se actualiza desde la respuesta del API, nunca durante el efecto.
    const firstLoad = setTimeout(load, 0);
    const timer = setInterval(load, POLL_INTERVAL_MS);

    return () => {
      clearTimeout(firstLoad);
      clearInterval(timer);
    };
  }, [load]);

  const assign = useCallback(
    async (plugId: string, assignment: SmartPlugAssignment) => {
      // La asignación se persiste en el backend o falla de forma visible: nunca
      // se finge un guardado que en realidad no ocurrió.
      await assignSmartPlug(plugId, assignment);
      await load();
    },
    [load]
  );

  return { plugs, source, assign, reload: load };
}
