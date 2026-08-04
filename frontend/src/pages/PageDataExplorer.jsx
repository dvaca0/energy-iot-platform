import React, { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import {
  Activity,
  BarChart3,
  Database,
  RefreshCw,
  Zap,
  DollarSign,
  Gauge,
  Waves,
  AlertTriangle,
  Table2,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// Origin comes from the shared API client, so it follows whatever host
// served the page. The previous hardcoded loopback origin only ever
// resolved on the server itself, leaving this page broken in browsers.

// Categorical series palette — blue-led and deliberately narrow, so several
// buildings can be told apart without the page turning into a colour chart.
const COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#64748b", "#06b6d4"];
const CARD = "#171a1d";
const SURFACE_INNER = "#121417";
const BORDER = "#252a31";
const BORDER_SOFT = "#1e2227";
const TEXT = "#f5f7fa";
const SECONDARY = "#9aa4af";
const MUTED = "#7c8793";
const ACCENT = "#2563eb";

const rangeLabels = {
  "1h": "Última hora",
  "24h": "Últimas 24 horas",
  "7d": "Últimos 7 días",
  "30d": "Últimos 30 días",
  all: "Todo el despliegue",
};

const Card = ({ children, style }) => (
  <div
    style={{
      background: CARD,
      border: `1px solid ${BORDER}`,
      borderRadius: 12,
      padding: 18,
      boxShadow: "0 1px 2px rgba(0,0,0,.24)",
      ...style,
    }}
  >
    {children}
  </div>
);

const Title = ({ icon: Icon, title, sub, right }) => (
  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 14 }}>
    <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
      {Icon && <Icon size={14} color={MUTED} strokeWidth={1.6} style={{ marginTop: 1 }} />}
      <div>
        <h3 style={{ margin: 0, color: TEXT, fontSize: 14, fontWeight: 600, letterSpacing: -0.1 }}>{title}</h3>
        <div style={{ color: MUTED, fontSize: 11.5, marginTop: 3 }}>{sub}</div>
      </div>
    </div>
    {right}
  </div>
);

const avg = (values) => {
  const valid = values.filter((v) => Number.isFinite(Number(v)));
  if (!valid.length) return 0;
  return valid.reduce((a, b) => a + Number(b), 0) / valid.length;
};

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 6, padding: "8px 11px", boxShadow: "0 4px 16px rgba(0,0,0,.4)" }}>
      <div style={{ color: MUTED, fontSize: 11, marginBottom: 6 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.color, fontSize: 12, marginBottom: 3, fontVariantNumeric: "tabular-nums" }}>
          {p.name}: {Number(p.value || 0).toLocaleString("es-MX", { maximumFractionDigits: 4 })}
        </div>
      ))}
    </div>
  );
};

const MultiBuildingSelect = ({ buildings, selected, setSelected }) => {
  const toggle = (id) => {
    setSelected((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id]
    );
  };

  return (
    <div style={{ position: "relative" }}>
      <select
        value=""
        onChange={(e) => {
          const value = Number(e.target.value);
          if (value) toggle(value);
        }}
        style={{
          background: SURFACE_INNER,
          border: `1px solid ${BORDER}`,
          color: TEXT,
          borderRadius: 6,
          padding: "9px 11px",
          minWidth: 220,
          outline: "none",
        }}
      >
        <option value="">{selected.length || buildings.length} edificio(s)</option>
        {buildings.map((b) => (
          <option key={b.id} value={b.id}>
            {selected.includes(b.id) ? "✓ " : ""}{b.name}
          </option>
        ))}
      </select>
    </div>
  );
};

const DataLineChart = ({ data, buildings, metric, suffix = "", threshold }) => (
  <ResponsiveContainer width="100%" height={230}>
    <LineChart data={data}>
      <CartesianGrid stroke={BORDER_SOFT} strokeDasharray="3 3" vertical={false} />
      <XAxis dataKey="time" stroke={MUTED} fontSize={11} />
      <YAxis stroke={MUTED} fontSize={11} />
      <Tooltip content={<CustomTooltip />} />
      <Legend />
      {threshold !== undefined && (
        <Line
          type="monotone"
          dataKey={() => threshold}
          name={`Umbral ${threshold}${suffix}`}
          stroke="#f59e0b"
          strokeWidth={1.25}
          strokeDasharray="4 4"
          dot={false}
        />
      )}
      {buildings.map((b, i) => (
        <Line
          key={b.id}
          type="monotone"
          dataKey={`${b.name}_${metric}`}
          name={`${b.name}${suffix ? ` (${suffix})` : ""}`}
          stroke={COLORS[i % COLORS.length]}
          strokeWidth={1.5}
          dot={false}
          activeDot={{ r: 3, strokeWidth: 0 }}
          connectNulls
        />
      ))}
    </LineChart>
  </ResponsiveContainer>
);

const PageDataExplorer = () => {
  const [range, setRange] = useState("24h");
  const [options, setOptions] = useState({ buildings: [], ranges: [] });
  const [selectedBuildings, setSelectedBuildings] = useState([]);
  const [compare, setCompare] = useState(true);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const activeBuildings = useMemo(() => {
    const source = data?.buildings?.length ? data.buildings : options.buildings;
    if (!selectedBuildings.length) return source;
    return source.filter((b) => selectedBuildings.includes(b.id));
  }, [data, options, selectedBuildings]);

  const loadOptions = async () => {
    const response = await api.get("/data-explorer/options");
    setOptions(response.data);
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const ids = selectedBuildings.join(",");
      const url = `/data-explorer?range=${encodeURIComponent(range)}${ids ? `&building_ids=${encodeURIComponent(ids)}` : ""}`;
      const response = await api.get(url);
      setData(response.data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOptions();
  }, []);

  useEffect(() => {
    loadData();
  }, [range, selectedBuildings.join(",")]);

  const series = data?.series || [];
  const tariff = data?.tariffDistribution || [];
  const heatmap = data?.heatmap || [];
  const readings = data?.recentReadings || [];
  const summary = data?.summary || {};

  const selectedChartBuildings = compare ? activeBuildings : activeBuildings.slice(0, 1);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 }}>
        <div>
          <h1 style={{ color: TEXT, margin: 0, fontSize: 17, fontWeight: 600, letterSpacing: -0.2 }}>Explorador de Datos</h1>
          <div style={{ color: MUTED, marginTop: 4, fontSize: 12 }}>
            Análisis visual de lecturas reales por edificio, nodo y periodo
          </div>
        </div>

        <div style={{
          color: "#22c55e",
          border: "1px solid #22c55e33",
          background: "#22c55e14",
          borderRadius: 4,
          padding: "4px 10px",
          fontSize: 11,
          fontWeight: 500,
        }}>
          Datos reales
        </div>
      </div>

      <Card style={{ marginBottom: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <Database size={15} color={MUTED} strokeWidth={1.6} />

          <select
            value={range}
            onChange={(e) => setRange(e.target.value)}
            style={{
              background: SURFACE_INNER,
              border: `1px solid ${BORDER}`,
              color: TEXT,
              borderRadius: 6,
              padding: "9px 11px",
              minWidth: 190,
              outline: "none",
            }}
          >
            {Object.entries(rangeLabels).map(([id, label]) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>

          <MultiBuildingSelect
            buildings={options.buildings}
            selected={selectedBuildings}
            setSelected={setSelectedBuildings}
          />

          <label style={{ display: "flex", alignItems: "center", gap: 8, color: SECONDARY, fontSize: 12.5 }}>
            <input
              type="checkbox"
              checked={compare}
              onChange={(e) => setCompare(e.target.checked)}
              style={{ accentColor: ACCENT, width: 14, height: 14 }}
            />
            Comparar edificios
          </label>

          <button
            onClick={loadData}
            style={{
              background: ACCENT,
              border: `1px solid ${ACCENT}`,
              color: "#fff",
              borderRadius: 6,
              padding: "9px 14px",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              display: "flex",
              gap: 8,
              alignItems: "center",
            }}
          >
            <RefreshCw size={14} />
            {loading ? "Actualizando..." : "Actualizar vista"}
          </button>

          <div style={{ marginLeft: "auto", color: MUTED, fontSize: 12 }}>
            Rango activo: <b style={{ color: SECONDARY }}>{rangeLabels[range]}</b>
          </div>
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Card>
          <Title icon={Zap} title="Potencia activa" sub="kW · lecturas reales agregadas" />
          <DataLineChart data={series} buildings={selectedChartBuildings} metric="power_kw" suffix="kW" />
        </Card>

        <Card>
          <Title icon={Activity} title="Energía acumulada" sub="kWh · suma progresiva por edificio" />
          <ResponsiveContainer width="100%" height={230}>
            <AreaChart data={series}>
              <CartesianGrid stroke={BORDER_SOFT} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="time" stroke={MUTED} fontSize={11} />
              <YAxis stroke={MUTED} fontSize={11} />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              {selectedChartBuildings.map((b, i) => (
                <Area
                  key={b.id}
                  type="monotone"
                  dataKey={`${b.name}_energy_kwh`}
                  name={b.name}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={1.5}
                  fill={COLORS[i % COLORS.length]}
                  fillOpacity={0.1}
                  connectNulls
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <Title icon={DollarSign} title="Costo estimado" sub="MXN · costo calculado con tarifa GDMTH" />
          <DataLineChart data={series} buildings={selectedChartBuildings} metric="cost_mxn" suffix="MXN" />
        </Card>

        <Card>
          <Title icon={Activity} title="Corriente por nodo" sub="A · corriente total promedio por periodo" />
          <DataLineChart data={series} buildings={selectedChartBuildings} metric="current_a" suffix="A" />
        </Card>

        <Card>
          <Title icon={Waves} title="Tensión de red" sub="V · monitoreo de voltaje" />
          <DataLineChart data={series} buildings={selectedChartBuildings} metric="voltage" suffix="V" />
        </Card>

        <Card>
          <Title
            icon={Gauge}
            title="Factor de potencia"
            sub="Umbral mínimo 0.90"
            right={<div style={{ color: "#f59e0b", fontSize: 11.5, fontWeight: 500, display: "flex", alignItems: "center", gap: 5 }}><AlertTriangle size={12} strokeWidth={1.8} /> Bajo 0.90 revisar</div>}
          />
          <DataLineChart data={series} buildings={selectedChartBuildings} metric="power_factor" threshold={0.9} />
        </Card>

        <Card>
          <Title icon={Activity} title="Frecuencia de red" sub="Hz · valor nominal 60 Hz" />
          <DataLineChart data={series} buildings={selectedChartBuildings} metric="frequency_hz" suffix="Hz" />
        </Card>

        <Card>
          <Title icon={BarChart3} title="Distribución por periodo tarifario" sub="kWh y costo por Base / Intermedia / Punta" />
          <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16, alignItems: "center" }}>
            <ResponsiveContainer width="100%" height={210}>
              <PieChart>
                <Pie data={tariff} dataKey="cost_mxn" nameKey="period" innerRadius={55} outerRadius={85}>
                  {tariff.map((entry, index) => (
                    <Cell key={entry.period} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>

            <div>
              {tariff.map((item, i) => (
                <div key={item.period} style={{ marginBottom: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", color: TEXT, fontSize: 13 }}>
                    <b>{item.period}</b>
                    <b style={{ color: COLORS[i % COLORS.length] }}>${Number(item.cost_mxn || 0).toLocaleString("es-MX")} MXN</b>
                  </div>
                  <div style={{ color: MUTED, fontSize: 11 }}>{Number(item.kwh || 0).toLocaleString("es-MX")} kWh · {item.share_pct}%</div>
                  <div style={{ height: 4, background: SURFACE_INNER, border: `1px solid ${BORDER_SOFT}`, borderRadius: 99, marginTop: 6 }}>
                    <div style={{ height: "100%", width: `${item.share_pct || 0}%`, background: COLORS[i % COLORS.length], borderRadius: 99 }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      <Card style={{ marginTop: 14 }}>
        <Title icon={BarChart3} title="Mapa de calor horario" sub="kWh por hora y edificio" />
        <div style={{ overflowX: "auto" }}>
          <div style={{ minWidth: 850 }}>
            <div style={{ display: "grid", gridTemplateColumns: "140px repeat(24, 1fr)", gap: 3, color: MUTED, fontSize: 10, marginBottom: 6 }}>
              <div />
              {Array.from({ length: 24 }).map((_, i) => <div key={i}>{String(i).padStart(2, "0")}</div>)}
            </div>
            {heatmap.map((row) => {
              const max = Math.max(...row.hours.map((h) => h.kwh), 1);
              return (
                <div key={row.building} style={{ display: "grid", gridTemplateColumns: "140px repeat(24, 1fr)", gap: 3, marginBottom: 5, alignItems: "center" }}>
                  <div style={{ color: TEXT, fontSize: 12, fontWeight: 500 }}>{row.building}</div>
                  {row.hours.map((h) => {
                    const intensity = h.kwh / max;
                    const color = intensity > 0.66 ? "#ef4444" : intensity > 0.33 ? "#f59e0b" : intensity > 0 ? ACCENT : SURFACE_INNER;
                    return (
                      <div
                        key={h.hour}
                        title={`${row.building} ${h.hour}:00 · ${h.kwh} kWh`}
                        style={{ height: 20, background: color, opacity: 0.4 + intensity * 0.6, borderRadius: 3 }}
                      />
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </Card>

      <Card style={{ marginTop: 14 }}>
        <Title icon={Table2} title="Lecturas recientes" sub="Últimas muestras filtradas por edificio y rango" />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ color: MUTED, textAlign: "left", borderBottom: `1px solid ${BORDER}`, textTransform: "uppercase", fontSize: 10.5, letterSpacing: 0.7 }}>
                {["Timestamp", "Edificio", "Nodo", "kW", "V", "A", "FP", "Hz", "kWh", "Tarifa", "MXN"].map((h) => (
                  <th key={h} style={{ padding: "0 8px 9px", fontWeight: 500 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {readings.map((r, i) => (
                <tr key={`${r.timestamp}-${i}`} style={{ borderBottom: `1px solid ${BORDER_SOFT}`, color: SECONDARY }}>
                  <td style={{ padding: "8px" }}>{new Date(r.timestamp).toLocaleString("es-MX")}</td>
                  <td style={{ padding: "8px", color: TEXT, fontWeight: 500 }}>{r.building}</td>
                  <td style={{ padding: "8px" }}>{r.node}</td>
                  <td style={{ padding: "8px" }}>{r.power_kw}</td>
                  <td style={{ padding: "8px" }}>{r.voltage}</td>
                  <td style={{ padding: "8px" }}>{r.current}</td>
                  <td style={{ padding: "8px", color: r.power_factor < 0.9 ? "#ef4444" : "#22c55e", fontWeight: 500 }}>{r.power_factor}</td>
                  <td style={{ padding: "8px" }}>{r.frequency_hz}</td>
                  <td style={{ padding: "8px" }}>{r.energy_kwh}</td>
                  <td style={{ padding: "8px" }}>{r.tariff_period}</td>
                  <td style={{ padding: "8px", color: TEXT, fontWeight: 500 }}>${r.cost_mxn}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 10, marginTop: 14 }}>
        {[
          ["Total energía", `${Number(summary.total_kwh || 0).toLocaleString("es-MX")} kWh`, TEXT],
          ["Costo total", `$${Number(summary.total_cost_mxn || 0).toLocaleString("es-MX")} MXN`, TEXT],
          ["FP promedio", Number(summary.avg_power_factor || 0).toFixed(2), TEXT],
          ["Corriente máx.", `${Number(summary.max_current_a || 0).toLocaleString("es-MX")} A`, TEXT],
          ["Voltaje mín.", `${Number(summary.min_voltage || 0).toLocaleString("es-MX")} V`, TEXT],
          ["Lecturas", Number(summary.reading_count || 0).toLocaleString("es-MX"), TEXT],
        ].map(([label, value, color]) => (
          <Card key={label} style={{ padding: 14 }}>
            <div style={{ color: MUTED, textTransform: "uppercase", letterSpacing: 0.9, fontSize: 10, fontWeight: 600 }}>{label}</div>
            <div style={{ color, fontSize: 18, fontWeight: 600, marginTop: 7, letterSpacing: -0.3, fontVariantNumeric: "tabular-nums" }}>{value}</div>
          </Card>
        ))}
      </div>
    </div>
  );
};

export default PageDataExplorer;
