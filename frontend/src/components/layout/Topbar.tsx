import { Bell, Search } from "lucide-react";

const titles: Record<string, string> = {
  dashboard: "Executive Dashboard",
  campus: "Campus Map",
  buildings: "Buildings",
  deployments: "Deployments",
  live: "Live Monitoring",
  cost: "Cost Analytics",
  ai: "AI Center",
  mining: "Data Mining",
  reports: "Reports",
  infra: "Infrastructure",
  settings: "Settings",
};

interface TopbarProps {
  page: string;
}

export function Topbar({ page }: TopbarProps) {
  return (
    <header className="topbar">
      <div>
        <h1>{titles[page] ?? "Dashboard"}</h1>
        <p>Universidad de Colima · GDMTH · Building monitoring campaign</p>
      </div>

      <div className="topbar-actions">
        <div className="search-box">
          <Search size={15} />
          <span>Search buildings, nodes, reports...</span>
        </div>

        <div className="system-pill">
          <span className="status-dot status-online" />
          2 nodes online
        </div>

        <button className="icon-button" aria-label="Notifications">
          <Bell size={17} />
        </button>

        <div className="avatar">DV</div>
      </div>
    </header>
  );
}
