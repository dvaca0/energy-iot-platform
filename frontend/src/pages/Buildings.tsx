// @ts-nocheck
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { buildings } from "../data/mockData";

export function Buildings() {
  return (
    <div className="page">
      <Card className="table-card">
        <div className="section-header">
          <div>
            <h2>Building inventory</h2>
            <p>Monitored and pending university buildings</p>
          </div>
          <Badge tone="purple">{buildings.length} buildings</Badge>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Building</th>
                <th>Faculty</th>
                <th>Campus</th>
                <th>Node</th>
                <th>Status</th>
                <th>Power</th>
                <th>Weekly cost</th>
              </tr>
            </thead>
            <tbody>
              {buildings.map((building) => (
                <tr key={building.id}>
                  <td><strong>{building.name}</strong></td>
                  <td>{building.faculty}</td>
                  <td>{building.campus}</td>
                  <td>{building.node ? <Badge>{building.node}</Badge> : "—"}</td>
                  <td>
                    <span className={`status-dot ${building.status === "normal" ? "status-online" : building.status === "warning" ? "status-warning" : "status-offline"}`} />
                    {building.status}
                  </td>
                  <td>{building.power ? `${building.power} kW` : "—"}</td>
                  <td>{building.costWeek ? `$${building.costWeek.toLocaleString("es-MX")} MXN` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
