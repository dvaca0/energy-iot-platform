export type Status = "online" | "warning" | "offline" | "normal";

export interface NodeDevice {
  id: string;
  name: string;
  status: "online" | "offline";
  ip: string;
  building: string;
  campus: string;
  voltage: number;
  current: number;
  power: number;
  energyToday: number;
  pf: number;
  freq: number;
  lastSync: string;
  buffer: number;
  samples: number;
}

export interface Building {
  id: string;
  name: string;
  faculty: string;
  campus: string;
  node: string | null;
  status: "normal" | "warning" | "offline";
  power: number;
  energyWeek: number;
  costWeek: number;
  costToday: number;
  anomaly: boolean;
  lastUpdate: string;
}

export interface Recommendation {
  id: string;
  priority: "high" | "medium" | "low";
  category: string;
  building: string;
  impact: number;
  title: string;
  description: string;
  action: string;
}
