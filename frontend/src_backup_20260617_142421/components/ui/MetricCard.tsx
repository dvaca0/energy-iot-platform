import { Card } from "./Card";

interface MetricCardProps {
  label: string;
  value: string;
  detail?: string;
  trend?: string;
  emphasis?: boolean;
}

export function MetricCard({ label, value, detail, trend, emphasis = false }: MetricCardProps) {
  return (
    <Card className="metric-card" glow={emphasis}>
      <div className="metric-label">{label}</div>
      <div className={emphasis ? "metric-value metric-value-emphasis" : "metric-value"}>{value}</div>
      {detail && <div className="metric-detail">{detail}</div>}
      {trend && <div className="metric-trend">{trend}</div>}
    </Card>
  );
}
