import type { Building, NodeDevice, Recommendation } from "../types";

export const nodes: NodeDevice[] = [
  {
    id: "N001",
    name: "Edge Node 001",
    status: "online",
    ip: "100.64.1.10",
    building: "FIME",
    campus: "Colima",
    voltage: 228.4,
    current: 18.7,
    power: 4.21,
    energyToday: 31.2,
    pf: 0.93,
    freq: 60.02,
    lastSync: "2 min ago",
    buffer: 0,
    samples: 8640,
  },
  {
    id: "N002",
    name: "Edge Node 002",
    status: "online",
    ip: "100.64.1.11",
    building: "Laboratorio de Redes",
    campus: "Colima",
    voltage: 225.1,
    current: 12.3,
    power: 2.77,
    energyToday: 19.8,
    pf: 0.89,
    freq: 59.97,
    lastSync: "5 min ago",
    buffer: 3,
    samples: 6210,
  },
];

export const buildings: Building[] = [
  { id: "B01", name: "FIME", faculty: "Ingeniería Mecánica y Eléctrica", campus: "Colima", node: "N001", status: "normal", power: 4.21, energyWeek: 221.4, costWeek: 5312, costToday: 862, anomaly: false, lastUpdate: "2 min" },
  { id: "B02", name: "Laboratorio de Redes", faculty: "Ingeniería en Sistemas", campus: "Colima", node: "N002", status: "warning", power: 2.77, energyWeek: 148.6, costWeek: 3566, costToday: 511, anomaly: true, lastUpdate: "5 min" },
  { id: "B03", name: "Rectoría", faculty: "Administración", campus: "Colima", node: null, status: "offline", power: 0, energyWeek: 0, costWeek: 0, costToday: 0, anomaly: false, lastUpdate: "—" },
  { id: "B04", name: "Biblioteca Central", faculty: "Servicios Universitarios", campus: "Colima", node: null, status: "offline", power: 0, energyWeek: 0, costWeek: 0, costToday: 0, anomaly: false, lastUpdate: "—" },
  { id: "B05", name: "Facultad de Ingeniería", faculty: "Ingeniería", campus: "Coquimatlán", node: null, status: "offline", power: 0, energyWeek: 0, costWeek: 0, costToday: 0, anomaly: false, lastUpdate: "—" },
  { id: "B06", name: "Data Center", faculty: "TI", campus: "Colima", node: null, status: "offline", power: 0, energyWeek: 0, costWeek: 0, costToday: 0, anomaly: false, lastUpdate: "—" },
];

export const hourlyData = [
  { hour: "00:00", kwh: 2.1, cost: 42, tariff: "Base" },
  { hour: "03:00", kwh: 1.5, cost: 30, tariff: "Base" },
  { hour: "06:00", kwh: 2.8, cost: 67, tariff: "Intermediate" },
  { hour: "09:00", kwh: 6.9, cost: 248, tariff: "Peak" },
  { hour: "12:00", kwh: 8.1, cost: 291, tariff: "Peak" },
  { hour: "15:00", kwh: 5.9, cost: 142, tariff: "Intermediate" },
  { hour: "18:00", kwh: 5.8, cost: 139, tariff: "Intermediate" },
  { hour: "21:00", kwh: 3.2, cost: 77, tariff: "Intermediate" },
];

export const weeklyTrend = [
  { day: "Mon", cost: 3210, kwh: 142 },
  { day: "Tue", cost: 3480, kwh: 155 },
  { day: "Wed", cost: 3290, kwh: 146 },
  { day: "Thu", cost: 3650, kwh: 162 },
  { day: "Fri", cost: 3820, kwh: 169 },
  { day: "Sat", cost: 2100, kwh: 93 },
  { day: "Sun", cost: 1420, kwh: 63 },
];

export const recommendations: Recommendation[] = [
  {
    id: "R01",
    priority: "high",
    category: "Peak Cost Optimization",
    building: "FIME",
    impact: 3250,
    title: "Move non-critical loads outside peak periods",
    description: "Peak tariff hours represent 21% of energy usage but 39% of estimated cost.",
    action: "Review equipment operating between 09:00–13:00 and 16:00–18:00.",
  },
  {
    id: "R02",
    priority: "high",
    category: "Power Factor",
    building: "Laboratorio de Redes",
    impact: 1840,
    title: "Investigate low power factor",
    description: "Average power factor is below the recommended threshold.",
    action: "Request an electrical diagnostic for compensation options.",
  },
  {
    id: "R03",
    priority: "medium",
    category: "Night Baseload",
    building: "Laboratorio de Redes",
    impact: 720,
    title: "Reduce abnormal nighttime consumption",
    description: "The system detected consumption above expected values between 02:00 and 05:00.",
    action: "Audit devices that remain powered overnight.",
  },
];
