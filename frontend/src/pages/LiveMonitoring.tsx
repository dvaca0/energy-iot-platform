// @ts-nocheck
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { nodes } from "../data/mockData";

export function LiveMonitoring() {
  return (
    <div className="page">
      <div className="live-banner">
        <span className="status-dot status-online" />
        Live telemetry · refresh every 15 seconds from edge nodes
      </div>

      {nodes.map((node) => (
        <Card className="live-node" key={node.id} glow>
          <div className="section-header">
            <div>
              <h2>{node.name}</h2>
              <p>{node.building} · {node.ip} · Last sync {node.lastSync}</p>
            </div>
            <Badge tone="green">ONLINE</Badge>
          </div>

          <div className="live-metrics">
            <div><span>Voltage</span><strong>{node.voltage} V</strong></div>
            <div><span>Current</span><strong>{node.current} A</strong></div>
            <div><span>Power</span><strong>{node.power} kW</strong></div>
            <div><span>Power factor</span><strong>{node.pf}</strong></div>
            <div><span>Frequency</span><strong>{node.freq} Hz</strong></div>
            <div><span>Energy today</span><strong>{node.energyToday} kWh</strong></div>
          </div>
        </Card>
      ))}
    </div>
  );
}
