// @ts-nocheck
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { MetricCard } from "../components/ui/MetricCard";
import { buildings, hourlyData, recommendations, weeklyTrend } from "../data/mockData";

const tariffColors: Record<string, string> = {
  Base: "#818cf8",
  Intermediate: "#f59e0b",
  Peak: "#ef4444",
};

export function Dashboard() {
  const monitored = buildings.filter((building) => building.node);
  const totalCost = monitored.reduce((sum, building) => sum + building.costWeek, 0);

  return (
    <div className="page">
      <div className="metrics-grid">
        <MetricCard label="Estimated cost today" value="$1,373 MXN" detail="FIME + Network Lab" trend="+8% vs previous period" emphasis />
        <MetricCard label="Cost this week" value={`$${totalCost.toLocaleString("es-MX")} MXN`} detail="Accumulated campaign cost" trend="+12% vs previous week" />
        <MetricCard label="Monthly projection" value="$38,400 MXN" detail="Projected with current pattern" />
        <MetricCard label="Potential savings" value="$5,810 MXN/mo" detail="From current AI recommendations" emphasis />
        <MetricCard label="Most expensive building" value="FIME" detail="$5,312 MXN this week" />
        <MetricCard label="Node availability" value="2 / 2" detail="All edge nodes online" />
      </div>

      <div className="dashboard-grid">
        <Card className="panel-large">
          <div className="section-header">
            <div>
              <h2>Cost by hour</h2>
              <p>Estimated MXN cost using time-of-use tariff periods</p>
            </div>
            <Badge tone="purple">GDMTH</Badge>
          </div>

          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={hourlyData}>
              <CartesianGrid stroke="#1f1b37" strokeDasharray="3 3" />
              <XAxis dataKey="hour" stroke="#625b81" />
              <YAxis stroke="#625b81" />
              <Tooltip contentStyle={{ background: "#12111f", border: "1px solid #2a2445", borderRadius: 12 }} />
              <Bar dataKey="cost" name="Cost MXN" radius={[6, 6, 0, 0]}>
                {hourlyData.map((item) => (
                  <Cell key={item.hour} fill={tariffColors[item.tariff]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card className="panel-side">
          <div className="section-header">
            <div>
              <h2>Cost distribution</h2>
              <p>Peak period drives most of the bill</p>
            </div>
          </div>

          <div className="tariff-list">
            {[
              { name: "Base", cost: 1228, pct: 14 },
              { name: "Intermediate", cost: 3362, pct: 38 },
              { name: "Peak", cost: 4288, pct: 48 },
            ].map((item) => (
              <div className="tariff-row" key={item.name}>
                <div>
                  <span style={{ background: tariffColors[item.name] }} />
                  {item.name}
                </div>
                <strong>${item.cost.toLocaleString("es-MX")}</strong>
                <div className="progress">
                  <i style={{ width: `${item.pct}%`, background: tariffColors[item.name] }} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="dashboard-grid">
        <Card>
          <div className="section-header">
            <div>
              <h2>Weekly trend</h2>
              <p>Cost and consumption behavior</p>
            </div>
          </div>

          <ResponsiveContainer width="100%" height={230}>
            <AreaChart data={weeklyTrend}>
              <defs>
                <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#a78bfa" stopOpacity={0.42} />
                  <stop offset="95%" stopColor="#a78bfa" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1f1b37" strokeDasharray="3 3" />
              <XAxis dataKey="day" stroke="#625b81" />
              <YAxis stroke="#625b81" />
              <Tooltip contentStyle={{ background: "#12111f", border: "1px solid #2a2445", borderRadius: 12 }} />
              <Area type="monotone" dataKey="cost" stroke="#a78bfa" strokeWidth={2} fill="url(#costGradient)" />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card glow>
          <div className="section-header">
            <div>
              <h2>AI Insights Center</h2>
              <p>Financial and operational recommendations</p>
            </div>
          </div>

          <div className="insight-list">
            {recommendations.map((item) => (
              <article className="insight-card" key={item.id}>
                <div className="insight-top">
                  <Badge tone={item.priority === "high" ? "red" : "yellow"}>{item.priority.toUpperCase()}</Badge>
                  <strong>${item.impact.toLocaleString("es-MX")} MXN/mo</strong>
                </div>
                <h3>{item.category}</h3>
                <p>{item.description}</p>
                <footer>
                  <span>{item.building}</span>
                  <span>{item.action}</span>
                </footer>
              </article>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
