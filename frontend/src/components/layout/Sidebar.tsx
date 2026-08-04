import {
  Activity,
  BarChart3,
  BrainCircuit,
  Building2,
  Cpu,
  Database,
  FileText,
  LayoutDashboard,
  Map,
  Server,
  Settings,
  WalletCards,
} from "lucide-react";

const nav = [
  { id: "dashboard", label: "Executive Dashboard", icon: LayoutDashboard },
  { id: "campus", label: "Campus Map", icon: Map },
  { id: "buildings", label: "Buildings", icon: Building2 },
  { id: "deployments", label: "Deployments", icon: Cpu },
  { id: "live", label: "Live Monitoring", icon: Activity },
  { id: "cost", label: "Cost Analytics", icon: WalletCards },
  { id: "ai", label: "AI Center", icon: BrainCircuit },
  { id: "mining", label: "Data Mining", icon: Database },
  { id: "reports", label: "Reports", icon: FileText },
  { id: "infra", label: "Infrastructure", icon: Server },
  { id: "settings", label: "Settings", icon: Settings },
];

interface SidebarProps {
  page: string;
  setPage: (page: string) => void;
  role: string;
  setRole: (role: string) => void;
}

export function Sidebar({ page, setPage, role, setRole }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <BarChart3 size={20} />
        </div>
        <div>
          <div className="brand-title">UEIP</div>
          <div className="brand-subtitle">Energy Intelligence</div>
        </div>
      </div>

      <nav className="nav">
        {nav.map((item) => {
          const Icon = item.icon;
          const active = page === item.id;

          return (
            <button key={item.id} className={active ? "nav-item nav-item-active" : "nav-item"} onClick={() => setPage(item.id)}>
              <Icon size={17} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="role-box">
        <label>Current role</label>
        <select value={role} onChange={(event) => setRole(event.target.value)}>
          <option>Administrator</option>
          <option>Executive</option>
          <option>Technician</option>
          <option>Researcher</option>
        </select>
      </div>
    </aside>
  );
}
