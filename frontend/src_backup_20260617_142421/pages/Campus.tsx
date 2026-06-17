import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { buildings } from "../data/mockData";

export function Campus() {
  return (
    <div className="page">
      <div className="campus-summary">
        {["Campus Colima", "Campus Coquimatlán", "Campus Tecomán"].map((campus, index) => (
          <Card className="campus-card" key={campus}>
            <div>
              <h2>{campus}</h2>
              <p>{index === 0 ? "2 active monitoring deployments" : "No active monitoring yet"}</p>
            </div>
            <Badge tone={index === 0 ? "green" : "gray"}>{index === 0 ? "ACTIVE" : "PENDING"}</Badge>
          </Card>
        ))}
      </div>

      <Card className="map-panel">
        <div className="section-header">
          <div>
            <h2>Smart campus network</h2>
            <p>Building status visualization for the portable monitoring campaign</p>
          </div>
        </div>

        <div className="building-node-grid">
          {buildings.map((building) => (
            <article className={`building-node building-${building.status}`} key={building.id}>
              <div className="building-node-top">
                <span className={`status-dot ${building.status === "normal" ? "status-online" : building.status === "warning" ? "status-warning" : "status-offline"}`} />
                <Badge tone={building.node ? "purple" : "gray"}>{building.node ?? "UNASSIGNED"}</Badge>
              </div>
              <h3>{building.name}</h3>
              <p>{building.faculty}</p>
              {building.node ? (
                <strong>${building.costWeek.toLocaleString("es-MX")} MXN/week</strong>
              ) : (
                <span className="subtle">No monitoring data</span>
              )}
            </article>
          ))}
        </div>
      </Card>
    </div>
  );
}
