import { useEffect, useState } from "react";
import {
  User, Mail, Shield, MapPin, Clock, LogOut, Check, X, Minus,
  Zap, AlertTriangle, DollarSign, Database, BrainCircuit,
  Building2, Globe, Server, Activity, RefreshCw, Save,
  ChevronDown, Info, Cpu, Radio, Gauge, Lock,
} from "lucide-react";
import { api } from "../services/api";

// ─── Design tokens ────────────────────────────────────────────────────────────
const T = {
  bg:      "#0a0a0f",
  surf:    "#111120",
  surfHi:  "#141428",
  border:  "#1e1c35",
  borderS: "#17162c",
  txt:     "#e4e1f5",
  sec:     "#a09cc0",
  muted:   "#5c5880",
  accent:  "#8b5cf6",
  accentL: "#a78bfa",
  accentD: "#6d3fd4",
  green:   "#22c55e",
  amber:   "#f59e0b",
  red:     "#ef4444",
  blue:    "#60a5fa",
};

const ROLES = ["Administrador", "Ejecutivo", "Técnico", "Investigador"];

// ─── Permissions matrix ───────────────────────────────────────────────────────
const PERMISSIONS = [
  { page: "Dashboard Ejecutivo",    admin: "full",  exec: "full",  tech: "read", inv: "read"  },
  { page: "Mapa de Campus",         admin: "full",  exec: "full",  tech: "read", inv: "read"  },
  { page: "Edificios",              admin: "full",  exec: "read",  tech: "full", inv: "read"  },
  { page: "Despliegues",            admin: "full",  exec: "none",  tech: "full", inv: "none"  },
  { page: "Monitoreo en Vivo",      admin: "full",  exec: "read",  tech: "full", inv: "read"  },
  { page: "Análisis de Costo",      admin: "full",  exec: "full",  tech: "read", inv: "read"  },
  { page: "Centro IA / Forecasting",admin: "full",  exec: "read",  tech: "none", inv: "full"  },
  { page: "Minería de Datos",       admin: "full",  exec: "none",  tech: "none", inv: "full"  },
  { page: "Explorador de Datos",    admin: "full",  exec: "read",  tech: "full", inv: "full"  },
  { page: "Reportes",               admin: "full",  exec: "full",  tech: "read", inv: "full"  },
  { page: "Infraestructura",        admin: "full",  exec: "none",  tech: "full", inv: "none"  },
  { page: "Configuración",          admin: "full",  exec: "none",  tech: "none", inv: "none"  },
];

// ─── Default settings ─────────────────────────────────────────────────────────
const DEFAULT_SETTINGS = {
  user: {
    name:       "Dr. Carlos Mendoza",
    email:      "c.mendoza@ucol.mx",
    role:       "Administrador",
    campus:     "Campus Colima",
    lastLogin:  "13 Ene 2025, 08:41",
    sessionStatus: "Activa",
  },
  thresholds: {
    minPowerFactor:   0.90,
    maxCurrent:       200,
    voltageDeviation: 10,
    freqDeviation:    0.5,
    costAnomaly:      30,
    demandSpike:      25,
    nodeOfflineTimeout: 300,
  },
  tariff: {
    active:      "GDMTH",
    source:      "Manual (fallback)",
    baseRate:    31.98,
    interRate:   40.95,
    peakRate:    145.36,
    lastUpdate:  "Enero 2025",
    apiStatus:   "No conectado",
    apiNote:     "Integración CFE en desarrollo",
  },
  retention: {
    edgeDays:      7,
    backendDays:   "Ilimitado",
    readingInterval: 15,
    syncInterval:  60,
    bufferRecords: 3,
    bufferStatus:  "Normal",
  },
  ai: {
    forecasting:      { enabled: true,  model: "Random Forest",     version: "v2.1" },
    anomaly:          { enabled: true,  model: "Isolation Forest",  version: "v1.4" },
    clustering:       { enabled: true,  model: "K-Means",           version: "v1.0" },
    confidence:       "Backtesting sobre historial disponible",
    minHistoryDays:   7,
  },
  system: {
    campuses:          3,
    buildings:         8,
    monitoredBuildings:2,
    activeDeployments: 2,
    totalNodes:        2,
    totalReadings:     14850,
    coveragePct:       25,
    frontendVersion:   "1.3.0",
    backendVersion:    "No conectado",
    apiVersion:        "v1 (mock)",
  },
};

// ─── Reusable primitives ──────────────────────────────────────────────────────

const Card = ({ children, style }) => (
  <div style={{
    background: T.surf, border: `1px solid ${T.border}`, borderRadius: 10,
    padding: "20px 22px", ...style,
  }}>
    {children}
  </div>
);

const CardTitle = ({ icon: Icon, title, sub, action }) => (
  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 }}>
    <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
      <div style={{
        width: 30, height: 30, borderRadius: 7, background: "rgba(139,92,246,.1)",
        border: `1px solid rgba(139,92,246,.2)`, display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
      }}>
        <Icon size={14} color={T.accentL} strokeWidth={1.8} />
      </div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: T.txt, letterSpacing: 0.1 }}>{title}</div>
        {sub && <div style={{ fontSize: 11, color: T.muted, marginTop: 1 }}>{sub}</div>}
      </div>
    </div>
    {action}
  </div>
);

const Divider = ({ style }) => (
  <div style={{ height: 1, background: T.borderS, ...style }} />
);

const Row = ({ label, value, valueColor, mono }) => (
  <div style={{
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "8px 0", borderBottom: `1px solid ${T.borderS}`,
  }}>
    <span style={{ fontSize: 12, color: T.muted }}>{label}</span>
    <span style={{
      fontSize: 12.5, fontWeight: 600, color: valueColor || T.txt,
      fontFamily: mono ? "monospace" : "inherit",
      fontVariantNumeric: "tabular-nums",
    }}>{value}</span>
  </div>
);

const StatusDot = ({ status }) => {
  const map = { online: T.green, warning: T.amber, offline: T.muted, ok: T.green };
  const clr = map[status] || T.muted;
  return (
    <span style={{
      width: 6, height: 6, borderRadius: "50%", background: clr, display: "inline-block",
      boxShadow: status === "online" || status === "ok" ? `0 0 5px ${clr}88` : "none",
      animation: status === "online" ? "pulse-s 2.5s infinite ease-in-out" : "none",
      flexShrink: 0,
    }} />
  );
};

const Chip = ({ children, variant = "default" }) => {
  const v = {
    default: { bg: "rgba(255,255,255,.04)", color: T.sec,   border: T.border },
    success: { bg: "rgba(34,197,94,.08)",   color: T.green, border: "rgba(34,197,94,.2)" },
    warning: { bg: "rgba(245,158,11,.08)",  color: T.amber, border: "rgba(245,158,11,.2)" },
    danger:  { bg: "rgba(239,68,68,.08)",   color: T.red,   border: "rgba(239,68,68,.2)" },
    accent:  { bg: "rgba(139,92,246,.1)",   color: T.accentL, border: "rgba(139,92,246,.25)" },
  }[variant] || {};
  return (
    <span style={{
      fontSize: 10.5, fontWeight: 600, letterSpacing: 0.3, padding: "3px 9px",
      borderRadius: 4, border: `1px solid ${v.border}`,
      background: v.bg, color: v.color, whiteSpace: "nowrap",
    }}>{children}</span>
  );
};

// Editable threshold field
const ThresholdRow = ({ icon: Icon, label, value, unit, onChange, warn, mono }) => {
  const [editing, setEditing] = useState(false);
  const [local, setLocal] = useState(value);
  const commit = () => { onChange(local); setEditing(false); };
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "9px 0", borderBottom: `1px solid ${T.borderS}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {Icon && <Icon size={12} color={T.muted} strokeWidth={1.8} />}
        <span style={{ fontSize: 12, color: T.muted }}>{label}</span>
        {warn && <AlertTriangle size={11} color={T.amber} />}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {editing ? (
          <>
            <input
              type="number"
              value={local}
              onChange={e => setLocal(e.target.value)}
              onKeyDown={e => e.key === "Enter" && commit()}
              autoFocus
              style={{
                width: 80, background: T.surfHi, border: `1px solid ${T.accentL}`,
                borderRadius: 5, color: T.txt, fontSize: 12, padding: "4px 8px",
                outline: "none", fontVariantNumeric: "tabular-nums", textAlign: "right",
              }}
            />
            <span style={{ fontSize: 11, color: T.muted }}>{unit}</span>
            <button onClick={commit} style={{ background: "none", border: "none", cursor: "pointer", color: T.green, display: "flex" }}>
              <Check size={13} />
            </button>
            <button onClick={() => setEditing(false)} style={{ background: "none", border: "none", cursor: "pointer", color: T.muted, display: "flex" }}>
              <X size={13} />
            </button>
          </>
        ) : (
          <>
            <span style={{ fontSize: 13, fontWeight: 700, color: T.txt, fontVariantNumeric: "tabular-nums" }}>
              {local} <span style={{ fontSize: 11, fontWeight: 400, color: T.muted }}>{unit}</span>
            </span>
            <button
              onClick={() => setEditing(true)}
              style={{
                background: "rgba(139,92,246,.08)", border: `1px solid rgba(139,92,246,.2)`,
                borderRadius: 5, color: T.accentL, fontSize: 10.5, cursor: "pointer",
                padding: "2px 8px", fontWeight: 600,
              }}
            >
              Editar
            </button>
          </>
        )}
      </div>
    </div>
  );
};

// Toggle switch
const Toggle = ({ enabled, onChange, label, sub }) => (
  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${T.borderS}` }}>
    <div>
      <div style={{ fontSize: 12.5, fontWeight: 500, color: T.txt }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>{sub}</div>}
    </div>
    <div
      onClick={() => onChange(!enabled)}
      style={{
        width: 36, height: 20, borderRadius: 10, background: enabled ? T.accent : T.border,
        position: "relative", cursor: "pointer", transition: "background .2s", flexShrink: 0,
      }}
    >
      <div style={{
        width: 14, height: 14, borderRadius: "50%", background: "#fff",
        position: "absolute", top: 3, left: enabled ? 19 : 3, transition: "left .2s",
      }} />
    </div>
  </div>
);

// Permission icon cell
const PermIcon = ({ level }) => {
  if (level === "full") return (
    <span style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Check size={13} color={T.green} strokeWidth={2.5} />
    </span>
  );
  if (level === "read") return (
    <span style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Minus size={13} color={T.amber} strokeWidth={2.5} />
    </span>
  );
  return (
    <span style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
      <X size={12} color={T.muted} strokeWidth={2} />
    </span>
  );
};

// Coverage bar
const CoverageBar = ({ pct }) => (
  <div>
    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 11 }}>
      <span style={{ color: T.muted }}>Cobertura de monitoreo</span>
      <span style={{ color: T.accentL, fontWeight: 700 }}>{pct}%</span>
    </div>
    <div style={{ height: 5, background: T.surfHi, borderRadius: 3, overflow: "hidden", border: `1px solid ${T.borderS}` }}>
      <div style={{ height: "100%", width: `${pct}%`, background: `linear-gradient(90deg, ${T.accentD}, ${T.accentL})`, borderRadius: 3 }} />
    </div>
  </div>
);

// ─── Main component ───────────────────────────────────────────────────────────
export default function PageSettings({ role, setRole, settings, onLogout }) {
  const [realSettings, setRealSettings] = useState(settings || null);
  const S = realSettings || settings || DEFAULT_SETTINGS;

  useEffect(() => {
    const sessionEmail = localStorage.getItem("energy_user") || "admin@ucol.mx";
    const sessionRole = localStorage.getItem("energy_role") || role || "Administrador";
    const sessionStarted = localStorage.getItem("energy_session_started") || new Date().toLocaleString("es-MX");

    if (!localStorage.getItem("energy_session_started")) {
      localStorage.setItem("energy_session_started", sessionStarted);
    }

    const load = async () => {
      const [
        nodesRes,
        buildingsRes,
        dashboardRes,
        systemRes,
        infraRes,
        campusesRes,
      ] = await Promise.allSettled([
        api.get("/nodes"),
        api.get("/buildings"),
        api.get("/dashboard/summary"),
        api.get("/settings"),
        api.get("/infra"),
        api.get("/metrics/campuses"),
      ]);

      const nodes = nodesRes.status === "fulfilled" ? nodesRes.value.data || [] : [];
      const buildings = buildingsRes.status === "fulfilled" ? buildingsRes.value.data || [] : [];
      const dashboard = dashboardRes.status === "fulfilled" ? dashboardRes.value.data || {} : {};
      const system = systemRes.status === "fulfilled" ? systemRes.value.data || {} : {};
      const infra = infraRes.status === "fulfilled" ? infraRes.value.data || {} : {};
      const campuses = campusesRes.status === "fulfilled" ? campusesRes.value.data || [] : [];

      const tariffs = system.tariff || {};
      const counts = system.counts || {};
      const thresholdsFromApi = system.thresholds || {};
      const systemInfo = system.system || {};
      const infraSummary = infra.summary || {};
      const infraNodes = infra.nodes || nodes;

      const onlineNodes = nodes.filter(n => n.status === "online").length;
      const totalNodes = nodes.length;
      const monitoredBuildings = buildings.filter(b => b.node || b.status === "monitored" || b.status === "online").length;
      const totalBuildings = buildings.length;
      const totalReadings =
        Number(counts.readings || counts.total_readings || infraSummary.total_readings || dashboard.total_readings || 0);

      const pendingBuffer = nodes.reduce((sum, n) => sum + Number(n.buffer_pending || n.buffer || 0), 0);
      const totalSamples = nodes.reduce((sum, n) => sum + Number(n.samples || 0), 0);
      const coveragePct = totalBuildings > 0 ? Math.round((monitoredBuildings / totalBuildings) * 100) : 0;

      setRealSettings({
        user: {
          name: sessionEmail.split("@")[0],
          email: sessionEmail,
          role: sessionRole,
          campus: sessionRole === "Administrador" ? "Todos los campus" : (nodes[0]?.campus || buildings[0]?.campus || "Sin campus asignado"),
          lastLogin: sessionStarted,
          sessionStatus: "Activa",
        },
        thresholds: {
          minPowerFactor: thresholdsFromApi.min_power_factor ?? thresholdsFromApi.minPowerFactor ?? 0.90,
          maxCurrent: thresholdsFromApi.max_current ?? thresholdsFromApi.maxCurrent ?? 200,
          voltageDeviation: thresholdsFromApi.voltage_deviation ?? thresholdsFromApi.voltageDeviation ?? 10,
          freqDeviation: thresholdsFromApi.frequency_deviation ?? thresholdsFromApi.freqDeviation ?? 0.5,
          costAnomaly: thresholdsFromApi.cost_anomaly ?? thresholdsFromApi.costAnomaly ?? 30,
          demandSpike: thresholdsFromApi.demand_spike ?? thresholdsFromApi.demandSpike ?? 25,
          nodeOfflineTimeout: thresholdsFromApi.node_offline_timeout ?? thresholdsFromApi.nodeOfflineTimeout ?? 300,
        },
        tariff: {
          active: tariffs.active || tariffs.name || "GDMTH",
          source: tariffs.source || "Manual fallback",
          baseRate: tariffs.baseRate ?? 1.0375,
          interRate: tariffs.interRate ?? 1.8463,
          peakRate: tariffs.peakRate ?? 2.0789,
          lastUpdate: tariffs.lastUpdate || "Configuración persistente local",
          apiStatus: tariffs.apiStatus || "Pendiente",
          apiNote: tariffs.apiNote || "Scraper/API CFE pendiente",
        },
        retention: {
          edgeDays: 7,
          backendDays: "Ilimitado",
          readingInterval: 15,
          syncInterval: 60,
          bufferRecords: pendingBuffer,
          bufferStatus: pendingBuffer > 0 ? "Pendiente" : "Sin pendientes",
        },
        ai: {
          forecasting: system.ai?.forecasting || { enabled: true, model: "Random Forest" },
          anomaly: system.ai?.anomaly || { enabled: true, model: "Isolation Forest" },
          clustering: system.ai?.clustering || { enabled: true, model: "K-Means" },
          confidence: "Backtesting cuando existe historial suficiente",
          minHistoryDays: 7,
        },
        system: {
          campuses: new Set([...buildings.map(b => b.campus).filter(Boolean), ...nodes.map(n => n.campus).filter(Boolean)]).size,
          buildings: totalBuildings,
          monitoredBuildings,
          activeDeployments: dashboard.active_deployments || 0,
          totalNodes,
          totalReadings: totalReadings || totalSamples,
          coveragePct,
          frontendVersion: systemInfo.frontendVersion || "React/Vite activo",
          backendVersion: systemInfo.backendVersion || "FastAPI activo",
          apiVersion: systemInfo.apiVersion || "v1",
          nodes: infraNodes,
          onlineNodes,
        },
      });
    };

    load().catch(error => console.error("Settings real data load error:", error));
  }, [role]);

  // Local editable state
  const [thresholds, setThresholds] = useState({ ...S.thresholds });
  const [aiConfig,   setAiConfig]   = useState({ ...S.ai });
  const [saved,      setSaved]      = useState(false);
  const [roleOpen,   setRoleOpen]   = useState(false);

  useEffect(() => {
    setThresholds({ ...S.thresholds });
    setAiConfig({ ...S.ai });
  }, [realSettings]);

  const updateThreshold = (key, val) =>
    setThresholds(t => ({ ...t, [key]: parseFloat(val) }));

  const updateAiToggle = (key, val) =>
    setAiConfig(c => ({ ...c, [key]: { ...c[key], enabled: val } }));

  const handleSave = async () => {
    try {
      const response = await api.put("/settings", {
        thresholds,
        ai: aiConfig,
        retention: S.retention,
        tariff: S.tariff,
      });
      setRealSettings(current => ({ ...(current || S), ...response.data }));
      setSaved(true);
      setTimeout(() => setSaved(false), 2800);
    } catch (error) {
      console.error("Settings save error:", error);
      alert("No se pudieron guardar los cambios.");
    }
  };

  const roleMap = {
    Administrador: { chip: "accent",   label: "Administrador" },
    Ejecutivo:     { chip: "default",  label: "Ejecutivo" },
    Técnico:       { chip: "warning",  label: "Técnico" },
    Investigador:  { chip: "default",  label: "Investigador" },
  };

  const pCol = (r) => ({
    Administrador: "admin",
    Ejecutivo:     "exec",
    Técnico:       "tech",
    Investigador:  "inv",
  }[r] || "admin");

  return (
    <>
      <style>{`
        @keyframes pulse-s{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.75)}}
        @keyframes fade-in-s{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
      `}</style>

      <div style={{ animation: "fade-in-s .25s ease", paddingBottom: 48 }}>

        {/* ── Page header ─────────────────────────────────────────────── */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 700, color: T.txt, letterSpacing: -0.4, marginBottom: 4 }}>
              Configuración
            </h1>
            <p style={{ fontSize: 12.5, color: T.muted }}>
              Gestión de cuenta, permisos, umbrales operativos y parámetros del sistema
            </p>
          </div>
          {saved && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8, padding: "7px 14px",
              background: "rgba(34,197,94,.08)", border: "1px solid rgba(34,197,94,.2)",
              borderRadius: 7, fontSize: 12.5, color: T.green, fontWeight: 500,
              animation: "fade-in-s .2s ease",
            }}>
              <Check size={13} color={T.green} />
              Cambios guardados en backend
            </div>
          )}
        </div>

        {/* ── Grid layout ─────────────────────────────────────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>

          {/* ══ 1. User & Session ══════════════════════════════════════ */}
          <Card>
            <CardTitle icon={User} title="Usuario y Sesión" sub="Perfil activo e información de acceso"
              action={
                <button onClick={onLogout || (() => {})} style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "6px 13px",
                  background: "rgba(239,68,68,.08)", border: "1px solid rgba(239,68,68,.2)",
                  borderRadius: 6, color: T.red, fontSize: 12, fontWeight: 600, cursor: "pointer",
                }}>
                  <LogOut size={12} color={T.red} strokeWidth={2} />
                  Cerrar sesión
                </button>
              }
            />
            {/* Avatar row */}
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 18 }}>
              <div style={{
                width: 46, height: 46, borderRadius: 12,
                background: "linear-gradient(135deg,rgba(139,92,246,.3),rgba(109,40,217,.4))",
                border: "1px solid rgba(139,92,246,.3)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 16, fontWeight: 700, color: T.accentL, flexShrink: 0, letterSpacing: 0.5,
              }}>{(S.user.email || "U").slice(0,2).toUpperCase()}</div>
              <div>
                <div style={{ fontSize: 14.5, fontWeight: 700, color: T.txt }}>{S.user.name}</div>
                <div style={{ fontSize: 11.5, color: T.muted, marginTop: 2 }}>{S.user.email}</div>
                <div style={{ marginTop: 5 }}>
                  <Chip variant={roleMap[role]?.chip || "accent"}>{role}</Chip>
                </div>
              </div>
            </div>
            <Divider style={{ marginBottom: 12 }} />
            {[
              { icon: Mail,   label: "Correo institucional", value: S.user.email,         mono: true },
              { icon: Shield, label: "Rol actual",           value: role },
              { icon: MapPin, label: "Campus asignado",      value: S.user.campus },
              { icon: Clock,  label: "Último acceso",        value: S.user.lastLogin },
            ].map(({ icon: Icon, label, value, mono }) => (
              <div key={label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 0", borderBottom: `1px solid ${T.borderS}` }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <Icon size={12} color={T.muted} strokeWidth={1.8} />
                  <span style={{ fontSize: 12, color: T.muted }}>{label}</span>
                </div>
                <span style={{ fontSize: 12.5, fontWeight: 600, color: T.txt, fontFamily: mono ? "monospace" : "inherit" }}>{value}</span>
              </div>
            ))}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 0" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <Activity size={12} color={T.muted} strokeWidth={1.8} />
                <span style={{ fontSize: 12, color: T.muted }}>Estado de sesión</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <StatusDot status="online" />
                <span style={{ fontSize: 12.5, fontWeight: 600, color: T.green }}>Activa</span>
              </div>
            </div>

            <Divider style={{ margin: "14px 0" }} />

            {/* Role switcher */}
            <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, textTransform: "uppercase", letterSpacing: 0.9, marginBottom: 9 }}>
              Cambiar rol de sesión
            </div>
            <div style={{ position: "relative" }}>
              <button
                onClick={() => setRoleOpen(o => !o)}
                style={{
                  width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "8px 12px", background: T.surfHi, border: `1px solid ${T.border}`,
                  borderRadius: 7, color: T.txt, fontSize: 13, cursor: "pointer",
                }}
              >
                <span style={{ fontWeight: 600 }}>{role}</span>
                <ChevronDown size={13} color={T.muted} />
              </button>
              {roleOpen && (
                <div style={{
                  position: "absolute", top: "calc(100% + 5px)", left: 0, right: 0, zIndex: 50,
                  background: "#0e0d1e", border: `1px solid ${T.border}`, borderRadius: 8,
                  overflow: "hidden", boxShadow: "0 8px 32px rgba(0,0,0,.55)",
                }}>
                  {ROLES.map(r => (
                    <div key={r} onClick={() => { setRole(r); setRoleOpen(false); }} style={{
                      padding: "9px 13px", cursor: "pointer", fontSize: 13,
                      color: r === role ? T.accentL : T.sec, fontWeight: r === role ? 700 : 400,
                      background: r === role ? "rgba(139,92,246,.1)" : "transparent",
                      borderBottom: `1px solid ${T.borderS}`,
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      transition: "background .1s",
                    }}
                      onMouseEnter={e => e.currentTarget.style.background = "rgba(139,92,246,.06)"}
                      onMouseLeave={e => e.currentTarget.style.background = r === role ? "rgba(139,92,246,.1)" : "transparent"}
                    >
                      {r}
                      {r === role && <Check size={12} color={T.accentL} />}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>

          {/* ══ 5. Data Retention & Sampling ═══════════════════════════ */}
          <Card>
            <CardTitle icon={Database} title="Retención de Datos y Muestreo"
              sub="Configuración de almacenamiento edge y sincronía con backend" />
            {[
              { label: "Retención en nodo edge",        value: `${S.retention.edgeDays} días`,            color: null },
              { label: "Retención en backend",          value: S.retention.backendDays,                   color: T.green },
              { label: "Intervalo de lectura",          value: `${S.retention.readingInterval} s`,         color: null },
              { label: "Intervalo de sincronía",        value: `${S.retention.syncInterval} s`,            color: null },
            ].map(r => <Row key={r.label} label={r.label} value={r.value} valueColor={r.color} />)}

            <div style={{ padding: "9px 0", borderBottom: `1px solid ${T.borderS}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <Database size={12} color={T.muted} strokeWidth={1.8} />
                <span style={{ fontSize: 12, color: T.muted }}>Buffer edge pendiente</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: S.retention.bufferRecords > 0 ? T.amber : T.green }}>
                  {S.retention.bufferRecords} registros
                </span>
                <Chip variant={S.retention.bufferRecords > 0 ? "warning" : "success"}>
                  {S.retention.bufferStatus}
                </Chip>
              </div>
            </div>

            <Divider style={{ margin: "16px 0 14px" }} />
            <CardTitle icon={BrainCircuit} title="Configuración IA"
              sub="Modelos de análisis automático activos en la plataforma" />

            {[
              { key: "forecasting", label: "Forecasting de consumo y costo", model: aiConfig.forecasting.model,  version: aiConfig.forecasting.version  },
              { key: "anomaly",     label: "Detección de anomalías",          model: aiConfig.anomaly.model,      version: aiConfig.anomaly.version      },
              { key: "clustering",  label: "Clustering de edificios",         model: aiConfig.clustering.model,   version: aiConfig.clustering.version   },
            ].map(it => (
              <div key={it.key} style={{ padding: "9px 0", borderBottom: `1px solid ${T.borderS}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontSize: 12.5, fontWeight: 500, color: T.txt, marginBottom: 2 }}>{it.label}</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <Chip variant="accent">{it.model}</Chip>
                      {it.version && <span style={{ fontSize: 10.5, color: T.muted }}>{it.version}</span>}
                    </div>
                  </div>
                  <div onClick={() => updateAiToggle(it.key, !aiConfig[it.key].enabled)} style={{
                    width: 34, height: 19, borderRadius: 10,
                    background: aiConfig[it.key].enabled ? T.accent : T.border,
                    position: "relative", cursor: "pointer", transition: "background .2s", flexShrink: 0,
                  }}>
                    <div style={{
                      width: 13, height: 13, borderRadius: "50%", background: "#fff",
                      position: "absolute", top: 3, left: aiConfig[it.key].enabled ? 18 : 3, transition: "left .2s",
                    }} />
                  </div>
                </div>
              </div>
            ))}
            <div style={{ padding: "9px 0", display: "flex", alignItems: "flex-start", gap: 7 }}>
              <Info size={12} color={T.muted} style={{ marginTop: 1, flexShrink: 0 }} strokeWidth={1.8} />
              <div>
                <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.6 }}>
                  Metodología de confianza: <span style={{ color: T.sec }}>{aiConfig.confidence}</span>
                </div>
                <div style={{ fontSize: 11, color: T.muted }}>
                  Historial mínimo requerido: <span style={{ color: T.sec }}>{aiConfig.minHistoryDays} días</span>
                </div>
              </div>
            </div>
          </Card>

          {/* ══ 3. Anomaly Thresholds ═══════════════════════════════════ */}
          <Card>
            <CardTitle icon={AlertTriangle} title="Reglas de Energía / Umbrales de Anomalía"
              sub="Valores de referencia para detección automática de condiciones anómalas"
              action={
                <button onClick={handleSave} style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "6px 13px",
                  background: "linear-gradient(135deg,#6d52b8,#4a35a0)",
                  border: "none", borderRadius: 6, color: "#fff",
                  fontSize: 12, fontWeight: 600, cursor: "pointer",
                }}>
                  <Save size={12} color="#fff" strokeWidth={2} />
                  Guardar
                </button>
              }
            />
            <ThresholdRow icon={Gauge}       label="Factor de potencia mínimo"  value={thresholds.minPowerFactor}    unit=""    onChange={v => updateThreshold("minPowerFactor", v)}    warn={thresholds.minPowerFactor < 0.90} />
            <ThresholdRow icon={Zap}         label="Corriente máxima"           value={thresholds.maxCurrent}        unit="A"   onChange={v => updateThreshold("maxCurrent", v)} />
            <ThresholdRow icon={Radio}       label="Desviación de voltaje"       value={thresholds.voltageDeviation}  unit="%"   onChange={v => updateThreshold("voltageDeviation", v)} />
            <ThresholdRow icon={Activity}    label="Desviación de frecuencia"    value={thresholds.freqDeviation}     unit="Hz"  onChange={v => updateThreshold("freqDeviation", v)} />
            <ThresholdRow icon={DollarSign}  label="Anomalía de costo"           value={thresholds.costAnomaly}       unit="%"   onChange={v => updateThreshold("costAnomaly", v)} />
            <ThresholdRow icon={AlertTriangle} label="Pico de demanda"           value={thresholds.demandSpike}       unit="%"   onChange={v => updateThreshold("demandSpike", v)} />
            <ThresholdRow icon={Clock}       label="Tiempo fuera de línea (nodo)" value={thresholds.nodeOfflineTimeout} unit="s" onChange={v => updateThreshold("nodeOfflineTimeout", v)} />

            <div style={{ marginTop: 14, padding: "10px 12px", background: "rgba(245,158,11,.05)", border: "1px solid rgba(245,158,11,.15)", borderRadius: 7, display: "flex", gap: 8 }}>
              <Info size={12} color={T.amber} style={{ marginTop: 1, flexShrink: 0 }} strokeWidth={1.8} />
              <span style={{ fontSize: 11.5, color: T.sec, lineHeight: 1.6 }}>
                Los cambios en umbrales afectan la detección de anomalías en tiempo real y los reportes del Centro IA. Requiere confirmación del administrador.
              </span>
            </div>
          </Card>

          {/* ══ 4. Tariff Configuration ════════════════════════════════ */}
          <Card>
            <CardTitle icon={DollarSign} title="Configuración Tarifaria"
              sub="Parámetros CFE activos para el cálculo de costo estimado"
              action={<Chip variant="warning">Manual</Chip>}
            />
            <div style={{ background: T.surfHi, border: `1px solid ${T.border}`, borderRadius: 8, padding: "14px 16px", marginBottom: 14 }}>
              <div style={{ fontSize: 10.5, color: T.muted, textTransform: "uppercase", letterSpacing: 0.9, fontWeight: 600, marginBottom: 5 }}>
                Tarifa activa
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, color: T.accentL, letterSpacing: -0.5 }}>
                {S.tariff.active}
              </div>
              <div style={{ fontSize: 11.5, color: T.muted, marginTop: 3 }}>
                Gran Demanda en Media Tensión H — CFE
              </div>
            </div>

            {[
              { label: "Cargo base",             value: `$${S.tariff.baseRate}/kWh`,   color: null },
              { label: "Cargo intermedia",       value: `$${S.tariff.interRate}/kWh`,  color: null },
              { label: "Cargo punta",            value: `$${S.tariff.peakRate}/kWh`,   color: T.red },
              { label: "Fuente",                 value: S.tariff.source,               color: T.amber },
              { label: "Última actualización",   value: S.tariff.lastUpdate,           color: null },
            ].map(r => <Row key={r.label} label={r.label} value={r.value} valueColor={r.color} />)}

            <Divider style={{ margin: "14px 0" }} />
            <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, textTransform: "uppercase", letterSpacing: 0.9, marginBottom: 9 }}>
              Integración CFE API / Scraper
            </div>
            <div style={{ padding: "10px 12px", background: T.surfHi, border: `1px solid ${T.border}`, borderRadius: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 500, color: T.sec }}>{S.tariff.apiNote}</div>
                <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>
                  Estado: <span style={{ color: T.amber }}>{S.tariff.apiStatus}</span>
                </div>
              </div>
              <button style={{
                padding: "6px 14px", background: T.surfHi, border: `1px solid ${T.border}`,
                borderRadius: 6, color: T.muted, fontSize: 11.5, cursor: "not-allowed",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                <RefreshCw size={11} color={T.muted} />
                Sincronizar
              </button>
            </div>
          </Card>

        </div>

        {/* ══ 2. Role Permissions Matrix (full width) ═══════════════════ */}
        <Card style={{ marginTop: 14, padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "18px 22px", borderBottom: `1px solid ${T.borderS}`, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <div style={{
                width: 30, height: 30, borderRadius: 7, background: "rgba(139,92,246,.1)",
                border: "1px solid rgba(139,92,246,.2)", display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                <Lock size={14} color={T.accentL} strokeWidth={1.8} />
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: T.txt }}>Matriz de Permisos por Rol</div>
                <div style={{ fontSize: 11, color: T.muted, marginTop: 1 }}>Control de acceso a páginas según perfil de usuario</div>
              </div>
            </div>
            <div style={{ display: "flex", gap: 12, fontSize: 11, color: T.muted, alignItems: "center" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}><Check size={11} color={T.green} />Acceso completo</span>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}><Minus size={11} color={T.amber} />Solo lectura</span>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}><X size={11} color={T.muted} />Sin acceso</span>
            </div>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: T.surfHi, borderBottom: `1px solid ${T.borderS}` }}>
                <th style={{ padding: "11px 22px", textAlign: "left", fontSize: 10.5, color: T.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.9, width: "40%" }}>
                  Página / Módulo
                </th>
                {["Administrador", "Ejecutivo", "Técnico", "Investigador"].map(r => (
                  <th key={r} style={{ padding: "11px 16px", textAlign: "center", fontSize: 10.5, fontWeight: 700, letterSpacing: 0.4 }}>
                    <span style={{
                      color: r === role ? T.accentL : T.muted,
                      borderBottom: r === role ? `2px solid ${T.accent}` : "none",
                      paddingBottom: r === role ? 2 : 0,
                    }}>{r}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PERMISSIONS.map((p, i) => (
                <tr key={i} style={{
                  borderBottom: `1px solid ${T.borderS}`,
                  background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,.012)",
                  transition: "background .1s",
                }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(139,92,246,.04)"}
                  onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? "transparent" : "rgba(255,255,255,.012)"}
                >
                  <td style={{ padding: "9px 22px", fontSize: 12.5, color: T.sec, fontWeight: 400 }}>{p.page}</td>
                  <td style={{ padding: "9px 16px" }}><PermIcon level={p.admin} /></td>
                  <td style={{ padding: "9px 16px" }}><PermIcon level={p.exec} /></td>
                  <td style={{ padding: "9px 16px" }}><PermIcon level={p.tech} /></td>
                  <td style={{ padding: "9px 16px" }}><PermIcon level={p.inv} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        {/* ══ 7. Coverage & System Info (full width) ════════════════════ */}
        <Card style={{ marginTop: 14 }}>
          <CardTitle icon={Globe} title="Cobertura y Estado del Sistema"
            sub="Estadísticas globales de despliegue y versiones de la plataforma" />

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 22 }}>
            {/* Coverage stats */}
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, textTransform: "uppercase", letterSpacing: 0.9, marginBottom: 10 }}>
                Cobertura de monitoreo
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 14 }}>
                {[
                  { label: "Campus registrados",       value: S.system.campuses,           color: T.txt },
                  { label: "Edificios totales",        value: S.system.buildings,           color: T.txt },
                  { label: "Edificios monitoreados",   value: S.system.monitoredBuildings,  color: T.accentL },
                  { label: "Despliegues activos",      value: S.system.activeDeployments,   color: T.green },
                  { label: "Nodos totales",            value: S.system.totalNodes,          color: T.txt },
                  { label: "Lecturas acumuladas",      value: S.system.totalReadings.toLocaleString(), color: T.txt },
                ].map(it => (
                  <div key={it.label} style={{ background: T.surfHi, borderRadius: 7, padding: "10px 12px", border: `1px solid ${T.borderS}` }}>
                    <div style={{ fontSize: 10.5, color: T.muted, marginBottom: 4 }}>{it.label}</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: it.color, fontVariantNumeric: "tabular-nums" }}>{it.value}</div>
                  </div>
                ))}
              </div>
              <CoverageBar pct={S.system.coveragePct} />
              <div style={{ marginTop: 8, fontSize: 11, color: T.muted }}>
                {S.system.monitoredBuildings} de {S.system.buildings} edificios con monitoreo activo
              </div>
            </div>

            {/* Version info */}
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: T.muted, textTransform: "uppercase", letterSpacing: 0.9, marginBottom: 10 }}>
                Versiones del sistema
              </div>
              {[
                { icon: Globe,  label: "Frontend",        value: S.system.frontendVersion, status: "ok" },
                { icon: Server, label: "Backend",         value: S.system.backendVersion,  status: "ok" },
                { icon: Cpu,    label: "API",             value: S.system.apiVersion,      status: "ok" },
                { icon: Database,label:"Buffer edge",     value: S.retention.bufferRecords > 0 ? `${S.retention.bufferRecords} pendientes` : "Sin pendientes", status: S.retention.bufferRecords > 0 ? "warning" : "ok" },
              ].map((r, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: `1px solid ${T.borderS}` }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <r.icon size={12} color={T.muted} strokeWidth={1.8} />
                    <span style={{ fontSize: 12, color: T.muted }}>{r.label}</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <StatusDot status={r.status} />
                    <span style={{ fontSize: 12.5, fontWeight: 600, color: r.status === "ok" ? T.txt : r.status === "warning" ? T.amber : T.muted, fontFamily: "monospace" }}>
                      {r.value}
                    </span>
                  </div>
                </div>
              ))}

              {/* Node status compact */}
              <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {(S.system.nodes || []).map(n => (
                  <div key={n.id} style={{ background: T.surfHi, border: `1px solid rgba(34,197,94,.15)`, borderRadius: 7, padding: "10px 12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: T.txt }}>{n.id}</span>
                      <StatusDot status={n.status} />
                    </div>
                    <div style={{ fontSize: 10.5, color: T.muted, fontFamily: "monospace" }}>{n.ip}</div>
                    <div style={{ fontSize: 10.5, color: T.muted, marginTop: 2 }}>Sync: {n.last_sync ? new Date(n.last_sync).toLocaleString("es-MX") : "Sin sincronía"}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>

      </div>
    </>
  );
}
