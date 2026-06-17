// @ts-nocheck
import { Card } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";

interface SimplePageProps {
  title: string;
  subtitle: string;
  type: "mining" | "reports" | "infra" | "settings";
}

export function SimplePage({ title, subtitle, type }: SimplePageProps) {
  const content = {
    mining: ["Building behavior clustering", "Consumption signatures", "Correlation analysis", "Seasonal patterns"],
    reports: ["Weekly cost report", "Deployment report", "AI anomaly report", "Executive PDF export"],
    infra: ["API status", "PostgreSQL status", "SQLite edge buffers", "Tailscale connectivity"],
    settings: ["Users and roles", "CFE tariff configuration", "Campus management", "Alert thresholds"],
  }[type];

  return (
    <div className="page">
      <Card className="simple-page-card" glow>
        <div className="section-header">
          <div>
            <h2>{title}</h2>
            <p>{subtitle}</p>
          </div>
          <Badge>PLANNED MODULE</Badge>
        </div>

        <div className="module-grid">
          {content.map((item) => (
            <div className="soft-card module-item" key={item}>
              <strong>{item}</strong>
              <p>Backend-ready placeholder for the next implementation phase.</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
