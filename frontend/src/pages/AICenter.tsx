// @ts-nocheck
import { Card } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { recommendations } from "../data/mockData";

export function AICenter() {
  return (
    <div className="page ai-grid">
      <Card glow>
        <div className="section-header">
          <div>
            <h2>Forecasting</h2>
            <p>Cost and consumption prediction</p>
          </div>
          <Badge>MODEL READY</Badge>
        </div>
        <div className="forecast-summary">
          <div><span>Tomorrow cost</span><strong>$1,520 MXN</strong></div>
          <div><span>Weekly forecast</span><strong>$9,420 MXN</strong></div>
          <div><span>Monthly projection</span><strong>$38,400 MXN</strong></div>
        </div>
      </Card>

      <Card>
        <div className="section-header">
          <div>
            <h2>Anomaly detection</h2>
            <p>Detected operational issues</p>
          </div>
        </div>
        <div className="anomaly-list">
          <article><Badge tone="red">HIGH</Badge><strong>Peak demand spike</strong><p>Network Lab exceeded expected demand at 09:05.</p></article>
          <article><Badge tone="yellow">MEDIUM</Badge><strong>Night baseload</strong><p>Unexpected consumption remained active after 02:00.</p></article>
          <article><Badge tone="yellow">MEDIUM</Badge><strong>Low power factor</strong><p>FIME dropped below recommended PF threshold.</p></article>
        </div>
      </Card>

      <Card className="ai-chat">
        <div className="section-header">
          <div>
            <h2>Energy AI Assistant</h2>
            <p>Natural language analysis placeholder</p>
          </div>
        </div>
        <div className="chat-message">Ask: “Which building cost the most this week?”</div>
        <div className="chat-answer">FIME is currently the most expensive building with an estimated weekly cost of $5,312 MXN.</div>
      </Card>

      <Card>
        <div className="section-header">
          <div>
            <h2>Recommendations</h2>
            <p>Ranked by estimated financial impact</p>
          </div>
        </div>
        <div className="insight-list">
          {recommendations.map((item) => (
            <article className="insight-card" key={item.id}>
              <div className="insight-top">
                <Badge tone={item.priority === "high" ? "red" : "yellow"}>{item.priority.toUpperCase()}</Badge>
                <strong>${item.impact.toLocaleString("es-MX")} MXN/mo</strong>
              </div>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
            </article>
          ))}
        </div>
      </Card>
    </div>
  );
}
