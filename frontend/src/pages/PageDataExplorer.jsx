import { useState, useMemo } from "react";
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  SlidersHorizontal, RefreshCw, Database, Zap, Activity,
  TrendingUp, DollarSign, Gauge, Radio, BarChart2,
  TableProperties, ChevronDown, Check, Clock, AlertTriangle,
} from "lucide-react";

// ─── Design tokens (matches platform) ────────────────────────────────────────
const T = {
  bg:       "#0a0a0f",
  surf:     "#111120",
  surfHi:   "#141428",
  border:   "#1e1c35",
  borderS:  "#181630",
  txt:      "#e4e1f5",
  sec:      "#857fa8",
  muted:    "#413d5e",
  accent:   "#8b5cf6",
  accentL:  "#a78bfa",
  green:    "#22c55e",
  amber:    "#f59e0b",
  red:      "#ef4444",
  blue:     "#60a5fa",
  teal:     "#2dd4bf",
};

// Building color palette — visually distinct on dark bg
const B_COLORS = ["#a78bfa", "#34d399", "#fb923c", "#60a5fa", "#f472b6"];

// ─── Mock data generators ─────────────────────────────────────────────────────
const BUILDINGS = ["FIME", "Lab. de Redes", "Biblioteca", "Rectoría", "Data Center"];
const NODES     = ["N001", "N002", "N003", "N004", "N005"];
const TARIFFS   = ["base", "intermedia", "punta"];
const TARIFF_COLOR = { base: "#6366f1", intermedia: T.amber, punta: T.red };

// Generate 48 half-hour ticks for "last 24 h"
function genSeries() {
  const now   = Date.now();
  const ticks = 48;
  return Array.from({ length: ticks }, (_, i) => {
    const ts = new Date(now - (ticks - 1 - i) * 30 * 60 * 1000);
    const h  = ts.getHours();
    const isPunta   = (h >= 9 && h < 14) || (h >= 16 && h < 18);
    const isInter   = (h >= 6 && h < 9)  || (h >= 14 && h < 16) || (h >= 18 && h < 22);
    const tariff    = isPunta ? "punta" : isInter ? "intermedia" : "base";
    const rate      = isPunta ? 145.36 : isInter ? 40.95 : 31.98;
    const label     = ts.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });

    return {
      ts: ts.toISOString(),
      label,
      fime_kw:   +(3.8 + Math.sin(i / 6) * 1.4 + Math.random() * 0.4).toFixed(3),
      redes_kw:  +(2.1 + Math.cos(i / 5) * 0.9 + Math.random() * 0.3).toFixed(3),
      bib_kw:    +(1.5 + Math.sin(i / 7 + 1) * 0.6 + Math.random() * 0.2).toFixed(3),
      fime_kwh:  +(i * 2.1 + Math.random() * 0.5).toFixed(2),
      redes_kwh: +(i * 1.1 + Math.random() * 0.3).toFixed(2),
      bib_kwh:   +(i * 0.8 + Math.random() * 0.2).toFixed(2),
      fime_v:    +(228 + Math.sin(i / 10) * 3 + Math.random() * 1.2).toFixed(1),
      redes_v:   +(226 + Math.cos(i / 9) * 2 + Math.random() * 1.5).toFixed(1),
      fime_a:    +(18.2 + Math.random() * 2).toFixed(2),
      redes_a:   +(11.8 + Math.random() * 1.8).toFixed(2),
      fime_pf:   +(0.91 + Math.sin(i / 8) * 0.05 - Math.random() * 0.04).toFixed(3),
      redes_pf:  +(0.87 + Math.sin(i / 9) * 0.04 - Math.random() * 0.05).toFixed(3),
      fime_hz:   +(60.01 + (Math.random() - 0.5) * 0.08).toFixed(3),
      redes_hz:  +(59.98 + (Math.random() - 0.5) * 0.06).toFixed(3),
      fime_cost: +(((3.8 + Math.sin(i / 6) * 1.4) * 0.5) * rate).toFixed(2),
      redes_cost:+(((2.1 + Math.cos(i / 5) * 0.9) * 0.5) * rate).toFixed(2),
      tariff,
    };
  });
}

// Heatmap data: buildings × hours
function genHeatmap(buildings) {
  return buildings.map(b => ({
    building: b,
    hours: Array.from({ length: 24 }, (_, h) => {
      const isPunta = (h >= 9 && h < 14) || (h >= 16 && h < 18);
      const isInter = (h >= 6 && h < 9) || (h >= 14 && h < 16) || (h >= 18 && h < 22);
      const base    = isPunta ? 7 : isInter ? 4 : 1.8;
      return +(base + Math.random() * 2).toFixed(2);
    }),
  }));
}

// Recent readings table rows
function genReadings(n = 14) {
  const now = Date.now();
  return Array.from({ length: n }, (_, i) => {
    const ts = new Date(now - i * 3 * 60 * 1000);
    const bIdx = i % 2;
    const b    = BUILDINGS[bIdx];
    const h    = ts.getHours();
    const isPunta = (h >= 9 && h < 14) || (h >= 16 && h < 18);
    const isInter = (h >= 6 && h < 9) || (h >= 14 && h < 16) || (h >= 18 && h < 22);
    const tariff  = isPunta ? "punta" : isInter ? "intermedia" : "base";
    const rate    = isPunta ? 145.36 : isInter ? 40.95 : 31.98;
    const kw      = +(bIdx === 0 ? 3.8 + Math.random() * 1.2 : 2.1 + Math.random() * 0.9).toFixed(3);
    const v       = +(bIdx === 0 ? 228 + Math.random() * 3 : 226 + Math.random() * 4).toFixed(1);
    const a       = +(bIdx === 0 ? 18 + Math.random() * 2 : 12 + Math.random() * 2).toFixed(2);
    const pf      = +(bIdx === 0 ? 0.91 + Math.random() * 0.04 : 0.87 + Math.random() * 0.05).toFixed(3);
    const hz      = +(60 + (Math.random() - 0.5) * 0.1).toFixed(3);
    const kwh     = +(kw * 0.05).toFixed(4);
    const cost    = +(kwh * rate).toFixed(2);
    return {
      ts: ts.toLocaleString("es-MX", { hour: "2-digit", minute: "2-digit", second: "2-digit", day: "2-digit", month: "2-digit" }),
      building: b, node: NODES[bIdx],
      kw, v, a, pf, hz, kwh, tariff, cost,
    };
  });
}

// ─── Reusable sub-components ─────────────────────────────────────────────────

const Card = ({ children, style }) => (
  <div style={{
    background: T.surf, border: `1px solid ${T.border}`, borderRadius: 10,
    padding: "18px 20px", ...style,
  }}>
    {children}
  </div>
);

const SectionLabel = ({ icon: Icon, title, sub, right }) => (
  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
    <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
      {Icon && <Icon size={14} color={T.accentL} strokeWidth={1.8} />}
      <div>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: T.txt, letterSpacing: 0.1 }}>{title}</div>
        {sub && <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>{sub}</div>}
      </div>
    </div>
    {right}
  </div>
);

const Divider = () => <div style={{ height: 1, background: T.borderS, margin: "14px 0" }} />;

const TariffPill = ({ t }) => {
  const map = { base: T.blue, intermedia: T.amber, punta: T.red };
  const clr = map[t] || T.muted;
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase",
      background: `${clr}18`, color: clr, border: `1px solid ${clr}30`,
      borderRadius: 4, padding: "2px 7px",
    }}>{t}</span>
  );
};

const PfBadge = ({ v }) => {
  const ok  = v >= 0.90;
  const clr = ok ? T.green : T.red;
  return (
    <span style={{ color: clr, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
      {v} {!ok && <AlertTriangle size={11} color={T.red} style={{ marginLeft: 3, verticalAlign: "middle" }} />}
    </span>
  );
};

// Custom tooltip for recharts
const ChartTip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "#0d0c1e", border: `1px solid ${T.border}`, borderRadius: 8,
      padding: "10px 14px", fontSize: 12,
    }}>
      <div style={{ color: T.sec, marginBottom: 7, fontWeight: 500 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, color: T.txt, marginBottom: 3 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: p.color, flexShrink: 0, display: "inline-block" }} />
          <span style={{ color: T.sec }}>{p.name}:</span>
          <span style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{p.value}</span>
        </div>
      ))}
    </div>
  );
};

const axisStyle  = { fontSize: 10, fill: T.muted };
const gridStyle  = { stroke: "#181630", strokeDasharray: "3 3" };
const legendStyle = { fontSize: 11, color: T.sec };

// Building line configs
const LINE_CFG = [
  { key: "fime",  label: "FIME" },
  { key: "redes", label: "Lab. de Redes" },
  { key: "bib",   label: "Biblioteca" },
];

// ─── Multi-select dropdown ────────────────────────────────────────────────────
function MultiSelect({ options, selected, onChange, label }) {
  const [open, setOpen] = useState(false);
  const allSel = selected.length === options.length;
  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 8, padding: "7px 12px",
          background: T.surfHi, border: `1px solid ${T.border}`, borderRadius: 7,
          color: T.sec, fontSize: 12.5, cursor: "pointer", minWidth: 180,
          justifyContent: "space-between",
        }}
      >
        <span style={{ color: T.txt }}>
          {selected.length === 0 ? label : selected.length === options.length ? "Todos los edificios" : `${selected.length} edificio(s)`}
        </span>
        <ChevronDown size={13} color={T.muted} />
      </button>
      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 5px)", left: 0, zIndex: 50,
          background: "#0e0d1e", border: `1px solid ${T.border}`, borderRadius: 8,
          minWidth: 200, overflow: "hidden", boxShadow: "0 8px 32px rgba(0,0,0,.5)",
        }}>
          {["__all__", ...options].map((opt, i) => {
            const isAll = opt === "__all__";
            const isSel = isAll ? allSel : selected.includes(opt);
            return (
              <div
                key={i}
                onClick={() => {
                  if (isAll) { onChange(allSel ? [] : [...options]); }
                  else { onChange(isSel ? selected.filter(s => s !== opt) : [...selected, opt]); }
                }}
                style={{
                  display: "flex", alignItems: "center", gap: 9,
                  padding: "9px 13px", cursor: "pointer", fontSize: 12.5,
                  color: isSel ? T.txt : T.sec,
                  background: isSel ? "rgba(139,92,246,.08)" : "transparent",
                  borderBottom: i < options.length ? `1px solid ${T.borderS}` : "none",
                  transition: "background .1s",
                }}
                onMouseEnter={e => e.currentTarget.style.background = "rgba(139,92,246,.06)"}
                onMouseLeave={e => e.currentTarget.style.background = isSel ? "rgba(139,92,246,.08)" : "transparent"}
              >
                <div style={{
                  width: 14, height: 14, borderRadius: 3, flexShrink: 0,
                  border: `1px solid ${isSel ? T.accent : T.border}`,
                  background: isSel ? T.accent : "transparent",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {isSel && <Check size={9} color="#fff" strokeWidth={2.5} />}
                </div>
                {isAll ? <span style={{ fontWeight: 600 }}>Todos los edificios</span> : opt}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Heatmap ─────────────────────────────────────────────────────────────────
function Heatmap({ data }) {
  const maxVal = Math.max(...data.flatMap(r => r.hours));
  const hours  = Array.from({ length: 24 }, (_, i) => i);
  const isPunta = h => (h >= 9 && h < 14) || (h >= 16 && h < 18);
  const isInter = h => (h >= 6 && h < 9) || (h >= 14 && h < 16) || (h >= 18 && h < 22);
  const cellColor = (v) => {
    const t = v / maxVal;
    if (t < 0.25) return `rgba(99,102,241,${0.15 + t * 0.5})`;
    if (t < 0.60) return `rgba(245,158,11,${0.2 + t * 0.5})`;
    return `rgba(239,68,68,${0.25 + t * 0.6})`;
  };
  const CELL_W = 28, CELL_H = 28, LABEL_W = 110;
  return (
    <div style={{ overflowX: "auto" }}>
      {/* Hour axis */}
      <div style={{ display: "flex", marginLeft: LABEL_W, marginBottom: 4 }}>
        {hours.map(h => (
          <div key={h} style={{
            width: CELL_W, flexShrink: 0, textAlign: "center",
            fontSize: 9.5, color: isPunta(h) ? T.red : isInter(h) ? T.amber : T.muted,
            fontWeight: isPunta(h) || isInter(h) ? 600 : 400,
          }}>{String(h).padStart(2, "0")}</div>
        ))}
      </div>
      {/* Rows */}
      {data.map((row, ri) => (
        <div key={ri} style={{ display: "flex", alignItems: "center", marginBottom: 4 }}>
          <div style={{
            width: LABEL_W, flexShrink: 0, fontSize: 11, fontWeight: 500,
            color: T.sec, paddingRight: 10, overflow: "hidden",
            whiteSpace: "nowrap", textOverflow: "ellipsis",
          }}>{row.building}</div>
          {row.hours.map((v, hi) => (
            <div
              key={hi}
              title={`${row.building} — ${String(hi).padStart(2,"0")}:00 → ${v.toFixed(2)} kWh`}
              style={{
                width: CELL_W, height: CELL_H, flexShrink: 0,
                background: cellColor(v), borderRadius: 3, margin: "0 1px",
                cursor: "default", transition: "transform .1s",
              }}
              onMouseEnter={e => { e.currentTarget.style.transform = "scale(1.15)"; e.currentTarget.style.zIndex = 10; }}
              onMouseLeave={e => { e.currentTarget.style.transform = "scale(1)"; e.currentTarget.style.zIndex = 1; }}
            />
          ))}
        </div>
      ))}
      {/* Legend */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10, marginLeft: LABEL_W }}>
        <span style={{ fontSize: 10, color: T.muted }}>Bajo</span>
        {[0.1, 0.3, 0.5, 0.7, 0.9].map(t => (
          <div key={t} style={{ width: 18, height: 12, borderRadius: 2, background: cellColor(t * maxVal) }} />
        ))}
        <span style={{ fontSize: 10, color: T.muted }}>Alto kWh</span>
        <span style={{ marginLeft: 14, fontSize: 10, color: T.muted }}>·</span>
        {[{l:"Base",c:T.blue},{l:"Intermedia",c:T.amber},{l:"Punta",c:T.red}].map(({l,c}) => (
          <span key={l} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: T.muted, marginLeft: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: c, display: "inline-block" }} />{l}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── Summary strip item ───────────────────────────────────────────────────────
const SumItem = ({ icon: Icon, label, value, unit, color = T.accentL }) => (
  <div style={{
    flex: 1, minWidth: 130,
    borderRight: `1px solid ${T.borderS}`,
    padding: "16px 20px",
    display: "flex", flexDirection: "column", gap: 6,
  }}>
    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
      <Icon size={12} color={T.muted} strokeWidth={1.8} />
      <span style={{ fontSize: 10, fontWeight: 600, color: T.muted, textTransform: "uppercase", letterSpacing: 0.9 }}>{label}</span>
    </div>
    <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
      <span style={{ fontSize: 22, fontWeight: 700, color, letterSpacing: -0.5, fontVariantNumeric: "tabular-nums" }}>{value}</span>
      <span style={{ fontSize: 11, color: T.muted }}>{unit}</span>
    </div>
  </div>
);

// ─── Main component ───────────────────────────────────────────────────────────
export default function PageDataExplorer({ data }) {
  // ── State ──────────────────────────────────────────────────────────────────
  const [range,       setRange]    = useState("24h");
  const [selBuildings, setSel]     = useState(["FIME", "Lab. de Redes"]);
  const [compare,     setCompare]  = useState(true);
  const [refreshKey,  setRefresh]  = useState(0);

  // ── Mock data (replaced by `data` prop when backend is connected) ──────────
  const series   = useMemo(() => data?.series         ?? genSeries(),               [refreshKey]);
  const heatRows = useMemo(() => data?.heatmap        ?? genHeatmap(BUILDINGS),     [refreshKey]);
  const readings = useMemo(() => data?.recentReadings ?? genReadings(14),           [refreshKey]);
  const tariffDist = useMemo(() => data?.tariffDistribution ?? [
    { name: "Base",       value: 38.4,  cost: 1228, color: T.blue },
    { name: "Intermedia", value: 82.1,  cost: 3362, color: T.amber },
    { name: "Punta",      value: 29.5,  cost: 4288, color: T.red },
  ], [refreshKey]);
  const summary  = useMemo(() => data?.summary ?? {
    totalKwh: 370.2, totalCost: 8878, avgPf: 0.91,
    maxCurrent: 22.4, minVoltage: 223.8, readings: 2016,
  }, [refreshKey]);

  // ── Active lines based on selection ───────────────────────────────────────
  const activeLines = compare ? LINE_CFG.filter(l => {
    if (l.key === "fime")  return selBuildings.includes("FIME");
    if (l.key === "redes") return selBuildings.includes("Lab. de Redes");
    if (l.key === "bib")   return selBuildings.includes("Biblioteca");
    return false;
  }) : LINE_CFG.slice(0, 1);

  const filteredHeat = heatRows.filter(r => selBuildings.includes(r.building));

  // ── Shared chart props ─────────────────────────────────────────────────────
  const chartMargin = { top: 4, right: 6, left: -16, bottom: 0 };
  const xAxis = <XAxis dataKey="label" tick={axisStyle} tickLine={false} axisLine={{ stroke: T.borderS }} interval={7} />;
  const yAxis = <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={46} />;
  const grid  = <CartesianGrid {...gridStyle} vertical={false} />;
  const tip   = <Tooltip content={<ChartTip />} />;
  const chart_h = 188;

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div style={{ background: T.bg, minHeight: "100vh", padding: "0 0 48px" }}>

      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div style={{ padding: "24px 28px 0" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 700, color: T.txt, letterSpacing: -0.4, marginBottom: 4 }}>
              Explorador de Datos
            </h1>
            <p style={{ fontSize: 12.5, color: T.muted }}>
              Análisis visual de lecturas reales por edificio, nodo y periodo
            </p>
          </div>
          <div style={{
            display: "flex", alignItems: "center", gap: 7, padding: "5px 12px",
            background: "rgba(34,197,94,.07)", border: "1px solid rgba(34,197,94,.18)",
            borderRadius: 6, fontSize: 11.5, fontWeight: 600, color: T.green,
          }}>
            <Database size={12} color={T.green} strokeWidth={1.8} />
            Datos reales
          </div>
        </div>

        {/* ── Filter bar ────────────────────────────────────────────────── */}
        <Card style={{ marginBottom: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <SlidersHorizontal size={14} color={T.muted} strokeWidth={1.8} />

            {/* Range select */}
            <div style={{ position: "relative" }}>
              <select
                value={range}
                onChange={e => setRange(e.target.value)}
                style={{
                  appearance: "none", background: T.surfHi, border: `1px solid ${T.border}`,
                  color: T.txt, borderRadius: 7, padding: "7px 32px 7px 12px",
                  fontSize: 12.5, cursor: "pointer", outline: "none", minWidth: 160,
                }}
              >
                <option value="1h">Última hora</option>
                <option value="24h">Últimas 24 horas</option>
                <option value="7d">Últimos 7 días</option>
                <option value="30d">Últimos 30 días</option>
                <option value="all">Todo el despliegue</option>
              </select>
              <ChevronDown size={13} color={T.muted} style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }} />
            </div>

            {/* Building multi-select */}
            <MultiSelect
              options={["FIME", "Lab. de Redes", "Biblioteca", "Rectoría", "Data Center"]}
              selected={selBuildings}
              onChange={setSel}
              label="Edificios"
            />

            {/* Compare toggle */}
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", userSelect: "none" }}>
              <div
                onClick={() => setCompare(c => !c)}
                style={{
                  width: 34, height: 18, borderRadius: 9, transition: "background .2s",
                  background: compare ? T.accent : T.border, position: "relative", cursor: "pointer",
                }}
              >
                <div style={{
                  width: 12, height: 12, borderRadius: "50%", background: "#fff",
                  position: "absolute", top: 3,
                  left: compare ? 18 : 3, transition: "left .2s",
                }} />
              </div>
              <span style={{ fontSize: 12.5, color: T.sec, fontWeight: 500 }}>Comparar edificios</span>
            </label>

            {/* Update button */}
            <button
              onClick={() => setRefresh(k => k + 1)}
              style={{
                display: "flex", alignItems: "center", gap: 7, padding: "7px 16px",
                background: "linear-gradient(135deg,#6d52b8,#4a35a0)", border: "none",
                borderRadius: 7, color: "#fff", fontSize: 12.5, fontWeight: 600, cursor: "pointer",
              }}
            >
              <RefreshCw size={12} color="#fff" strokeWidth={2} />
              Actualizar vista
            </button>

            <span style={{ fontSize: 11, color: T.muted, marginLeft: "auto" }}>
              <Clock size={11} color={T.muted} style={{ verticalAlign: "middle", marginRight: 4 }} />
              Los gráficos muestran lecturas reales agregadas según el rango seleccionado.
            </span>
          </div>
        </Card>

        {/* ── Charts grid 1: Power + Energy side by side ───────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>

          {/* 1. Potencia activa */}
          <Card>
            <SectionLabel icon={Zap} title="Potencia activa" sub="kW — lecturas cada 30 min" />
            <ResponsiveContainer width="100%" height={chart_h}>
              <LineChart data={series} margin={chartMargin}>
                {grid}{xAxis}{yAxis}{tip}
                {activeLines.map((l, i) => (
                  <Line key={l.key} type="monotone" dataKey={`${l.key}_kw`} name={l.label}
                    stroke={B_COLORS[i]} strokeWidth={1.6} dot={false} />
                ))}
                <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={7} />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          {/* 2. Energía acumulada */}
          <Card>
            <SectionLabel icon={TrendingUp} title="Energía acumulada" sub="kWh — suma progresiva" />
            <ResponsiveContainer width="100%" height={chart_h}>
              <AreaChart data={series} margin={chartMargin}>
                <defs>
                  {activeLines.map((l, i) => (
                    <linearGradient key={l.key} id={`ga${i}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={B_COLORS[i]} stopOpacity={0.25} />
                      <stop offset="100%" stopColor={B_COLORS[i]} stopOpacity={0} />
                    </linearGradient>
                  ))}
                </defs>
                {grid}{xAxis}{yAxis}{tip}
                {activeLines.map((l, i) => (
                  <Area key={l.key} type="monotone" dataKey={`${l.key}_kwh`} name={l.label}
                    stroke={B_COLORS[i]} fill={`url(#ga${i})`} strokeWidth={1.6} dot={false} />
                ))}
                <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={7} />
              </AreaChart>
            </ResponsiveContainer>
          </Card>
        </div>

        {/* ── Charts grid 2: Cost + Current ────────────────────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>

          {/* 3. Costo estimado */}
          <Card>
            <SectionLabel icon={DollarSign} title="Costo estimado" sub="MXN — calculado por tarifa GDMTH" />
            <ResponsiveContainer width="100%" height={chart_h}>
              <AreaChart data={series} margin={chartMargin}>
                <defs>
                  {activeLines.map((l, i) => (
                    <linearGradient key={l.key} id={`gc${i}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={B_COLORS[i]} stopOpacity={0.2} />
                      <stop offset="100%" stopColor={B_COLORS[i]} stopOpacity={0} />
                    </linearGradient>
                  ))}
                </defs>
                {grid}{xAxis}{yAxis}{tip}
                {activeLines.map((l, i) => (
                  <Area key={l.key} type="monotone" dataKey={`${l.key}_cost`} name={l.label}
                    stroke={B_COLORS[i]} fill={`url(#gc${i})`} strokeWidth={1.6} dot={false} />
                ))}
                <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={7} />
              </AreaChart>
            </ResponsiveContainer>
          </Card>

          {/* 4. Corriente total */}
          <Card>
            <SectionLabel icon={Activity} title="Corriente por nodo" sub="A — corriente total (fase no disponible en todos los nodos)" />
            <ResponsiveContainer width="100%" height={chart_h}>
              <LineChart data={series} margin={chartMargin}>
                {grid}{xAxis}{yAxis}{tip}
                {activeLines.map((l, i) => (
                  <Line key={l.key} type="monotone" dataKey={`${l.key}_a`} name={`${l.label} (A)`}
                    stroke={B_COLORS[i]} strokeWidth={1.6} dot={false} strokeDasharray={i > 0 ? "4 2" : undefined} />
                ))}
                <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={7} />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </div>

        {/* ── Charts grid 3: Voltage + PF ──────────────────────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>

          {/* 5. Voltaje */}
          <Card>
            <SectionLabel icon={Radio} title="Tensión de red" sub="V — detección de caídas o inestabilidad" />
            <ResponsiveContainer width="100%" height={chart_h}>
              <LineChart data={series} margin={chartMargin}>
                {grid}{xAxis}{yAxis}{tip}
                {activeLines.map((l, i) => (
                  <Line key={l.key} type="monotone" dataKey={`${l.key}_v`} name={`${l.label} (V)`}
                    stroke={B_COLORS[i]} strokeWidth={1.6} dot={false} />
                ))}
                <ReferenceLine y={220} stroke={T.red} strokeDasharray="5 3" label={{ value: "220V mín", fill: T.red, fontSize: 9 }} />
                <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={7} />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          {/* 6. Factor de potencia */}
          <Card>
            <SectionLabel
              icon={Gauge}
              title="Factor de potencia"
              sub="Umbral mínimo 0.90 — valores bajo umbral en rojo"
              right={
                <span style={{ fontSize: 10.5, color: T.amber, display: "flex", alignItems: "center", gap: 5 }}>
                  <AlertTriangle size={11} color={T.amber} strokeWidth={1.8} />
                  Lab. de Redes por debajo del límite
                </span>
              }
            />
            <ResponsiveContainer width="100%" height={chart_h}>
              <LineChart data={series} margin={chartMargin}>
                {grid}{xAxis}
                <YAxis tick={axisStyle} tickLine={false} axisLine={false} domain={[0.8, 1]} width={46} />
                {tip}
                <ReferenceLine y={0.90} stroke={T.amber} strokeDasharray="4 3"
                  label={{ value: "0.90 mín", fill: T.amber, fontSize: 9, position: "insideTopLeft" }} />
                {activeLines.map((l, i) => (
                  <Line key={l.key} type="monotone" dataKey={`${l.key}_pf`} name={l.label}
                    stroke={B_COLORS[i]} strokeWidth={1.6} dot={false} />
                ))}
                <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={7} />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </div>

        {/* ── Charts grid 4: Frequency + Tariff dist ───────────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>

          {/* 7. Frecuencia */}
          <Card>
            <SectionLabel icon={Activity} title="Frecuencia de red" sub="Hz — valor nominal 60 Hz" />
            <ResponsiveContainer width="100%" height={chart_h}>
              <LineChart data={series} margin={chartMargin}>
                {grid}{xAxis}
                <YAxis tick={axisStyle} tickLine={false} axisLine={false} domain={[59.85, 60.15]} width={46} />
                {tip}
                <ReferenceLine y={60} stroke={T.muted} strokeDasharray="3 3" />
                {activeLines.map((l, i) => (
                  <Line key={l.key} type="monotone" dataKey={`${l.key}_hz`} name={`${l.label} (Hz)`}
                    stroke={B_COLORS[i]} strokeWidth={1.4} dot={false} />
                ))}
                <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={7} />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          {/* 8. Distribución por periodo tarifario */}
          <Card>
            <SectionLabel icon={BarChart2} title="Distribución por periodo tarifario"
              sub="kWh consumidos y costo estimado por periodo — rango seleccionado" />
            <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
              <ResponsiveContainer width={160} height={chart_h}>
                <PieChart>
                  <Pie data={tariffDist} dataKey="value" nameKey="name"
                    cx="50%" cy="50%" innerRadius={44} outerRadius={68} paddingAngle={3}>
                    {tariffDist.map((d, i) => <Cell key={i} fill={d.color} opacity={0.8} />)}
                  </Pie>
                  <Tooltip formatter={(v, n) => [`${v} kWh`, n]} contentStyle={{ background: "#0d0c1e", border: `1px solid ${T.border}`, borderRadius: 7, fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1 }}>
                {tariffDist.map((t, i) => (
                  <div key={i} style={{ marginBottom: 14 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, alignItems: "center" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                        <span style={{ width: 3, height: 28, borderRadius: 2, background: t.color, display: "inline-block", flexShrink: 0 }} />
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: T.txt }}>{t.name}</div>
                          <div style={{ fontSize: 10.5, color: T.muted }}>{t.value} kWh</div>
                        </div>
                      </div>
                      <div style={{ textAlign: "right" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.color }}>${t.cost.toLocaleString()}</div>
                        <div style={{ fontSize: 10, color: T.muted }}>MXN</div>
                      </div>
                    </div>
                    <div style={{ height: 4, background: T.surfHi, borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${Math.round(t.value / 150 * 100)}%`, background: t.color, opacity: 0.65, borderRadius: 2 }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </Card>
        </div>

        {/* ── 9. Heatmap ───────────────────────────────────────────────── */}
        <Card style={{ marginBottom: 14 }}>
          <SectionLabel icon={BarChart2} title="Mapa de calor horario"
            sub="Intensidad de consumo (kWh) por hora y edificio — rango seleccionado" />
          <Heatmap data={filteredHeat.length > 0 ? filteredHeat : heatRows.slice(0, 2)} />
        </Card>

        {/* ── 10. Recent readings table ────────────────────────────────── */}
        <Card style={{ padding: 0, overflow: "hidden", marginBottom: 14 }}>
          <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.borderS}` }}>
            <SectionLabel icon={TableProperties} title="Lecturas recientes"
              sub="Últimas muestras registradas por nodo activo" />
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${T.borderS}`, background: T.surfHi }}>
                  {["Timestamp","Edificio","Nodo","kW","V","A","FP","Hz","kWh","Tarifa","MXN"].map(h => (
                    <th key={h} style={{
                      padding: "9px 14px", textAlign: "left", fontSize: 10, fontWeight: 600,
                      color: T.muted, textTransform: "uppercase", letterSpacing: 0.9, whiteSpace: "nowrap",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {readings.map((r, i) => (
                  <tr key={i}
                    style={{ borderBottom: `1px solid ${T.borderS}`, transition: "background .1s" }}
                    onMouseEnter={e => e.currentTarget.style.background = T.surfHi}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                  >
                    <td style={{ padding: "9px 14px", color: T.muted, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{r.ts}</td>
                    <td style={{ padding: "9px 14px", color: T.txt, fontWeight: 500, whiteSpace: "nowrap" }}>{r.building}</td>
                    <td style={{ padding: "9px 14px" }}>
                      <span style={{ fontSize: 10.5, background: "rgba(139,92,246,.1)", color: T.accentL, border: `1px solid rgba(139,92,246,.2)`, borderRadius: 4, padding: "2px 7px" }}>{r.node}</span>
                    </td>
                    <td style={{ padding: "9px 14px", color: T.accentL, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{r.kw}</td>
                    <td style={{ padding: "9px 14px", color: T.sec, fontVariantNumeric: "tabular-nums" }}>{r.v}</td>
                    <td style={{ padding: "9px 14px", color: T.sec, fontVariantNumeric: "tabular-nums" }}>{r.a}</td>
                    <td style={{ padding: "9px 14px" }}><PfBadge v={r.pf} /></td>
                    <td style={{ padding: "9px 14px", color: T.sec, fontVariantNumeric: "tabular-nums" }}>{r.hz}</td>
                    <td style={{ padding: "9px 14px", color: T.sec, fontVariantNumeric: "tabular-nums" }}>{r.kwh}</td>
                    <td style={{ padding: "9px 14px" }}><TariffPill t={r.tariff} /></td>
                    <td style={{ padding: "9px 14px", color: T.green, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>${r.cost}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {/* ── Summary strip ────────────────────────────────────────────── */}
        <div style={{
          background: T.surf, border: `1px solid ${T.border}`, borderRadius: 10,
          display: "flex", flexWrap: "wrap", overflow: "hidden",
        }}>
          <SumItem icon={TrendingUp}  label="Total energía"     value={summary.totalKwh.toLocaleString()} unit="kWh"   color={T.accentL} />
          <SumItem icon={DollarSign}  label="Costo total"       value={`$${summary.totalCost.toLocaleString()}`} unit="MXN" color={T.green} />
          <SumItem icon={Gauge}       label="FP promedio"       value={summary.avgPf}     unit=""      color={summary.avgPf >= 0.9 ? T.green : T.red} />
          <SumItem icon={Zap}         label="Corriente máx."    value={summary.maxCurrent} unit="A"    color={T.amber} />
          <SumItem icon={Activity}    label="Voltaje mín."      value={summary.minVoltage} unit="V"    color={T.blue} />
          <div style={{ flex: 1, minWidth: 130, padding: "16px 20px", display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <Database size={12} color={T.muted} strokeWidth={1.8} />
              <span style={{ fontSize: 10, fontWeight: 600, color: T.muted, textTransform: "uppercase", letterSpacing: 0.9 }}>Lecturas</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
              <span style={{ fontSize: 22, fontWeight: 700, color: T.sec, letterSpacing: -0.5, fontVariantNumeric: "tabular-nums" }}>{summary.readings.toLocaleString()}</span>
              <span style={{ fontSize: 11, color: T.muted }}>muestras</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
