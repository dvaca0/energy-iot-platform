// @ts-nocheck
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { nodes } from "../data/mockData";

export function Deployments() {
  return (
    <div className="page deployments-layout">
      <div>
        <div className="section-header standalone">
          <div>
            <h2>Available edge nodes</h2>
            <p>Technician workflow for assigning portable nodes</p>
          </div>
        </div>

        {nodes.map((node) => (
          <Card className="node-card" key={node.id}>
            <div className="node-card-header">
              <div>
                <h3>{node.name}</h3>
                <p>{node.ip} · Shelly + Raspberry Pi</p>
              </div>
              <Badge tone="green">ONLINE</Badge>
            </div>

            <div className="node-grid">
              <div><span>Building</span><strong>{node.building}</strong></div>
              <div><span>Last sync</span><strong>{node.lastSync}</strong></div>
              <div><span>Samples</span><strong>{node.samples.toLocaleString("es-MX")}</strong></div>
              <div><span>Buffer</span><strong>{node.buffer} pending</strong></div>
            </div>
          </Card>
        ))}
      </div>

      <Card className="assignment-card" glow>
        <div className="section-header">
          <div>
            <h2>Assign node to building</h2>
            <p>Create a new one-week monitoring deployment</p>
          </div>
        </div>

        <form className="deployment-form">
          <label>Online node<select><option>N001</option><option>N002</option></select></label>
          <label>Campus<select><option>Colima</option><option>Coquimatlán</option><option>Tecomán</option></select></label>
          <label>Faculty<input placeholder="Example: FIME" /></label>
          <label>Building name<input placeholder="Example: Data Center" /></label>
          <label>Electrical panel<input placeholder="Example: Main Panel A" /></label>
          <label>Start date<input type="date" /></label>
          <label>End date<input type="date" /></label>
          <label className="full">Technician notes<textarea placeholder="Installation notes..." /></label>
          <button type="button">Save deployment</button>
        </form>
      </Card>
    </div>
  );
}
