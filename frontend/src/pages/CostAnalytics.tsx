// @ts-nocheck
import { MetricCard } from "../components/ui/MetricCard";
import { Card } from "../components/ui/Card";

export function CostAnalytics() {
  return (
    <div className="page">
      <div className="metrics-grid">
        <MetricCard label="Cost today" value="$1,373 MXN" detail="Estimated GDMTH" emphasis />
        <MetricCard label="Cost this week" value="$8,878 MXN" detail="Current campaign" />
        <MetricCard label="Monthly projection" value="$38,400 MXN" detail="Projected from measured pattern" />
        <MetricCard label="Peak cost share" value="48%" detail="Only 23% of active hours" emphasis />
      </div>

      <Card className="cost-panel">
        <div className="section-header">
          <div>
            <h2>Tariff breakdown</h2>
            <p>Time-of-use cost analysis for CFE GDMTH tariff</p>
          </div>
        </div>

        <div className="tariff-breakdown">
          <div><span>Base</span><strong>$1,228 MXN</strong><p>38.4 kWh · 14% of cost</p></div>
          <div><span>Intermediate</span><strong>$3,362 MXN</strong><p>82.1 kWh · 38% of cost</p></div>
          <div><span>Peak</span><strong>$4,288 MXN</strong><p>29.5 kWh · 48% of cost</p></div>
        </div>

        <div className="savings-box">
          <h3>Savings simulator</h3>
          <p>Moving 20% of peak consumption into base period could save approximately <strong>$858 MXN/week</strong>.</p>
        </div>
      </Card>
    </div>
  );
}
