// @ts-nocheck
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ucolLogo from "./assets/ucol-logo.png";
import { getDashboardSummary, getHourlyCost, getBuildings, getNodes, getAiInsights, createDeployment, getDelegations, getAllOrgBuildings, getCampusesByDelegation, getUnitsByCampus, getBuildingsByUnit, getPanelsByBuilding, getLatestReadings, getLiveMetrics, getMetricsHourly, getMetricsTariffs, getMetricsDaily, getMetricsBuildings, getAnomalies, getCampusMetrics, getDeployments, getCostSummary, getSystemSettings, getInfrastructureStatus, getMiningAnalytics, getAiCenter, askAiAssistant } from "./services/api";

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ComposedChart
} from "recharts";

// ─── MOCK DATA ────────────────────────────────────────────────────────────────
const MOCK = {
  nodes: [
    { id:'N001', name:'Node 001', status:'online', ip:'100.64.1.10', building:'FIME', campus:'Colima',
      voltage:228.4, current:18.7, power:4.21, energy_today:31.2, pf:0.93, freq:60.02,
      last_sync:'hace 2 min', buffer:0, samples:8640, rpi_status:'ok', shelly_status:'ok', fw:'1.4.2' },
    { id:'N002', name:'Node 002', status:'online', ip:'100.64.1.11', building:'Laboratorio de Redes', campus:'Colima',
      voltage:225.1, current:12.3, power:2.77, energy_today:19.8, pf:0.89, freq:59.97,
      last_sync:'hace 5 min', buffer:3, samples:6210, rpi_status:'ok', shelly_status:'ok', fw:'1.4.2' }
  ],
  buildings: [
    { id:'B01', name:'FIME', faculty:'Ing. Mecánica y Eléctrica', campus:'Colima', node:'N001',
      status:'normal', power:4.21, energy_week:221.4, cost_week:5312, cost_today:862, anomaly:false, last_update:'2 min' },
    { id:'B02', name:'Laboratorio de Redes', faculty:'Ing. en Sistemas', campus:'Colima', node:'N002',
      status:'warning', power:2.77, energy_week:148.6, cost_week:3566, cost_today:511, anomaly:true, last_update:'5 min' },
    { id:'B03', name:'Rectoría', faculty:'Administración', campus:'Colima', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B04', name:'Biblioteca Central', faculty:'Servicios Escolares', campus:'Colima', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B05', name:'Facultad de Ingeniería', faculty:'Ingeniería', campus:'Coquimatlán', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B06', name:'Data Center', faculty:'TI', campus:'Colima', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B07', name:'Laboratorio de Química', faculty:'Ciencias', campus:'Tecomán', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B08', name:'Centro de Cómputo', faculty:'Ing. en Sistemas', campus:'Colima', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' }
  ],
  hourly: [
    {h:'00:00',kwh:2.1,cost:42,tariff:'base'},{h:'01:00',kwh:1.8,cost:36,tariff:'base'},
    {h:'02:00',kwh:1.6,cost:32,tariff:'base'},{h:'03:00',kwh:1.5,cost:30,tariff:'base'},
    {h:'04:00',kwh:1.7,cost:34,tariff:'base'},{h:'05:00',kwh:1.9,cost:38,tariff:'base'},
    {h:'06:00',kwh:2.8,cost:67,tariff:'intermedia'},{h:'07:00',kwh:4.1,cost:98,tariff:'intermedia'},
    {h:'08:00',kwh:5.8,cost:139,tariff:'intermedia'},{h:'09:00',kwh:6.9,cost:248,tariff:'punta'},
    {h:'10:00',kwh:7.4,cost:266,tariff:'punta'},{h:'11:00',kwh:7.8,cost:280,tariff:'punta'},
    {h:'12:00',kwh:8.1,cost:291,tariff:'punta'},{h:'13:00',kwh:7.6,cost:273,tariff:'punta'},
    {h:'14:00',kwh:6.2,cost:149,tariff:'intermedia'},{h:'15:00',kwh:5.9,cost:142,tariff:'intermedia'},
    {h:'16:00',kwh:6.4,cost:230,tariff:'punta'},{h:'17:00',kwh:7.1,cost:255,tariff:'punta'},
    {h:'18:00',kwh:5.8,cost:139,tariff:'intermedia'},{h:'19:00',kwh:4.6,cost:110,tariff:'intermedia'},
    {h:'20:00',kwh:3.9,cost:94,tariff:'intermedia'},{h:'21:00',kwh:3.2,cost:77,tariff:'intermedia'},
    {h:'22:00',kwh:2.8,cost:56,tariff:'base'},{h:'23:00',kwh:2.3,cost:46,tariff:'base'}
  ],
  weeklyTrend: [
    {day:'Lun',cost:3210,kwh:142},{day:'Mar',cost:3480,kwh:155},{day:'Mié',cost:3290,kwh:146},
    {day:'Jue',cost:3650,kwh:162},{day:'Vie',cost:3820,kwh:169},{day:'Sáb',cost:2100,kwh:93},
    {day:'Dom',cost:1420,kwh:63}
  ],
  forecast: [
    {day:'Sem 1',actual:20900,pred:20900,lower:19500,upper:22300},
    {day:'Sem 2',actual:21400,pred:21200,lower:19800,upper:22600},
    {day:'Sem 3',actual:null,pred:22100,lower:20500,upper:23700},
    {day:'Sem 4',actual:null,pred:22800,lower:21000,upper:24600}
  ],
  anomalies: [
    { id:'A01', time:'03:47', building:'Lab. de Redes', type:'Consumo nocturno anómalo', severity:'warning', value:'2.4 kW', expected:'0.8 kW' },
    { id:'A02', time:'11:23', building:'FIME', type:'Factor de potencia bajo', severity:'info', value:'0.71 FP', expected:'>0.90 FP' },
    { id:'A03', time:'09:05', building:'Lab. de Redes', type:'Pico de demanda', severity:'critical', value:'6.8 kW', expected:'4.5 kW' }
  ],
  recommendations: [
    { id:'R01', building:'FIME', priority:'alta', savings:3250, title:'Reducir consumo en hora punta', desc:'Mover cargas no críticas fuera del periodo 09:00–13:00 y 16:00–18:00 puede reducir el costo estimado mensual.', action:'Revisar equipos encendidos en punta' },
    { id:'R02', building:'Lab. de Redes', priority:'alta', savings:1840, title:'Corregir factor de potencia', desc:'FP promedio de 0.89 genera penalización tarifaria. Se recomienda instalar banco de capacitores.', action:'Solicitar diagnóstico eléctrico' },
    { id:'R03', building:'Lab. de Redes', priority:'media', savings:720, title:'Reducir baseload nocturno', desc:'Se detectó consumo anómalo entre 02:00–05:00. Revisar equipos que permanecen encendidos.', action:'Auditoría nocturna de equipos' }
  ],
  deployments: [
    { id:'D01', node:'N001', building:'FIME', campus:'Colima', panel:'Tablero Principal', tech:'Ing. Ramírez',
      start:'2025-01-06', end:'2025-01-13', progress:71, samples:8640, completeness:98, status:'active', notes:'Instalación sin incidentes.' },
    { id:'D02', node:'N002', building:'Lab. de Redes', campus:'Colima', panel:'Tablero Red A', tech:'Ing. López',
      start:'2025-01-06', end:'2025-01-13', progress:71, samples:6210, completeness:72, status:'active', notes:'Buffer acumulado por corte de internet 3h.' },
    { id:'D03', node:'N001', building:'Rectoría', campus:'Colima', panel:'Tablero General', tech:'Ing. Ramírez',
      start:'2024-12-16', end:'2024-12-23', progress:100, samples:10080, completeness:100, status:'completed', notes:'Despliegue exitoso.' },
    { id:'D04', node:'N002', building:'Biblioteca', campus:'Colima', panel:'Tablero Piso 1', tech:'Ing. López',
      start:'2024-12-16', end:'2024-12-23', progress:100, samples:9870, completeness:98, status:'completed', notes:'Datos completos.' }
  ],
  campuses: [
    { name:'Campus Colima', buildings:6, monitored:2, power:6.98, kwh_week:370, cost_week:8878, status:'active' },
    { name:'Campus Coquimatlán', buildings:1, monitored:0, power:0, kwh_week:0, cost_week:0, status:'inactive' },
    { name:'Campus Tecomán', buildings:1, monitored:0, power:0, kwh_week:0, cost_week:0, status:'inactive' }
  ],
  chatHistory: [
    { role:'assistant', msg:'Hola. Soy el Asistente de Energía IA. Puedes preguntarme sobre costos, consumo, anomalías o comparaciones entre edificios.' }
  ],
  chatResponses: {
    'costo':     'Esta semana, **FIME** es el edificio más costoso con **$5,312 MXN** estimados. Le sigue Lab. de Redes con $3,566 MXN. El costo semanal total estimado del campus es de **$8,878 MXN**.',
    'semana':    'El costo estimado de esta semana hasta hoy es de **$8,878 MXN**. El jueves y viernes son los días de mayor consumo. Se proyecta un mes completo de aproximadamente **$38,400 MXN** si el patrón se mantiene.',
    'anomal':    'Se detectaron **3 anomalías** hoy: un consumo nocturno anómalo en Lab. de Redes a las 03:47 (2.4 kW vs 0.8 kW esperado), un factor de potencia bajo en FIME (0.71) y un pico de demanda en Lab. de Redes a las 09:05.',
    'punta':     'El periodo de punta (09:00–13:00 y 16:00–18:00) representa solo el **23% del tiempo** pero genera el **39% del costo estimado**. Desplazar cargas a periodo base podría ahorrar hasta **$3,250 MXN/mes**.',
    'ahorro':    'Recomendaciones actuales: (1) Reducir punta: $3,250 MXN/mes. (2) Corregir FP en Lab. de Redes: $1,840 MXN/mes. (3) Eliminar baseload nocturno: $720 MXN/mes. **Ahorro potencial total: $5,810 MXN/mes**.',
    'default':   'Puedo ayudarte con información sobre costos, anomalías, periodos tarifarios, proyecciones y comparaciones entre edificios. ¿Qué deseas saber?'
  }
};

// ─── HELPERS ─────────────────────────────────────────────────────────────────
const fmt = {
  mxn: (v) => `$${v.toLocaleString('es-MX')} MXN`,
  kwh: (v) => `${v.toFixed(1)} kWh`,
  kw:  (v) => `${v.toFixed(2)} kW`,
  pct: (v) => `${v.toFixed(1)}%`
};

const STATUS_COLORS = { normal:'#22c55e', warning:'#f59e0b', critical:'#ef4444', offline:'#4b5563', online:'#22c55e' };
const TARIFF_COLORS = { base:'#818cf8', intermedia:'#f59e0b', punta:'#ef4444' };
const PURPLE = '#7c5cbf';
const PURPLE_L = '#a78bfa';
const CHART_GRID = '#1e1b35';
const TOOLTIP_STYLE = { background:'#12101f', border:'1px solid #2a2740', borderRadius:'10px', color:'#e2e0f0', fontSize:12 };


const ICONS = {
  Bolt: <><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/></>,
  Wallet: <><path d="M3 7h18v12H3z"/><path d="M16 11h5v4h-5z"/><path d="M3 7l3-4h12l3 4"/></>,
  Calendar: <><path d="M4 5h16v16H4z"/><path d="M8 3v4M16 3v4M4 10h16"/></>,
  TrendingUp: <><path d="M3 17l6-6 4 4 7-8"/><path d="M14 7h6v6"/></>,
  ArrowDown: <><path d="M12 4v14"/><path d="M6 12l6 6 6-6"/></>,
  Building: <><path d="M4 21V5l8-3 8 3v16"/><path d="M9 21v-6h6v6M8 8h.01M12 8h.01M16 8h.01M8 12h.01M12 12h.01M16 12h.01"/></>,
  Activity: <><path d="M3 12h4l3-8 4 16 3-8h4"/></>,
  Dashboard: <><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></>,
  Map: <><path d="M9 18l-6 3V6l6-3 6 3 6-3v15l-6 3-6-3z"/><path d="M9 3v15M15 6v15"/></>,
  Cpu: <><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/></>,
  Dollar: <><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7H14a3.5 3.5 0 0 1 0 7H6"/></>,
  Brain: <><path d="M9 3a3 3 0 0 0-3 3v1a4 4 0 0 0-2 7 4 4 0 0 0 4 6h1V3z"/><path d="M15 3a3 3 0 0 1 3 3v1a4 4 0 0 1 2 7 4 4 0 0 1-4 6h-1V3z"/><path d="M9 8H6M15 8h3M9 14H5M15 14h4"/></>,
  Database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></>,
  FileText: <><path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6M9 13h6M9 17h6"/></>,
  Server: <><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/></>,
  Settings: <><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2 3-.2-.1a1.7 1.7 0 0 0-2 .1 1.7 1.7 0 0 0-.8 1.7V22h-3.6v-.3a1.7 1.7 0 0 0-.8-1.7 1.7 1.7 0 0 0-2-.1l-.2.1-2-3 .1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H4v-3.6h.3a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1 2-3 .2.1a1.7 1.7 0 0 0 2-.1 1.7 1.7 0 0 0 .8-1.7V2h3.6v.3a1.7 1.7 0 0 0 .8 1.7 1.7 1.7 0 0 0 2 .1l.2-.1 2 3-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.3V14h-.3a1.7 1.7 0 0 0-1.5 1z"/></>,
  Alert: <><path d="M12 3l10 18H2L12 3z"/><path d="M12 9v5M12 18h.01"/></>,
  Bot: <><rect x="5" y="8" width="14" height="10" rx="3"/><path d="M12 8V4M8 13h.01M16 13h.01M9 18v2M15 18v2"/></>,
  User: <><path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/></>,
  Leaf: <><path d="M5 21c8 0 14-6 14-14V3h-4C7 3 3 7 3 15c0 3 2 6 2 6z"/><path d="M5 21c2-6 7-10 14-14"/></>,
  Plug: <><path d="M9 7V2M15 7V2M7 7h10v4a5 5 0 0 1-10 0V7z"/><path d="M12 16v6"/></>,
  Lock: <><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></>,
  Sync: <><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 16v5h5M3 12A9 9 0 0 1 18.5 5.8L21 8"/><path d="M21 8V3h-5"/></>,
  Monitor: <><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></>,
  Clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  Check: <><path d="M20 6L9 17l-5-5"/></>,
  X: <><path d="M18 6L6 18M6 6l12 12"/></>,
  ArrowRight: <><path d="M5 12h14M13 6l6 6-6 6"/></>,
  BarChart: <><path d="M4 19V5M4 19h17M8 16v-5M13 16V8M18 16v-9"/></>
};
const Icon = ({ name='Activity', size=16, color='currentColor', stroke=1.8, style }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={{display:'block',...style}}>
    {ICONS[name] || ICONS.Activity}
  </svg>
);
const iconForNav = (name) => ({ LayoutDashboard:'Dashboard', MapPin:'Map', Building2:'Building', Cpu:'Cpu', Activity:'Activity', DollarSign:'Dollar', BrainCircuit:'Brain', Database:'Database', FileText:'FileText', Server:'Server', Settings:'Settings' }[name] || 'Activity');
const PRIORITY_META = {
  high:{label:'Alta prioridad',color:'#ef4444'},
  medium:{label:'Prioridad media',color:'#f59e0b'},
  low:{label:'Observación',color:'#818cf8'},
  info:{label:'Información',color:PURPLE_L}
};

// Professional inline SVG icons — no CDN dependency

// ─── COMMON COMPONENTS ────────────────────────────────────────────────────────
const Card = ({ children, style, glow, className }) => (
  <div style={{
    background:'#10101e', border:`1px solid #1e1b35`, borderRadius:14,
    padding:'18px 20px', position:'relative', overflow:'hidden',
    ...(glow ? {boxShadow:`0 0 24px 0 ${PURPLE}22`} : {}),
    ...style
  }} className={className}>{children}</div>
);

const Badge = ({ children, color='#7c5cbf', bg }) => (
  <span style={{
    background: bg || `${color}22`, color, border:`1px solid ${color}44`,
    borderRadius:20, padding:'2px 10px', fontSize:11, fontWeight:600, letterSpacing:.5
  }}>{children}</span>
);

const StatusDot = ({ status }) => (
  <span style={{
    display:'inline-block', width:8, height:8, borderRadius:'50%',
    background: STATUS_COLORS[status] || '#6b7280',
    boxShadow: `0 0 6px ${STATUS_COLORS[status] || '#6b7280'}`,
    marginRight:6
  }}/>
);

const StatCard = ({ label, value, sub, icon, color='#7c5cbf', trend }) => (
  <Card style={{flex:1,minWidth:140,padding:'18px 20px',borderTop:`1px solid ${color}55`}}>
    <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:8}}>
      {icon && <Icon name={icon} size={14} color={color}/>} 
      <div style={{fontSize:10,color:'#7b739e',textTransform:'uppercase',letterSpacing:1.2,fontWeight:700}}>{label}</div>
    </div>
    <div style={{fontSize:27,fontWeight:760,color:'#f6f4ff',letterSpacing:-0.8,lineHeight:1.05}}>{value}</div>
    {sub && <div style={{fontSize:12,color:'#7b739e',marginTop:8}}>{sub}</div>}
    {trend && <div style={{display:'inline-flex',alignItems:'center',gap:4,fontSize:11,color:trend>0?'#ef4444':'#22c55e',marginTop:8,fontWeight:700}}>
      <Icon name={trend>0?'TrendingUp':'ArrowDown'} size={12}/>{trend>0?'+':'-'}{Math.abs(trend)}% vs sem. anterior
    </div>}
  </Card>
);

const SectionTitle = ({ children, sub }) => (
  <div style={{marginBottom:18}}>
    <h2 style={{fontSize:17,fontWeight:700,color:'#f0eeff'}}>{children}</h2>
    {sub && <p style={{fontSize:12,color:'#6e6694',marginTop:3}}>{sub}</p>}
  </div>
);

const AIInsightCard = ({ insights }) => {
  const normalized = insights.map((ins, i) => {
    if (typeof ins === 'string') {
      return {
        priority: i === 0 ? 'medium' : 'info',
        category: 'Sistema',
        building: 'Sin edificio',
        impact: 'Sin clasificación',
        title: 'Mensaje del sistema',
        desc: ins
      };
    }

    return {
      priority: ins.priority || ins.severity || 'info',
      category: ins.category || 'Anomalía',
      building: ins.building || ins.node_id || 'Sin edificio',
      impact: ins.value !== undefined && ins.threshold !== undefined
        ? `Valor: ${Number(ins.value).toFixed(2)} · Umbral: ${Number(ins.threshold).toFixed(2)}`
        : 'Evento detectado',
      title: ins.title || 'Anomalía detectada',
      desc: ins.description || ins.desc || 'Sin descripción'
    };
  });
  return (
    <Card glow style={{borderColor:`${PURPLE}44`}}>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:10,marginBottom:16}}>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <div style={{background:'#7c5cbf18',border:'1px solid #7c5cbf33',borderRadius:10,padding:8,color:PURPLE_L}}><Icon name="Brain" size={18}/></div>
          <div>
            <div style={{fontSize:13,fontWeight:800,color:'#f0eeff',letterSpacing:.2}}>Centro de Insights</div>
            <div style={{fontSize:11,color:'#7b739e'}}>Análisis automático y recomendaciones accionables</div>
          </div>
        </div>
        <Badge color={PURPLE_L}>Anomaly Engine</Badge>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(260px,1fr))',gap:12}}>
        {normalized.map((ins,i) => {
          const meta = PRIORITY_META[ins.priority] || PRIORITY_META.info;
          return (
            <div key={i} style={{background:'#0d0d19',border:`1px solid ${meta.color}33`,borderRadius:12,padding:'14px 15px'}}>
              <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:8,marginBottom:10}}>
                <Badge color={meta.color}>{meta.label}</Badge>
                <span style={{fontSize:10,color:'#7b739e',textTransform:'uppercase',letterSpacing:.8}}>{ins.category}</span>
              </div>
              <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:8}}>
                <Icon name="Building" size={14} color={PURPLE_L}/>
                <span style={{fontSize:12,color:'#c4bdf0',fontWeight:700}}>{ins.building}</span>
              </div>
              <div style={{fontSize:12,color:'#22c55e',fontWeight:700,marginBottom:8}}>{ins.title}</div>
              <p style={{fontSize:12,color:'#a9a2d0',lineHeight:1.55,marginBottom:8}}>{ins.desc}</p>
              <div style={{fontSize:11,color:'#7b739e'}}>{ins.impact}</div>
            </div>
          );
        })}
      </div>
    </Card>
  );
};

const CustomTooltip = ({ active, payload, label, prefix='', suffix='' }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={TOOLTIP_STYLE}>
      <div style={{padding:'8px 12px'}}>
        <div style={{fontSize:11,color:'#6e6694',marginBottom:6}}>{label}</div>
        {payload.map((p,i) => (
          <div key={i} style={{fontSize:13,color:p.color||'#e2e0f0',fontWeight:600}}>
            {p.name}: {prefix}{typeof p.value === 'number' ? p.value.toLocaleString('es-MX') : p.value}{suffix}
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── SIDEBAR ─────────────────────────────────────────────────────────────────
const NAV_ITEMS = [
  { id:'dashboard', label:'Dashboard Ejecutivo', icon:'LayoutDashboard' },
  { id:'campus', label:'Mapa de Campus', icon:'MapPin' },
  { id:'buildings', label:'Edificios', icon:'Building2' },
  { id:'deployments', label:'Despliegues', icon:'Cpu' },
  { id:'live', label:'Monitoreo en Vivo', icon:'Activity' },
  { id:'cost', label:'Análisis de Costo', icon:'DollarSign' },
  { id:'ai', label:'Centro IA / Forecasting', icon:'BrainCircuit' },
  { id:'mining', label:'Minería de Datos', icon:'Database' },
  { id:'reports', label:'Reportes', icon:'FileText' },
  { id:'infra', label:'Infraestructura', icon:'Server' },
  { id:'settings', label:'Configuración', icon:'Settings' }
];

const ROLES = ['Administrador','Ejecutivo','Técnico','Investigador'];

const Sidebar = ({ page, setPage, role, setRole }) => {
  const [roleOpen, setRoleOpen] = useState(false);
  return (
    <div style={{
      width:230, minHeight:'100vh', background:'#08080f',
      borderRight:'1px solid #1a1730', display:'flex', flexDirection:'column',
      position:'fixed', top:0, left:0, zIndex:100
    }}>
      <div style={{padding:'20px 16px 16px', borderBottom:'1px solid #1a1730'}}>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <div style={{background:'linear-gradient(135deg,#7c5cbf,#4f3d9e)',borderRadius:10,width:36,height:36,display:'flex',alignItems:'center',justifyContent:'center',color:'#fff'}}><Icon name="Bolt" size={18}/></div>
          <div>
            <div style={{fontSize:12,fontWeight:800,color:'#f0eeff',letterSpacing:.3}}>ENERGY</div>
            <div style={{fontSize:10,color:'#6e6694',letterSpacing:.5}}>INTELLIGENCE PLATFORM</div>
          </div>
        </div>
      </div>
      <nav style={{flex:1,padding:'12px 8px',overflowY:'auto'}}>
        {NAV_ITEMS.map(item => (
          <button key={item.id} onClick={() => setPage(item.id)}
            style={{
              width:'100%', display:'flex', alignItems:'center', gap:10,
              padding:'9px 12px', borderRadius:9, border:'none', marginBottom:2,
              background: page===item.id ? '#7c5cbf22' : 'transparent',
              color: page===item.id ? PURPLE_L : '#7a7499',
              fontWeight: page===item.id ? 700 : 400,
              fontSize:13, cursor:'pointer', transition:'all .15s',
              borderLeft: page===item.id ? `3px solid ${PURPLE_L}` : '3px solid transparent'
            }}>
            <Icon name={iconForNav(item.icon)} size={15} color={page===item.id ? PURPLE_L : '#7a7499'}/>
            {item.label}
          </button>
        ))}
      </nav>
      <div style={{padding:'12px 8px', borderTop:'1px solid #1a1730'}}>
        <div style={{position:'relative'}}>
          <button onClick={() => setRoleOpen(!roleOpen)} style={{
            width:'100%', display:'flex', alignItems:'center', justifyContent:'space-between',
            padding:'8px 12px', borderRadius:9, border:'1px solid #2a2740',
            background:'#10101e', color:'#c4bdf0', fontSize:12, cursor:'pointer'
          }}>
            <div style={{display:'flex',alignItems:'center',gap:8}}>
              <div style={{width:24,height:24,borderRadius:'50%',background:'#7c5cbf44',display:'flex',alignItems:'center',justifyContent:'center',fontSize:11,color:PURPLE_L,fontWeight:700}}>
                {role[0]}
              </div>
              {role}
            </div>
            <span style={{fontSize:10,color:'#6e6694'}}>▾</span>
          </button>
          {roleOpen && (
            <div style={{position:'absolute',bottom:'100%',left:0,right:0,background:'#12101f',border:'1px solid #2a2740',borderRadius:9,overflow:'hidden',marginBottom:4}}>
              {ROLES.map(r => (
                <button key={r} onClick={() => { setRole(r); setRoleOpen(false); }} style={{
                  width:'100%', padding:'9px 14px', textAlign:'left', border:'none',
                  background: r===role ? '#7c5cbf22' : 'transparent',
                  color: r===role ? PURPLE_L : '#9890c4', fontSize:13, cursor:'pointer'
                }}>{r}</button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ─── TOPBAR ───────────────────────────────────────────────────────────────────
const Topbar = ({page, activeNodesText}) => {
  const titles = { dashboard:'Dashboard Ejecutivo', campus:'Mapa de Campus', buildings:'Edificios',
    deployments:'Despliegues', live:'Monitoreo en Vivo', cost:'Análisis de Costo',
    ai:'Centro IA & Forecasting', mining:'Minería de Datos', reports:'Reportes',
    infra:'Infraestructura', settings:'Configuración' };
  const [time, setTime] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setTime(new Date()), 30000); return () => clearInterval(t); }, []);
  return (
    <div style={{
      background:'#08080f', borderBottom:'1px solid #1a1730',
      padding:'0 24px', height:56, display:'flex', alignItems:'center',
      justifyContent:'space-between', position:'sticky', top:0, zIndex:90
    }}>
      <div>
        <h1 style={{fontSize:16,fontWeight:700,color:'#f0eeff'}}>{titles[page] || page}</h1>
        <p style={{fontSize:11,color:'#6e6694'}}>Universidad de Colima · GDMTH · Semana del 6–13 Ene 2025</p>
      </div>
      <div style={{display:'flex',alignItems:'center',gap:16}}>
        <div style={{fontSize:12,color:'#6e6694'}}>
          {time.toLocaleTimeString('es-MX', {hour:'2-digit',minute:'2-digit'})}
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6,background:'#22c55e18',border:'1px solid #22c55e33',borderRadius:20,padding:'4px 12px'}}>
          <StatusDot status="online"/>
          <span style={{fontSize:11,color:'#22c55e',fontWeight:600}}>{activeNodesText}</span>
        </div>
        <div style={{width:32,height:32,borderRadius:'50%',background:'linear-gradient(135deg,#7c5cbf,#4f3d9e)',display:'flex',alignItems:'center',justifyContent:'center',fontSize:13,fontWeight:700,color:'#fff'}}>U</div>
      </div>
    </div>
  );
};

// ─── PAGE: EXECUTIVE DASHBOARD ────────────────────────────────────────────────
const PageDashboard = ({ apiAnomalies }) => {
  const [dashboardSummary, setDashboardSummary] = useState(null);
  const [hourlyCost, setHourlyCost] = useState(null);
  const [tariffMetrics, setTariffMetrics] = useState(null);
  const [dailyMetrics, setDailyMetrics] = useState(null);
  const [buildingMetrics, setBuildingMetrics] = useState(null);

  useEffect(() => {
    getDashboardSummary()
      .then(setDashboardSummary)
      .catch((error) => console.error("Dashboard summary API error:", error));

    getMetricsHourly()
      .then((data) => {
        const normalized = data.map((item) => ({
          h: item.hour,
          kwh: item.kwh,
          cost: item.cost_mxn,
          tariff: item.tariff_period === "intermediate" ? "intermedia" : item.tariff_period === "peak" ? "punta" : "base",
        }));
        setHourlyCost(normalized);
      })
      .catch((error) => console.error("Hourly metrics API error:", error));

    getMetricsTariffs()
      .then((data) => {
        const normalized = data.map((item) => ({
          name: item.period === "intermediate" ? "Intermedia" : item.period === "peak" ? "Punta" : item.period === "base" ? "Base" : item.period,
          kwh: item.kwh,
          cost: item.cost_mxn,
          pct: item.share_pct,
        }));
        setTariffMetrics(normalized);
      })
      .catch((error) => console.error("Tariff metrics API error:", error));

    getMetricsDaily()
      .then((data) => {
        const normalized = data.map((item) => ({
          day: item.day,
          cost: item.cost_mxn,
          kwh: item.kwh,
        }));
        setDailyMetrics(normalized);
      })
      .catch((error) => console.error("Daily metrics API error:", error));

    getMetricsBuildings()
      .then((data) => {
        const total = data.reduce((sum, item) => sum + Number(item.cost_mxn || 0), 0) || 1;
        const normalized = data.map((item) => ({
          b: item.building_name || "Sin edificio",
          cost: item.cost_mxn,
          kwh: item.kwh,
          pct: Math.round((Number(item.cost_mxn || 0) / total) * 100),
        }));
        setBuildingMetrics(normalized);
      })
      .catch((error) => console.error("Building metrics API error:", error));
  }, []);

  const mxn = (value) => `$${Number(value || 0).toLocaleString("es-MX")} MXN`;
  const hourlyChartData = hourlyCost || MOCK.hourly;

  const tariffData = tariffMetrics || [
    { name:'Base', kwh:0, cost:0, pct:0 },
    { name:'Intermedia', kwh:0, cost:0, pct:0 },
    { name:'Punta', kwh:0, cost:0, pct:0 }
  ];
  const dailyChartData = dailyMetrics || [];
  const buildingChartData = buildingMetrics || [];
  return (
    <div>
      <div style={{display:'flex',flexWrap:'wrap',gap:14,marginBottom:22}}>
        <StatCard label="Costo Estimado Hoy" value={dashboardSummary ? mxn(dashboardSummary.estimated_cost_today_mxn) : "Cargando..."} sub="FIME + Lab. Redes" color="#7c5cbf" trend={8} icon="Wallet"/>
        <StatCard label="Costo Esta Semana" value={dashboardSummary ? mxn(dashboardSummary.estimated_cost_week_mxn) : "Cargando..."} sub="Acumulado lun–hoy" color="#ef4444" trend={12} icon="Calendar"/>
        <StatCard label="Proyección Mensual" value={dashboardSummary ? mxn(dashboardSummary.projected_monthly_cost_mxn) : "Cargando..."} sub="Estimado GDMTH" color="#f59e0b" icon="TrendingUp"/>
        <StatCard label="Ahorro Potencial" value={dashboardSummary ? `${mxn(dashboardSummary.potential_savings_mxn_month)}/mes` : "Cargando..."} sub="Recomendaciones activas" color="#22c55e" icon="ArrowDown"/>
        <StatCard label="Edificio más costoso" value={dashboardSummary?.most_expensive_building?.name || "Cargando..."} sub={dashboardSummary?.most_expensive_building ? `${mxn(dashboardSummary.most_expensive_building.cost_week_mxn)} esta semana` : "Desde backend"} color="#a78bfa" icon="Building"/>
        <StatCard label="Nodos Online" value={dashboardSummary ? `${dashboardSummary.online_nodes} / ${dashboardSummary.total_nodes}` : "Cargando..."} sub="Sistema operativo" color="#22c55e" icon="Activity"/>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'2fr 1fr',gap:18,marginBottom:18}}>
        <Card>
          <SectionTitle sub="Costo estimado por hora · tarifa GDMTH">Costo por Hora (MXN)</SectionTitle>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={hourlyChartData} margin={{top:0,right:0,left:-10,bottom:0}}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID}/>
              <XAxis dataKey="h" tick={{fontSize:10,fill:'#6e6694'}} interval={3}/>
              <YAxis tick={{fontSize:10,fill:'#6e6694'}}/>
              <Tooltip content={<CustomTooltip prefix="$" suffix=" MXN"/>}/>
              <Bar dataKey="cost" name="Costo MXN" radius={[4,4,0,0]}>
                {hourlyChartData.map((d,i) => <Cell key={i} fill={TARIFF_COLORS[d.tariff]} opacity={0.85}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div style={{display:'flex',gap:16,marginTop:10}}>
            {Object.entries(TARIFF_COLORS).map(([k,v]) => (
              <span key={k} style={{fontSize:11,color:'#6e6694',display:'flex',alignItems:'center',gap:5}}>
                <span style={{width:10,height:10,borderRadius:2,background:v,display:'inline-block'}}/>
                {k.charAt(0).toUpperCase()+k.slice(1)}
              </span>
            ))}
          </div>
        </Card>
        <Card>
          <SectionTitle sub="Distribución por periodo tarifario">Costo por Tarifa</SectionTitle>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie data={tariffData} dataKey="cost" nameKey="name" cx="50%" cy="50%" innerRadius={50} outerRadius={75}>
                {tariffData.map((d,i) => <Cell key={i} fill={Object.values(TARIFF_COLORS)[i]}/>)}
              </Pie>
              <Tooltip formatter={(v) => `$${v.toLocaleString()} MXN`}/>
            </PieChart>
          </ResponsiveContainer>
          {tariffData.map((d,i) => (
            <div key={i} style={{display:'flex',justifyContent:'space-between',padding:'5px 0',borderTop:'1px solid #1a1730',fontSize:12}}>
              <span style={{display:'flex',alignItems:'center',gap:6,color:'#9890c4'}}>
                <span style={{width:8,height:8,borderRadius:2,background:Object.values(TARIFF_COLORS)[i],display:'inline-block'}}/>
                {d.name}
              </span>
              <span style={{color:'#f0eeff',fontWeight:600}}>${d.cost.toLocaleString()}</span>
            </div>
          ))}
        </Card>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:18,marginBottom:18}}>
        <Card>
          <SectionTitle sub="Tendencia de gasto · últimos 7 días">Costo Semanal por Día</SectionTitle>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={dailyChartData} margin={{top:5,right:10,left:-10,bottom:0}}>
              <defs>
                <linearGradient id="gc" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={PURPLE} stopOpacity={0.4}/>
                  <stop offset="95%" stopColor={PURPLE} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID}/>
              <XAxis dataKey="day" tick={{fontSize:11,fill:'#6e6694'}}/>
              <YAxis tick={{fontSize:10,fill:'#6e6694'}}/>
              <Tooltip content={<CustomTooltip prefix="$" suffix=" MXN"/>}/>
              <Area type="monotone" dataKey="cost" name="Costo MXN" stroke={PURPLE_L} fill="url(#gc)" strokeWidth={2}/>
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card>
          <SectionTitle sub="Edificios actualmente monitoreados">Costo por Edificio · Semana</SectionTitle>
          <div style={{marginTop:8}}>
            {buildingChartData.length === 0 ? (
              <div style={{background:'#1a1730',borderRadius:10,padding:'12px 14px',fontSize:13,color:'#9890c4'}}>
                Sin datos reales de edificios todavía.
              </div>
            ) : buildingChartData.map((d,i) => (
              <div key={i} style={{marginBottom:16}}>
                <div style={{display:'flex',justifyContent:'space-between',marginBottom:6,fontSize:13}}>
                  <span style={{color:'#c4bdf0'}}>{d.b}</span>
                  <span style={{color:'#f0eeff',fontWeight:700}}>${Number(d.cost || 0).toLocaleString("es-MX")} MXN</span>
                </div>
                <div style={{height:8,background:'#1a1730',borderRadius:4,overflow:'hidden'}}>
                  <div style={{height:'100%',width:`${d.pct}%`,background:`linear-gradient(90deg,${PURPLE},${PURPLE_L})`,borderRadius:4}}/>
                </div>
                <div style={{fontSize:11,color:'#6e6694'}}>{Number(d.kwh || 0).toFixed(4)} kWh</div>
              </div>
            ))}
            <div style={{background:'#1a1730',borderRadius:10,padding:'12px 14px',marginTop:16}}>
              <div style={{fontSize:11,color:'#6e6694',marginBottom:4}}>6 edificios sin monitoreo</div>
              <div style={{fontSize:13,color:'#9890c4'}}>Asignar nodos para ampliar cobertura</div>
            </div>
          </div>
        </Card>
      </div>
      <AIInsightCard insights={
        apiAnomalies?.anomalies?.length
          ? apiAnomalies.anomalies
          : [{
              priority: "info",
              category: "Sistema",
              building: "Sin edificio",
              title: "Sin anomalías detectadas",
              description: "No hay suficientes anomalías reales detectadas todavía. El sistema seguirá analizando las lecturas entrantes."
            }]
      }/>
    </div>
  );
};

// ─── PAGE: CAMPUS MAP ─────────────────────────────────────────────────────────
const PageCampus = () => {
  const [campusData, setCampusData] = useState({ campuses: [], buildings: [] });

  useEffect(() => {
    const load = () => {
      getCampusMetrics()
        .then(setCampusData)
        .catch((error) => console.error("Campus metrics API error:", error));
    };

    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const campuses = campusData.campuses || [];
  const buildings = campusData.buildings || [];

  return (
    <div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(280px,1fr))',gap:18,marginBottom:22}}>
        {campuses.map(campus => (
          <Card key={campus.id} glow={campus.status === "active"}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:18}}>
              <div>
                <div style={{fontSize:15,fontWeight:800,color:'#f0eeff'}}>{campus.name}</div>
                <div style={{fontSize:11,color:'#7b739e'}}>{campus.delegation}</div>
                <div style={{fontSize:11,color:'#7b739e',marginTop:3}}>
                  {campus.monitored_buildings}/{campus.total_buildings} edificios monitoreados
                </div>
              </div>
              <Badge color={campus.status === "active" ? "#22c55e" : "#6b7280"}>
                {campus.status === "active" ? "Activo" : "Sin datos"}
              </Badge>
            </div>

            <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12}}>
              <div>
                <div style={{fontSize:10,color:'#6e6694',textTransform:'uppercase',letterSpacing:.8}}>Potencia</div>
                <div style={{fontSize:19,fontWeight:800,color:'#f0eeff'}}>{Number(campus.power_kw || 0).toFixed(2)} kW</div>
              </div>
              <div>
                <div style={{fontSize:10,color:'#6e6694',textTransform:'uppercase',letterSpacing:.8}}>Energía hoy</div>
                <div style={{fontSize:19,fontWeight:800,color:'#f0eeff'}}>{Number(campus.energy_today_kwh || 0).toFixed(3)} kWh</div>
              </div>
              <div>
                <div style={{fontSize:10,color:'#6e6694',textTransform:'uppercase',letterSpacing:.8}}>Costo hoy</div>
                <div style={{fontSize:19,fontWeight:800,color:PURPLE_L}}>${Number(campus.cost_today_mxn || 0).toLocaleString("es-MX")} MXN</div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card>
        <SectionTitle title="Red de Edificios Inteligentes" subtitle="Datos reales de edificios registrados y lecturas recibidas"/>
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(190px,1fr))',gap:14}}>
          {buildings.map(building => {
            const isActive = building.status === "monitored";
            const color = building.anomaly ? "#f59e0b" : isActive ? "#22c55e" : "#6b7280";

            return (
              <div key={building.id} style={{
                background:'#0f0f1a',
                border:`1px solid ${color}55`,
                borderRadius:12,
                padding:16,
                minHeight:156,
              }}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:14}}>
                  <Icon name="Building" size={20} color={PURPLE_L}/>
                  <StatusDot status={building.anomaly ? "warning" : isActive ? "online" : "offline"}/>
                </div>

                <div style={{fontSize:13,fontWeight:800,color:'#f0eeff',marginBottom:3}}>{building.name}</div>
                <div style={{fontSize:11,color:'#7b739e',marginBottom:10}}>{building.campus}</div>

                {isActive ? (
                  <>
                    <div style={{fontSize:15,fontWeight:800,color:PURPLE_L}}>{Number(building.power_kw || 0).toFixed(2)} kW</div>
                    <div style={{fontSize:11,color:'#7b739e'}}>${Number(building.cost_today_mxn || 0).toLocaleString("es-MX")} MXN hoy</div>
                    <div style={{fontSize:11,color:'#7b739e'}}>{Number(building.energy_today_kwh || 0).toFixed(4)} kWh</div>
                    {building.anomaly && (
                      <div style={{display:'inline-block',marginTop:8,padding:'3px 8px',background:'#ef444422',borderRadius:999,color:'#ef4444',fontSize:10,fontWeight:700}}>
                        Anomalía
                      </div>
                    )}
                  </>
                ) : (
                  <div style={{fontSize:12,color:'#6e6694'}}>Sin lecturas reales</div>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
};


// ─── PAGE: BUILDINGS ──────────────────────────────────────────────────────────
const PageBuildings = () => {
  const [data, setData] = useState({ campuses: [], buildings: [] });

  useEffect(() => {
    const load = () => {
      getCampusMetrics()
        .then(setData)
        .catch((error) => console.error("Buildings metrics API error:", error));
    };

    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const buildings = data.buildings || [];
  const campuses = data.campuses || [];
  const [campusFilter, setCampusFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const filteredBuildings = buildings.filter((b) => {
    const campusOk = campusFilter === "all" || b.campus === campusFilter;
    const statusOk =
      statusFilter === "all" ||
      (statusFilter === "monitored" && b.status === "monitored") ||
      (statusFilter === "no_data" && b.status !== "monitored") ||
      (statusFilter === "anomaly" && b.anomaly);

    return campusOk && statusOk;
  });

  return (
    <div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:18}}>
        <div style={{display:'flex',gap:12}}>
          <select value={campusFilter} onChange={(e) => setCampusFilter(e.target.value)} style={{background:'#12111f',color:'#e2e0f0',border:'1px solid #2a2740',borderRadius:8,padding:'8px 12px'}}>
            <option value="all">Todos los campus</option>
            {campuses.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{background:'#12111f',color:'#e2e0f0',border:'1px solid #2a2740',borderRadius:8,padding:'8px 12px'}}>
            <option value="all">Todos los estados</option>
            <option value="monitored">Monitoreado</option>
            <option value="no_data">Sin lecturas</option>
            <option value="anomaly">Con anomalía</option>
          </select>
        </div>
        <div style={{fontSize:12,color:'#7b739e'}}>{filteredBuildings.length} edificios</div>
      </div>

      <Card>
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse'}}>
            <thead>
              <tr style={{color:'#7b739e',fontSize:11,textTransform:'uppercase',letterSpacing:1}}>
                <th align="left" style={{padding:'0 0 12px'}}>Edificio</th>
                <th align="left" style={{padding:'0 0 12px'}}>Unidad</th>
                <th align="left" style={{padding:'0 0 12px'}}>Campus</th>
                <th align="left" style={{padding:'0 0 12px'}}>Estado</th>
                <th align="left" style={{padding:'0 0 12px'}}>Potencia</th>
                <th align="left" style={{padding:'0 0 12px'}}>Energía hoy</th>
                <th align="left" style={{padding:'0 0 12px'}}>Costo hoy</th>
                <th align="left" style={{padding:'0 0 12px'}}>Anomalía</th>
              </tr>
            </thead>

            <tbody>
              {filteredBuildings.map((b) => (
                <tr key={b.id} style={{borderTop:'1px solid #1f1f35'}}>
                  <td style={{padding:'14px 0'}}>
                    <div style={{fontWeight:800,color:'#f0eeff'}}>{b.name}</div>
                    <div style={{fontSize:11,color:'#7b739e'}}>{b.delegation}</div>
                  </td>

                  <td style={{color:'#c4bdf0'}}>{b.organizational_unit}</td>
                  <td style={{color:'#c4bdf0'}}>{b.campus}</td>

                  <td>
                    <span style={{
                      color:b.status === 'monitored' ? '#22c55e' : '#6b7280',
                      fontWeight:700,
                      fontSize:12
                    }}>
                      {b.status === 'monitored' ? 'Monitoreado' : 'Sin lecturas'}
                    </span>
                  </td>

                  <td style={{fontWeight:700,color:'#f0eeff'}}>
                    {Number(b.power_kw || 0).toFixed(2)} kW
                  </td>

                  <td style={{color:'#c4bdf0'}}>
                    {Number(b.energy_today_kwh || 0).toFixed(4)} kWh
                  </td>

                  <td style={{fontWeight:800,color:'#a78bfa'}}>
                    ${Number(b.cost_today_mxn || 0).toLocaleString('es-MX')} MXN
                  </td>

                  <td>
                    {b.anomaly ? (
                      <span style={{background:'#ef444422',color:'#ef4444',border:'1px solid #ef444455',padding:'3px 9px',borderRadius:999,fontSize:11,fontWeight:800}}>
                        Sí
                      </span>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};


// ─── PAGE: DEPLOYMENTS ────────────────────────────────────────────────────────
const PageDeployments = () => {
  const [nodes, setNodes] = useState([]);
  const [deployments, setDeployments] = useState([]);
  const [delegations, setDelegations] = useState([]);
  const [campuses, setCampuses] = useState([]);
  const [units, setUnits] = useState([]);
  const [saved, setSaved] = useState(false);

  const [form, setForm] = useState({
    node: '',
    delegationId: '',
    campusId: '',
    unitId: '',
    customUnitName: '',
    customUnitType: 'administrative',
    building: '',
    panel: '',
    start: '',
    end: '',
    notes: ''
  });

  const loadBase = () => {
    getNodes().then(setNodes).catch((error) => console.error("Nodes API error:", error));
    getDeployments().then(setDeployments).catch((error) => console.error("Deployments API error:", error));
    getDelegations().then(setDelegations).catch((error) => console.error("Delegations API error:", error));
  };

  useEffect(() => {
    loadBase();
    const timer = setInterval(loadBase, 15000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!form.delegationId) {
      setCampuses([]);
      setUnits([]);
      return;
    }

    getCampusesByDelegation(Number(form.delegationId))
      .then((data) => {
        setCampuses(data);
        setUnits([]);
        setForm((current) => ({...current, campusId:'', unitId:''}));
      })
      .catch((error) => console.error("Campuses API error:", error));
  }, [form.delegationId]);

  useEffect(() => {
    if (!form.campusId) {
      setUnits([]);
      return;
    }

    getUnitsByCampus(Number(form.campusId))
      .then((data) => {
        setUnits(data);
        setForm((current) => ({...current, unitId:''}));
      })
      .catch((error) => console.error("Units API error:", error));
  }, [form.campusId]);

  useEffect(() => {
    if (!form.node && nodes.length > 0) {
      setForm((current) => ({...current, node:nodes[0].id}));
    }
  }, [nodes]);

  const handleSave = async () => {
    const useManualUnit = form.unitId === "__manual__";

    if (!form.node || !form.campusId || !form.building || !form.panel || !form.start || !form.end) {
      alert("Completa nodo, campus, edificio, tablero y fechas.");
      return;
    }

    if (!useManualUnit && !form.unitId) {
      alert("Selecciona una unidad organizacional o agrega una manualmente.");
      return;
    }

    if (useManualUnit && !form.customUnitName) {
      alert("Escribe el nombre de la unidad organizacional.");
      return;
    }

    try {
      await createDeployment({
        node_id: form.node,
        campus_id: Number(form.campusId),
        organizational_unit_id: useManualUnit ? null : Number(form.unitId),
        custom_unit_name: useManualUnit ? form.customUnitName : null,
        custom_unit_type: useManualUnit ? form.customUnitType : null,
        building_name: form.building,
        electrical_panel: form.panel,
        start_date: form.start,
        end_date: form.end,
        notes: form.notes,
      });

      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      loadBase();
    } catch (error) {
      console.error("Create deployment API error:", error);
      alert("No se pudo guardar el despliegue.");
    }
  };

  const activeDeployments = deployments.filter((d) => d.status === "active");
  const pastDeployments = deployments.filter((d) => d.status !== "active");

  const fmtSync = (value) => {
    if (!value) return "Sin sincronía";
    try {
      return new Date(value).toLocaleString("es-MX");
    } catch {
      return value;
    }
  };

  return (
    <div style={{display:'grid',gridTemplateColumns:'1fr 1.4fr',gap:18}}>
      <div>
        <SectionTitle title="Nodos Disponibles" subtitle="Estado real reportado por Raspberry/edge"/>
        {nodes.map((node) => (
          <Card key={node.id} style={{marginBottom:14}} glow={node.status === "online"}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:18}}>
              <div style={{display:'flex',gap:12,alignItems:'center'}}>
                <div style={{background:'#22c55e18',border:'1px solid #22c55e33',borderRadius:10,padding:'9px 11px',color:'#22c55e',fontWeight:900,fontSize:12}}>NODE</div>
                <div>
                  <div style={{fontWeight:800,color:'#f0eeff'}}>{node.name}</div>
                  <div style={{fontSize:11,color:'#7b739e'}}>{node.ip || "Sin IP"}</div>
                </div>
              </div>
              <Badge color={node.status === "online" ? "#22c55e" : "#6b7280"}>{node.status}</Badge>
            </div>

            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12,fontSize:12}}>
              <div><div style={{color:'#6e6694'}}>Edificio</div><b>{node.building || "Sin despliegue"}</b></div>
              <div><div style={{color:'#6e6694'}}>Última sincronía</div><b>{fmtSync(node.last_sync)}</b></div>
              <div><div style={{color:'#6e6694'}}>Muestras</div><b>{Number(node.samples || 0).toLocaleString("es-MX")}</b></div>
              <div><div style={{color:'#6e6694'}}>Buffer</div><b>{Number(node.buffer_pending || 0)} reg. pend.</b></div>
              <div><div style={{color:'#6e6694'}}>Raspberry</div><b>{node.status === "online" ? "OK" : "Sin datos"}</b></div>
              <div><div style={{color:'#6e6694'}}>Shelly</div><b>{node.status === "online" ? "OK" : "Sin datos"}</b></div>
            </div>
          </Card>
        ))}

        <SectionTitle title="Despliegues Pasados" subtitle="Historial real de despliegues cerrados"/>
        {pastDeployments.length === 0 ? (
          <Card>
            <div style={{fontSize:13,color:'#7b739e'}}>No hay despliegues pasados registrados todavía.</div>
          </Card>
        ) : pastDeployments.map((deployment) => (
          <Card key={deployment.id} style={{marginBottom:10}}>
            <div style={{display:'flex',justifyContent:'space-between'}}>
              <b>{deployment.building_name}</b>
              <Badge color={
                deployment.status === "active"
                  ? "#22c55e"
                  : deployment.status === "completed"
                  ? "#3b82f6"
                  : deployment.status === "failed"
                  ? "#ef4444"
                  : "#6b7280"
              }>
                {deployment.status}
              </Badge>
            </div>
            <div style={{fontSize:12,color:'#7b739e',marginTop:6}}>
              {deployment.node_id} · {deployment.start_date} – {deployment.end_date}
            </div>
          </Card>
        ))}
      </div>

      <div>
        <SectionTitle title="En Curso" subtitle="Despliegues activos desde backend"/>
        {activeDeployments.length === 0 ? (
          <Card style={{marginBottom:14}}>
            <div style={{fontSize:13,color:'#7b739e'}}>No hay despliegues activos.</div>
          </Card>
        ) : activeDeployments.map((deployment) => (
          <Card key={deployment.id} style={{marginBottom:14}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
              <div>
                <div style={{fontSize:16,fontWeight:800,color:'#f0eeff'}}>{deployment.building_name}</div>
                <div style={{fontSize:12,color:'#7b739e'}}>
                  {deployment.node_id} · {deployment.electrical_panel}
                </div>
              </div>
              <Badge color="#22c55e">Activo</Badge>
            </div>

            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:12,fontSize:12,marginBottom:14}}>
              <div><div style={{color:'#6e6694'}}>Unidad</div><b>{deployment.organizational_unit}</b></div>
              <div><div style={{color:'#6e6694'}}>Inicio</div><b>{deployment.start_date}</b></div>
              <div><div style={{color:'#6e6694'}}>Fin</div><b>{deployment.end_date}</b></div>
            </div>

            <div style={{background:'#1a1730',borderRadius:8,padding:'9px 12px',fontSize:12,color:'#a9a2d0'}}>
              {deployment.notes || "Sin notas del técnico."}
            </div>
          </Card>
        ))}

        <Card>
          <SectionTitle title="Asignar Nodo" subtitle="Registrar un nuevo despliegue en campo"/>
          {saved && (
            <div style={{background:'#22c55e18',border:'1px solid #22c55e44',color:'#22c55e',borderRadius:10,padding:'10px 12px',fontSize:13,marginBottom:14}}>
              Despliegue guardado correctamente.
            </div>
          )}

          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
            <div style={{display:'flex',flexDirection:'column',gap:5}}>
              <label>Nodo</label>
              <select value={form.node} onChange={(e) => setForm(f => ({...f,node:e.target.value}))}>
                {nodes.map((n) => <option key={n.id} value={n.id}>{n.id} · {n.name}</option>)}
              </select>
            </div>

            <div style={{display:'flex',flexDirection:'column',gap:5}}>
              <label>Delegación</label>
              <select value={form.delegationId} onChange={(e) => setForm(f => ({...f,delegationId:e.target.value}))}>
                <option value="">Seleccionar delegación</option>
                {delegations.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>

            <div style={{display:'flex',flexDirection:'column',gap:5}}>
              <label>Campus</label>
              <select value={form.campusId} disabled={!form.delegationId} onChange={(e) => setForm(f => ({...f,campusId:e.target.value}))}>
                <option value="">Seleccionar campus</option>
                {campuses.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>

            <div style={{display:'flex',flexDirection:'column',gap:5}}>
              <label>Unidad Organizacional</label>
              <select value={form.unitId} disabled={!form.campusId} onChange={(e) => setForm(f => ({...f,unitId:e.target.value}))}>
                <option value="">Seleccionar unidad</option>
                {units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                <option value="__manual__">Otra / agregar manualmente</option>
              </select>
            </div>

            {form.unitId === "__manual__" && (
              <>
                <div style={{display:'flex',flexDirection:'column',gap:5}}>
                  <label>Nombre de unidad</label>
                  <input value={form.customUnitName} onChange={(e) => setForm(f => ({...f,customUnitName:e.target.value}))} placeholder="Ej. CEGAF, DIGESET..." />
                </div>

                <div style={{display:'flex',flexDirection:'column',gap:5}}>
                  <label>Tipo</label>
                  <select value={form.customUnitType} onChange={(e) => setForm(f => ({...f,customUnitType:e.target.value}))}>
                    <option value="administrative">Dependencia administrativa</option>
                    <option value="technical">Técnica / TI</option>
                    <option value="services">Servicios universitarios</option>
                    <option value="faculty">Facultad</option>
                    <option value="center">Centro</option>
                    <option value="other">Otra</option>
                  </select>
                </div>
              </>
            )}

            <div style={{display:'flex',flexDirection:'column',gap:5}}>
              <label>Edificio</label>
              <input value={form.building} disabled={!form.unitId} onChange={(e) => setForm(f => ({...f,building:e.target.value}))} placeholder="Ej. Edificio B, Laboratorio de Redes" />
            </div>

            <div style={{display:'flex',flexDirection:'column',gap:5}}>
              <label>Tablero Eléctrico</label>
              <input value={form.panel} disabled={!form.unitId} onChange={(e) => setForm(f => ({...f,panel:e.target.value}))} placeholder="Ej. Tablero Principal" />
            </div>

            <div style={{display:'flex',flexDirection:'column',gap:5}}>
              <label>Fecha Inicio</label>
              <input type="date" value={form.start} onChange={(e) => setForm(f => ({...f,start:e.target.value}))} />
            </div>

            <div style={{display:'flex',flexDirection:'column',gap:5}}>
              <label>Fecha Fin</label>
              <input type="date" value={form.end} onChange={(e) => setForm(f => ({...f,end:e.target.value}))} />
            </div>
          </div>

          <div style={{display:'flex',flexDirection:'column',gap:5,marginTop:12}}>
            <label>Notas del técnico</label>
            <textarea value={form.notes} onChange={(e) => setForm(f => ({...f,notes:e.target.value}))} placeholder="Observaciones de instalación..." />
          </div>

          <button onClick={handleSave} style={{width:'100%',marginTop:14}}>
            Guardar Despliegue
          </button>
        </Card>
      </div>
    </div>
  );
};


// ─── PAGE: LIVE MONITORING ────────────────────────────────────────────────────
const PageLive = () => {
  const [metrics, setMetrics] = useState([]);

  useEffect(() => {
    const load = () => {
      getLiveMetrics()
        .then(setMetrics)
        .catch((error) => console.error("Live metrics API error:", error));
    };

    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div>
      <div style={{display:'flex',gap:12,marginBottom:18,alignItems:'center'}}>
        <div style={{display:'flex',alignItems:'center',gap:8,background:'#22c55e18',border:'1px solid #22c55e33',borderRadius:20,padding:'5px 14px'}}>
          <div style={{width:8,height:8,borderRadius:'50%',background:'#22c55e',animation:'pulse 2s infinite'}}/>
          <span style={{fontSize:12,color:'#22c55e',fontWeight:600}}>EN VIVO</span>
        </div>
        <span style={{fontSize:12,color:'#6e6694'}}>Actualización cada 3s · Datos desde /api/metrics/live</span>
      </div>

      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}`}</style>

      {metrics.length === 0 ? (
        <Card>
          <div style={{fontSize:13,color:'#7b739e'}}>No hay nodos con métricas reales todavía.</div>
        </Card>
      ) : metrics.map((n) => (
        <Card key={n.node_id} style={{marginBottom:18}} glow={n.status === "online"}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
            <div style={{display:'flex',alignItems:'center',gap:12}}>
              <div style={{
                background:'#22c55e18',
                border:'1px solid #22c55e33',
                borderRadius:10,
                padding:'8px 10px',
                fontSize:12,
                color:'#22c55e',
                fontWeight:800,
                letterSpacing:.8
              }}>
                NODE
              </div>
              <div>
                <div style={{fontSize:15,fontWeight:700,color:'#f0eeff'}}>{n.node_id}</div>
                <div style={{fontSize:11,color:'#6e6694'}}>
                  {n.building || "Sin edificio"} · Última lectura {n.latest_reading ? new Date(n.latest_reading).toLocaleString("es-MX") : "sin datos"}
                </div>
              </div>
            </div>
            <Badge color={n.status === "online" ? "#22c55e" : "#6b7280"}>
              {n.status === "online" ? "Real API" : "Offline"}
            </Badge>
          </div>

          <div style={{display:'flex',flexWrap:'wrap',gap:12}}>
            {[
              {l:'Tensión (V)',v:Number(n.voltage || 0).toFixed(1),c:'#818cf8',unit:'V'},
              {l:'Corriente (A)',v:Number(n.current || 0).toFixed(2),c:'#f59e0b',unit:'A'},
              {l:'Potencia (kW)',v:Number(n.power_kw || 0).toFixed(3),c:'#ef4444',unit:'kW'},
              {l:'Factor de Potencia',v:Number(n.power_factor || 0).toFixed(3),c:'#22c55e',unit:''},
              {l:'Frecuencia (Hz)',v:Number(n.frequency_hz || 0).toFixed(2),c:'#a78bfa',unit:'Hz'},
              {l:'Energía Hoy',v:Number(n.energy_today_kwh || 0).toFixed(3),c:PURPLE_L,unit:'kWh'}
            ].map((m,i) => (
              <div key={i} style={{
                background:'#0f0f1a', borderRadius:12, padding:'14px 16px',
                flex:1, minWidth:120, border:`1px solid ${m.c}22`
              }}>
                <div style={{fontSize:10,color:'#6e6694',textTransform:'uppercase',letterSpacing:.8,marginBottom:6}}>{m.l}</div>
                <div style={{fontSize:26,fontWeight:700,color:m.c}}>{m.v}</div>
                <div style={{fontSize:11,color:'#4b5563',marginTop:2}}>{m.unit}</div>
              </div>
            ))}
          </div>

          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:10,marginTop:12}}>
            {[
              {l:'RPi Status',v:n.rpi_status === "ok" ? "OK" : "Offline",c:n.rpi_status === "ok" ? '#22c55e' : '#6b7280'},
              {l:'Shelly Status',v:n.shelly_status === "ok" ? "OK" : "Offline",c:n.shelly_status === "ok" ? '#22c55e' : '#6b7280'},
              {l:'Buffer',v:`${Number(n.buffer_pending || 0)} pend.`,c:Number(n.buffer_pending || 0)>0?'#f59e0b':'#22c55e'}
            ].map((item,i) => (
              <div key={i} style={{background:'#0a0a14',borderRadius:8,padding:'8px 12px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                <span style={{fontSize:11,color:'#6e6694'}}>{item.l}</span>
                <span style={{fontSize:12,fontWeight:700,color:item.c}}>{item.v}</span>
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
};


// ─── PAGE: COST ANALYTICS ─────────────────────────────────────────────────────
const PageCost = () => {
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    const load = () => {
      getCostSummary()
        .then(setSummary)
        .catch((error) => console.error("Cost summary API error:", error));
    };

    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const periods = summary?.periods || [];
  const rates = summary?.rates || {};

  const mxn = (v) => `$${Number(v || 0).toLocaleString("es-MX")} MXN`;
  const totalCost = periods.reduce((sum, p) => sum + Number(p.cost_mxn || 0), 0) || 1;

  const peak = periods.find(p => p.period === "peak");
  const peakShare = peak ? peak.share_pct : 0;

  return (
    <div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:16,marginBottom:22}}>
        <StatCard label="Costo hoy" value={mxn(summary?.cost_today_mxn)} sub="Datos reales acumulados" color="#ef4444" icon="Wallet"/>
        <StatCard label="Costo esta semana" value={mxn(summary?.cost_week_mxn)} sub="Proyección con datos actuales" color="#f59e0b" icon="Calendar"/>
        <StatCard label="Proyección mensual" value={mxn(summary?.projected_month_mxn)} sub="Extrapolación simple" color="#a78bfa" icon="TrendingUp"/>
        <StatCard label="Costo por punta" value={`${Number(peakShare || 0).toFixed(1)}%`} sub="Participación real actual" color="#ef4444" icon="Zap"/>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'2fr 1fr',gap:18,marginBottom:22}}>
        <Card>
          <SectionTitle title="Análisis por Periodo Tarifario" subtitle="Desglose real por periodo tarifario GDMTH"/>
          {periods.length === 0 ? (
            <div style={{fontSize:13,color:'#7b739e'}}>Sin consumo real registrado todavía.</div>
          ) : periods.map((p, i) => {
            const color = p.period === "peak" ? "#ef4444" : p.period === "intermediate" ? "#f59e0b" : "#818cf8";
            const label = p.period === "peak" ? "Punta" : p.period === "intermediate" ? "Intermedia" : "Base";
            const width = Math.max(2, (Number(p.cost_mxn || 0) / totalCost) * 100);

            return (
              <div key={i} style={{marginBottom:22}}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
                  <div style={{display:'flex',alignItems:'center',gap:8}}>
                    <div style={{width:10,height:10,borderRadius:2,background:color}}/>
                    <b>{label}</b>
                  </div>
                  <div style={{fontWeight:800,color}}>{mxn(p.cost_mxn)}</div>
                </div>
                <div style={{height:8,background:'#1a1730',borderRadius:99,overflow:'hidden'}}>
                  <div style={{height:'100%',width:`${width}%`,background:color,borderRadius:99}}/>
                </div>
                <div style={{display:'flex',justifyContent:'space-between',fontSize:11,color:'#7b739e',marginTop:6}}>
                  <span>{Number(p.share_pct || 0).toFixed(1)}% del costo total</span>
                  <span>{Number(p.kwh || 0).toFixed(4)} kWh</span>
                </div>
              </div>
            );
          })}
        </Card>

        <Card>
          <SectionTitle title="Tarifa Activa" subtitle="Fuente: configuración local"/>
          <div style={{fontSize:24,fontWeight:900,color:PURPLE_L,marginBottom:4}}>GDMTH</div>
          <div style={{fontSize:12,color:'#7b739e',marginBottom:22}}>Gran Demanda en Media Tensión H</div>

          {[
            ["Base", rates.base],
            ["Intermedia", rates.intermediate],
            ["Punta", rates.peak],
          ].map(([name, value]) => (
            <div key={name} style={{display:'flex',justifyContent:'space-between',fontSize:13,marginBottom:14}}>
              <span style={{color:'#7b739e'}}>Cargo {name}</span>
              <b>${Number(value || 0).toFixed(2)}/kWh</b>
            </div>
          ))}

          <div style={{display:'flex',justifyContent:'space-between',fontSize:13,marginTop:20}}>
            <span style={{color:'#7b739e'}}>Estado CFE API</span>
            <b>Manual fallback</b>
          </div>
        </Card>
      </div>

      <Card>
        <SectionTitle title="Simulador de Ahorro" subtitle="Deshabilitado hasta contar con histórico suficiente"/>
        <div style={{background:'#1a1730',borderRadius:12,padding:18,color:'#a9a2d0',fontSize:13}}>
          El simulador requiere más datos históricos para estimar escenarios de ahorro sin usar placeholders.
        </div>
      </Card>
    </div>
  );
};


// ─── PAGE: AI CENTER ──────────────────────────────────────────────────────────
const PageAI = ({ apiInsights, apiAnomalies }) => {
  const [tab, setTab] = useState("forecast");
  const [aiData, setAiData] = useState(null);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([
    { role: "assistant", text: "Hola. Soy el Asistente de Energía IA. Puedes preguntarme sobre costos, consumo, anomalías o comparaciones entre edificios." }
  ]);

  useEffect(() => {
    const load = () => {
      getAiCenter()
        .then(setAiData)
        .catch((error) => console.error("AI Center API error:", error));
    };

    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, []);

  const forecast = aiData?.forecast || {};
  const anomalies = aiData?.anomalies || {};
  const recommendations = aiData?.recommendations || [];

  const sendQuestion = () => {
    const clean = question.trim();
    if (!clean) return;

    setMessages((current) => [...current, { role: "user", text: clean }]);
    setQuestion("");

    askAiAssistant(clean)
      .then((res) => {
        setMessages((current) => [...current, { role: "assistant", text: res.answer }]);
      })
      .catch((error) => {
        console.error("AI assistant frontend error:", error);
        setMessages((current) => [...current, { role: "assistant", text: `No pude consultar el backend IA: ${error.message}` }]);
      });
  };

  const tabs = [
    ["forecast", "Pronóstico"],
    ["anomalies", "Anomalías"],
    ["recommendations", "Recomendaciones"],
    ["assistant", "Asistente IA"],
  ];

  const mxn = (v) => `$${Number(v || 0).toLocaleString("es-MX")} MXN`;

  return (
    <div>
      <div style={{display:'flex',gap:8,background:'#11111c',padding:4,borderRadius:12,width:'fit-content',marginBottom:20}}>
        {tabs.map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} style={{
            background:tab === key ? PURPLE : 'transparent',
            color:tab === key ? '#fff' : '#8b83ad',
            border:0,
            borderRadius:9,
            padding:'10px 22px',
            fontWeight:800,
            cursor:'pointer',
          }}>
            {label}
          </button>
        ))}
      </div>

      {tab === "forecast" && (
        <>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:16,marginBottom:18}}>
            <StatCard label="Proyección mañana" value={mxn(forecast.tomorrow_mxn)} sub={`Confianza ${(Number(forecast.confidence || 0) * 100).toFixed(0)}%`} color="#818cf8" icon="ArrowRight"/>
            <StatCard label="Proyección semana" value={mxn(forecast.week_mxn)} sub="Basado en consumo real" color="#a78bfa" icon="BarChart"/>
            <StatCard label="Proyección mensual" value={mxn(forecast.month_mxn)} sub="Tendencia actual" color="#f59e0b" icon="TrendingUp"/>
          </div>

          <Card>
            <SectionTitle title="Pronóstico de Costo (MXN)" subtitle={`${forecast.method || "Modelo basado en datos reales"} · intervalo de confianza dinámico`}/>
            <div style={{height:240,border:'1px solid #1f1f35',borderRadius:12,padding:16}}>
              <svg width="100%" height="200" viewBox="0 0 600 200" preserveAspectRatio="none">
                <line x1="0" y1="180" x2="600" y2="180" stroke="#2a2740"/>
                <line x1="0" y1="120" x2="600" y2="120" stroke="#1f1f35" strokeDasharray="4 4"/>
                <line x1="0" y1="60" x2="600" y2="60" stroke="#1f1f35" strokeDasharray="4 4"/>
                {(() => {
                  const pts = forecast.points || [];
                  const max = Math.max(...pts.map(p => p.value || 0), 1);
                  const points = pts.map((p, i) => `${(i / Math.max(pts.length - 1, 1)) * 600},${180 - ((p.value || 0) / max) * 150}`).join(" ");
                  return <polyline points={points} fill="none" stroke="#a78bfa" strokeWidth="3" strokeDasharray="7 4"/>;
                })()}
              </svg>
              <div style={{display:'flex',justifyContent:'space-between',fontSize:12,color:'#7b739e'}}>
                {(forecast.points || []).map(p => <span key={p.label}>{p.label}</span>)}
              </div>
            </div>
          </Card>
        </>
      )}

      {tab === "anomalies" && (
        <>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:16,marginBottom:18}}>
            <StatCard label="Anomalías hoy" value={anomalies.today_count || 0} sub="Detectadas con reglas reales" color="#ef4444" icon="AlertTriangle"/>
            <StatCard label="Anomalías esta semana" value={anomalies.week_count || 0} sub={`Revisadas: ${anomalies.reviewed || 0}`} color="#f59e0b" icon="Clipboard"/>
          </div>

          {(anomalies.items || []).length === 0 ? (
            <Card>
              <div style={{fontSize:13,color:'#7b739e'}}>No hay anomalías activas con los datos actuales.</div>
            </Card>
          ) : anomalies.items.map((item, i) => (
            <Card key={i} style={{marginBottom:12,borderLeft:`4px solid ${item.color || '#818cf8'}`}}>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                <div>
                  <div style={{fontWeight:900,color:'#f0eeff',marginBottom:4}}>{item.title}</div>
                  <div style={{fontSize:12,color:'#7b739e'}}>{item.building} · {item.time}</div>
                  <div style={{fontSize:12,color:'#a9a2d0',marginTop:10}}>
                    Detectado: <b style={{color:'#ef4444'}}>{item.detected}</b>
                    <span style={{marginLeft:18}}>Esperado: <b style={{color:'#22c55e'}}>{item.expected}</b></span>
                  </div>
                </div>
                <Badge color={item.color || '#818cf8'}>{item.severity}</Badge>
              </div>
            </Card>
          ))}
        </>
      )}

      {tab === "recommendations" && (
        <>
          {recommendations.map((rec, i) => (
            <Card key={i} style={{marginBottom:14}}>
              <div style={{display:'flex',justifyContent:'space-between',gap:18}}>
                <div style={{flex:1}}>
                  <Badge color={rec.priority === "Alta prioridad" ? "#ef4444" : "#f59e0b"}>{rec.priority}</Badge>
                  <div style={{fontSize:16,fontWeight:900,color:'#f0eeff',marginTop:10}}>{rec.title}</div>
                  <div style={{fontSize:12,color:'#7b739e',marginBottom:14}}>{rec.building}</div>
                  <div style={{fontSize:13,color:'#a9a2d0',lineHeight:1.5}}>{rec.description}</div>
                  <div style={{marginTop:14,background:'#1b1730',borderRadius:8,padding:'9px 12px',fontSize:13,color:'#c4b5fd'}}>
                    → {rec.action}
                  </div>
                </div>
                <div style={{minWidth:120,textAlign:'right'}}>
                  <div style={{fontSize:11,color:'#7b739e'}}>Ahorro estimado</div>
                  <div style={{fontSize:26,fontWeight:900,color:'#22c55e'}}>${Number(rec.saving_mxn_month || 0).toLocaleString("es-MX")}</div>
                  <div style={{fontSize:11,color:'#7b739e'}}>MXN/mes</div>
                </div>
              </div>
            </Card>
          ))}
        </>
      )}

      {tab === "assistant" && (
        <Card style={{minHeight:470,display:'flex',flexDirection:'column'}}>
          <div style={{flex:1,overflowY:'auto',paddingBottom:20}}>
            {messages.map((msg, i) => (
              <div key={i} style={{
                display:'flex',
                justifyContent:msg.role === "user" ? "flex-end" : "flex-start",
                marginBottom:12
              }}>
                <div style={{
                  maxWidth:'70%',
                  background:msg.role === "user" ? '#6d4fc2' : '#10101a',
                  border:'1px solid #2a2740',
                  borderRadius:12,
                  padding:'12px 14px',
                  fontSize:13,
                  color:'#f0eeff',
                }}>
                  {msg.role === "assistant" ? (
                    <div className="ai-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.text}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    msg.text
                  )}
                </div>
              </div>
            ))}
          </div>

          <div>
            <div style={{display:'flex',gap:10}}>
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") sendQuestion(); }}
                placeholder="Pregunta sobre costos, anomalías, ahorro..."
                style={{
                  flex:1,
                  background:'#0f0f1a',
                  border:'1px solid #2a2740',
                  color:'#f0eeff',
                  borderRadius:8,
                  padding:'12px',
                }}
              />
              <button onClick={sendQuestion} style={{
                background:PURPLE,
                border:0,
                color:'#fff',
                borderRadius:9,
                padding:'0 24px',
                fontWeight:900,
              }}>
                Enviar
              </button>
            </div>
            <div style={{display:'flex',gap:6,marginTop:10,flexWrap:'wrap'}}>
              {["¿Qué edificio costó más esta semana?","¿Cuánto podemos ahorrar?","¿Hubo anomalías hoy?","Proyección de costo del mes"].map((q) => (
                <button key={q} onClick={() => setQuestion(q)} style={{
                  background:'#1b1730',
                  border:'1px solid #2a2740',
                  color:'#a78bfa',
                  borderRadius:999,
                  padding:'5px 10px',
                  fontSize:11,
                }}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
};



// ─── PAGE: DATA MINING ────────────────────────────────────────────────────────
const PageMining = () => {
  const [mining, setMining] = useState(null);

  useEffect(() => {
    const load = () => {
      getMiningAnalytics()
        .then(setMining)
        .catch((error) => console.error("Mining API error:", error));
    };

    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, []);

  const clusters = mining?.clusters || [];
  const correlation = mining?.correlation || {};
  const patterns = mining?.patterns || [];
  const insights = mining?.insights || [];
  const clusterColors = ["#818cf8", "#22c55e", "#ef4444", "#f59e0b", "#a78bfa"];

  const BlockTitle = ({title, subtitle}) => (
    <div style={{marginBottom:18}}>
      <div style={{fontSize:18,fontWeight:900,color:'#f0eeff',marginBottom:4}}>{title}</div>
      <div style={{fontSize:12,color:'#7b739e'}}>{subtitle}</div>
    </div>
  );

  return (
    <div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:18,marginBottom:18}}>
        <Card>
          <BlockTitle title="Clustering de Edificios" subtitle="K-Means clustering de comportamiento de consumo"/>
          {clusters.map((cluster, i) => {
            const color = clusterColors[i % clusterColors.length];
            return (
              <div key={cluster.name} style={{
                borderLeft:`4px solid ${color}`,
                padding:'14px 16px',
                marginBottom:12,
                background:'#0f0f1a',
                borderRadius:10,
              }}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
                  <div style={{fontWeight:800,color:'#f0eeff'}}>{cluster.name}</div>
                  <Badge color={color}>{cluster.count} edificio{cluster.count === 1 ? "" : "s"}</Badge>
                </div>
                <div style={{fontSize:12,color:'#7b739e',marginBottom:8}}>{cluster.description}</div>
                <div style={{display:'flex',gap:6,flexWrap:'wrap'}}>
                  {(cluster.buildings || []).length === 0 ? (
                    <span style={{fontSize:12,color:'#6e6694'}}>Sin edificios clasificados todavía</span>
                  ) : cluster.buildings.map((name) => (
                    <span key={name} style={{
                      border:`1px solid ${color}66`,
                      color,
                      borderRadius:999,
                      padding:'3px 9px',
                      fontSize:11,
                      fontWeight:700,
                      background:`${color}18`,
                    }}>
                      {name}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </Card>

        <Card>
          <BlockTitle title={correlation.title || "Correlación entre edificios"} subtitle="Correlación de consumo entre edificios monitoreados"/>
          {correlation.available ? (
            <>
              <div style={{height:210,border:'1px solid #1f1f35',borderRadius:12,padding:14,marginBottom:14}}>
                <svg width="100%" height="170" viewBox="0 0 500 170" preserveAspectRatio="none">
                  <line x1="0" y1="150" x2="500" y2="150" stroke="#2a2740" />
                  <line x1="0" y1="100" x2="500" y2="100" stroke="#1f1f35" strokeDasharray="4 4" />
                  <line x1="0" y1="50" x2="500" y2="50" stroke="#1f1f35" strokeDasharray="4 4" />
                  {(() => {
                    const a = correlation.series_a || [];
                    const b = correlation.series_b || [];
                    const vals = [...a.map(x => x.value), ...b.map(x => x.value)];
                    const max = Math.max(...vals, 1);
                    const pointsA = a.map((x, i) => `${(i / Math.max(a.length - 1, 1)) * 500},${150 - (x.value / max) * 130}`).join(" ");
                    const pointsB = b.map((x, i) => `${(i / Math.max(b.length - 1, 1)) * 500},${150 - (x.value / max) * 130}`).join(" ");
                    return (
                      <>
                        <polyline points={pointsA} fill="none" stroke="#a78bfa" strokeWidth="3"/>
                        <polyline points={pointsB} fill="none" stroke="#22c55e" strokeWidth="3" strokeDasharray="6 4"/>
                      </>
                    );
                  })()}
                </svg>
              </div>
              <div style={{fontSize:13,color:'#a9a2d0'}}>
                Coeficiente de correlación Pearson: <b style={{color:PURPLE_L}}>{Number(correlation.coefficient || 0).toFixed(2)}</b>
              </div>
            </>
          ) : (
            <div style={{height:210,display:'flex',alignItems:'center',justifyContent:'center',border:'1px solid #1f1f35',borderRadius:12,color:'#7b739e',fontSize:13,textAlign:'center',padding:20}}>
              {correlation.message || "Se requieren al menos 2 edificios con lecturas reales."}
            </div>
          )}
        </Card>
      </div>

      <Card style={{marginBottom:18}}>
        <BlockTitle title="Descubrimiento de Patrones" subtitle="Patrones descubiertos por el motor de minería de datos"/>
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(210px,1fr))',gap:14}}>
          {patterns.map((pattern, i) => {
            const color = pattern.severity === "high" ? "#ef4444" : pattern.severity === "warning" ? "#f59e0b" : pattern.severity === "medium" ? "#a78bfa" : "#818cf8";
            return (
              <div key={i} style={{
                border:`1px solid ${color}55`,
                borderRadius:12,
                padding:14,
                background:'#0f0f1a',
              }}>
                <div style={{marginBottom:12}}>
                  <Icon name={pattern.severity === "high" ? "TrendingUp" : pattern.severity === "warning" ? "Zap" : "Database"} size={18} color={color}/>
                </div>
                <div style={{fontWeight:800,color:'#f0eeff',marginBottom:4}}>{pattern.title}</div>
                <div style={{fontSize:12,color:PURPLE_L,marginBottom:8}}>{pattern.building}</div>
                <div style={{fontSize:12,color:'#7b739e',lineHeight:1.45}}>{pattern.description}</div>
              </div>
            );
          })}
        </div>
      </Card>

      <AIInsightCard insights={insights}/>
    </div>
  );
};


// ─── PAGE: REPORTS ───────────────────────────────────────────────────────────
const PageReports = () => {
  const API = "http://127.0.0.1:8010/api/reports";
  const download = (path) => window.open(`${API}${path}`, "_blank");

  const reports = [
    { title: "Resumen Semanal de Costo", type: "Ejecutivo", date: "Datos reales", status: "Disponible", icon: "Wallet", path: "/weekly-cost.pdf" },
    { title: "Comparación de Edificios", type: "Técnico", date: "Datos reales", status: "Disponible", icon: "Building", path: "/building-comparison.pdf" },
    { title: "Reporte de Anomalías IA", type: "IA", date: "Isolation Forest", status: "Disponible", icon: "AlertTriangle", path: "/anomalies.pdf" },
    { title: "Reporte de Despliegue de Nodos", type: "Técnico", date: "Estado actual", status: "Disponible", icon: "Cpu", path: "/deployments.pdf" },
    { title: "Reporte de Sostenibilidad", type: "Ejecutivo", date: "Datos reales", status: "Disponible", icon: "Leaf", path: "/sustainability.pdf" },
    { title: "Dataset Completo CSV", type: "Datos", date: "Lecturas reales", status: "Disponible", icon: "BarChart", path: "/dataset.csv" },
  ];

  return (
    <div>
      <div style={{display:'flex',gap:14,marginBottom:24}}>
        <button onClick={() => download("/raw-readings.pdf")} style={{background:PURPLE,color:'#fff',border:0,borderRadius:10,padding:'14px 28px',fontWeight:900,fontSize:15,cursor:'pointer'}}>Exportar PDF</button>
        <button onClick={() => download("/dataset.csv")} style={{background:PURPLE,color:'#fff',border:0,borderRadius:10,padding:'14px 28px',fontWeight:900,fontSize:15,cursor:'pointer'}}>Exportar CSV</button>
        <button onClick={() => download("/dataset.xlsx")} style={{background:PURPLE,color:'#fff',border:0,borderRadius:10,padding:'14px 28px',fontWeight:900,fontSize:15,cursor:'pointer'}}>Exportar Excel</button>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(330px,1fr))',gap:16}}>
        {reports.map((report) => (
          <Card key={report.title}>
            <div style={{display:'flex',gap:16,alignItems:'flex-start'}}>
              <div style={{
                width:46,height:46,borderRadius:12,background:'#1b1730',
                border:'1px solid #342a5f',display:'flex',alignItems:'center',
                justifyContent:'center',flexShrink:0
              }}>
                <Icon name={report.icon} size={22} color={PURPLE_L}/>
              </div>

              <div style={{flex:1}}>
                <div style={{fontSize:16,fontWeight:900,color:'#f0eeff',marginBottom:4}}>
                  {report.title}
                </div>
                <div style={{fontSize:12,color:'#7b739e',marginBottom:18}}>
                  {report.type} · {report.date}
                </div>

                <div style={{display:'flex',alignItems:'center',justifyContent:'space-between'}}>
                  <Badge color={report.status === "Disponible" ? "#22c55e" : "#f59e0b"}>
                    {report.status}
                  </Badge>

                  <button
                    onClick={() => download(report.path)}
                    style={{
                      background:'transparent',
                      border:'1px solid #342a5f',
                      color:'#c4b5fd',
                      borderRadius:8,
                      padding:'7px 16px',
                      cursor:'pointer',
                    }}
                  >
                    Descargar
                  </button>
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};


// ─── PAGE: INFRASTRUCTURE ─────────────────────────────────────────────────────
const PageInfra = () => {
  const [infra, setInfra] = useState(null);

  useEffect(() => {
    const load = () => {
      getInfrastructureStatus()
        .then(setInfra)
        .catch((error) => console.error("Infrastructure API error:", error));
    };

    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const summary = infra?.summary || {};
  const services = infra?.services || [];
  const nodes = infra?.nodes || [];

  const lastSyncText = summary.latest_sync
    ? new Date(summary.latest_sync).toLocaleString("es-MX")
    : "Sin sincronía";

  const statusColor = (status) => {
    if (status === "OK" || status === "online") return "#22c55e";
    if (status === "Sin datos") return "#f59e0b";
    return "#6b7280";
  };

  return (
    <div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:16,marginBottom:22}}>
        <StatCard label="Nodos online" value={`${summary.online_nodes || 0}/${summary.total_nodes || 0}`} sub="Disponibilidad real" color="#22c55e" icon="Activity"/>
        <StatCard label="Muestras acumuladas" value={Number(summary.total_samples || 0).toLocaleString("es-MX")} sub="Reportadas por edge" color="#a78bfa" icon="BarChart"/>
        <StatCard label="Buffer pendiente" value={`${summary.buffer_pending || 0} reg.`} sub="Pendientes de sincronía" color="#f59e0b" icon="Clock"/>
        <StatCard label="Lecturas backend" value={Number(summary.total_readings || 0).toLocaleString("es-MX")} sub="En base de datos" color="#22c55e" icon="Database"/>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:14,marginBottom:18}}>
        {services.map((service, i) => (
          <Card key={i}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
              <div style={{display:'flex',alignItems:'center',gap:12}}>
                <div style={{border:'1px solid #2a2740',background:'#10101a',borderRadius:10,padding:10}}>
                  <Icon name={service.name.includes("Base") ? "Database" : service.name.includes("VPN") ? "Lock" : "Server"} size={18} color={PURPLE_L}/>
                </div>
                <div>
                  <div style={{fontWeight:800,color:'#f0eeff'}}>{service.name}</div>
                  <div style={{fontSize:12,color:'#7b739e'}}>{service.detail}</div>
                </div>
              </div>
              <div style={{display:'flex',alignItems:'center',gap:8}}>
                <StatusDot status={service.status === "OK" ? "online" : service.status === "Sin datos" ? "warning" : "offline"}/>
                <b style={{fontSize:12,color:statusColor(service.status)}}>{service.status}</b>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {nodes.map((node) => (
        <Card key={node.id} style={{marginBottom:14}}>
          <SectionTitle title={`${node.id} — Detalle de Hardware`} subtitle={node.status === "online" ? "Nodo detectado recientemente" : "Nodo sin sincronía reciente"}/>
          <div style={{display:'grid',gridTemplateColumns:'repeat(8,1fr)',gap:12,fontSize:12}}>
            <div><div style={{color:'#6e6694'}}>IP</div><b>{node.ip || "Sin IP"}</b></div>
            <div><div style={{color:'#6e6694'}}>Estado</div><b style={{color:statusColor(node.status)}}>{node.status}</b></div>
            <div><div style={{color:'#6e6694'}}>Muestras</div><b>{Number(node.samples || 0).toLocaleString("es-MX")}</b></div>
            <div><div style={{color:'#6e6694'}}>Buffer</div><b>{Number(node.buffer_pending || 0)} pend.</b></div>
            <div><div style={{color:'#6e6694'}}>RPi Status</div><b>{node.rpi_status}</b></div>
            <div><div style={{color:'#6e6694'}}>Shelly Status</div><b>{node.shelly_status}</b></div>
            <div><div style={{color:'#6e6694'}}>Última Sync</div><b>{node.last_sync ? new Date(node.last_sync).toLocaleString("es-MX") : "Sin sync"}</b></div>
            <div><div style={{color:'#6e6694'}}>Edificio</div><b>{node.building || "Sin edificio"}</b></div>
          </div>

          <div style={{display:'grid',gridTemplateColumns:'repeat(5,1fr)',gap:12,fontSize:12,marginTop:14}}>
            <div><div style={{color:'#6e6694'}}>Voltaje</div><b>{node.voltage ? Number(node.voltage).toFixed(1) : "0.0"} V</b></div>
            <div><div style={{color:'#6e6694'}}>Corriente</div><b>{node.current ? Number(node.current).toFixed(2) : "0.00"} A</b></div>
            <div><div style={{color:'#6e6694'}}>Potencia</div><b>{node.power_kw ? Number(node.power_kw).toFixed(3) : "0.000"} kW</b></div>
            <div><div style={{color:'#6e6694'}}>FP</div><b>{node.power_factor ? Number(node.power_factor).toFixed(3) : "0.000"}</b></div>
            <div><div style={{color:'#6e6694'}}>Frecuencia</div><b>{node.frequency_hz ? Number(node.frequency_hz).toFixed(2) : "0.00"} Hz</b></div>
          </div>
        </Card>
      ))}
    </div>
  );
};


// ─── PAGE: SETTINGS ──────────────────────────────────────────────────────────
const PageSettings = ({ role, setRole }) => {
  const [settings, setSettings] = useState(null);
  const [localThresholds, setLocalThresholds] = useState(null);

  useEffect(() => {
    const load = () => {
      getSystemSettings()
        .then((data) => {
          setSettings(data);
          setLocalThresholds((current) => current || data.thresholds || {});
        })
        .catch((error) => console.error("Settings API error:", error));
    };

    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const tariffs = settings?.tariffs || {};
  const counts = settings?.counts || {};
  const system = settings?.system || {};
  const thresholds = localThresholds || settings?.thresholds || {};
  const nodes = settings?.nodes || [];

  const updateThreshold = (key, value) => {
    setLocalThresholds((current) => ({
      ...(current || {}),
      [key]: Number(value)
    }));
  };

  const statusBadge = (value) => (
    <span style={{
      color:value === "online" ? "#22c55e" : "#6b7280",
      background:value === "online" ? "#22c55e18" : "#6b728018",
      border:`1px solid ${value === "online" ? "#22c55e44" : "#6b728044"}`,
      borderRadius:999,
      padding:'3px 10px',
      fontSize:11,
      fontWeight:800
    }}>
      {value}
    </span>
  );

  return (
    <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:18}}>
      <Card>
        <SectionTitle title="Perfil de Usuario" subtitle="Sesión local para simulación de roles"/>
        {[
          ["Nombre", "Administrador UdeC"],
          ["Email", "admin@ucol.mx"],
          ["Rol actual", role],
          ["Campus", "Universidad de Colima"],
        ].map(([label, value]) => (
          <div key={label} style={{display:'flex',justifyContent:'space-between',marginBottom:14,fontSize:13}}>
            <span style={{color:'#7b739e'}}>{label}</span>
            <b style={{color:'#f0eeff'}}>{value}</b>
          </div>
        ))}
      </Card>

      <Card>
        <SectionTitle title="Tarifa Activa" subtitle="Valores reales usados por el motor de costos"/>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:18}}>
          <div>
            <div style={{fontSize:26,fontWeight:900,color:PURPLE_L}}>GDMTH</div>
            <div style={{fontSize:12,color:'#7b739e'}}>Gran Demanda en Media Tensión H · {tariffs.month || "JUN-26"}</div>
          </div>
          <Badge color="#a78bfa">{tariffs.source || "Manual fallback"}</Badge>
        </div>

        {[
          ["Cargo Base", tariffs.base],
          ["Cargo Intermedia", tariffs.intermediate],
          ["Cargo Punta", tariffs.peak],
        ].map(([label, value]) => (
          <div key={label} style={{display:'flex',justifyContent:'space-between',marginBottom:13,fontSize:13}}>
            <span style={{color:'#7b739e'}}>{label}</span>
            <b>${Number(value || 0).toFixed(4)}/kWh</b>
          </div>
        ))}

        <button disabled style={{
          width:'100%',
          marginTop:14,
          opacity:.55,
          cursor:'not-allowed',
          background:'#1f1b35',
          border:'1px solid #3b315f',
          color:'#a78bfa',
          borderRadius:8,
          padding:'9px 12px',
          fontWeight:700
        }}>
          Actualizar desde CFE API / scraper pendiente
        </button>
      </Card>

      <Card>
        <SectionTitle title="Selector de Rol" subtitle="Cambia la vista operativa del dashboard"/>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
          {["Administrador","Ejecutivo","Técnico","Investigador"].map((item) => (
            <button key={item} onClick={() => setRole(item)} style={{
              background:role === item ? '#261d3e' : '#10101a',
              border:`1px solid ${role === item ? '#a78bfa' : '#2a2740'}`,
              color:role === item ? '#c4b5fd' : '#8b83ad',
              borderRadius:10,
              padding:'12px',
              fontWeight:800
            }}>
              {item}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <SectionTitle title="Estado del Sistema" subtitle="Salud real del backend y sincronización"/>
        {[
          ["Backend API", system.backend_api || "sin datos"],
          ["Base de datos", system.database || "sin datos"],
          ["Zona horaria", system.timezone || "sin datos"],
          ["Última lectura", system.last_reading ? new Date(system.last_reading).toLocaleString("es-MX") : "Sin lecturas"],
        ].map(([label, value]) => (
          <div key={label} style={{display:'flex',justifyContent:'space-between',marginBottom:14,fontSize:13}}>
            <span style={{color:'#7b739e'}}>{label}</span>
            <b style={{color:value === "online" ? "#22c55e" : "#f0eeff"}}>{value}</b>
          </div>
        ))}
      </Card>

      <Card>
        <SectionTitle title="Umbrales de Alertas" subtitle="Parámetros editables localmente para anomalías"/>
        {[
          ["min_power_factor", "Factor de potencia mínimo", "", 0.01],
          ["max_current_a", "Corriente máxima", "A", 1],
          ["night_power_kw", "Consumo nocturno", "kW", 0.5],
          ["node_offline_seconds", "Nodo offline", "s", 30],
        ].map(([key, label, unit, step]) => (
          <div key={key} style={{display:'grid',gridTemplateColumns:'1fr 130px 40px',gap:10,alignItems:'center',marginBottom:12}}>
            <span style={{color:'#7b739e',fontSize:13}}>{label}</span>
            <input
              type="number"
              step={step}
              value={thresholds[key] ?? 0}
              onChange={(e) => updateThreshold(key, e.target.value)}
              style={{
                background:'#10101a',
                border:'1px solid #2a2740',
                color:'#f0eeff',
                borderRadius:8,
                padding:'8px 10px',
                textAlign:'right'
              }}
            />
            <span style={{color:PURPLE_L,fontSize:12,fontWeight:800}}>{unit}</span>
          </div>
        ))}

        <div style={{fontSize:11,color:'#7b739e',marginTop:10}}>
          Estos cambios son locales por ahora. Persistencia en backend pendiente.
        </div>
      </Card>

      <Card>
        <SectionTitle title="Inventario del Sistema" subtitle="Conteos reales registrados en base de datos"/>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
          {[
            ["Nodos totales", counts.nodes_total],
            ["Nodos online", counts.nodes_online],
            ["Campus", counts.campuses],
            ["Edificios", counts.buildings],
            ["Despliegues", counts.deployments],
            ["Lecturas", counts.readings],
          ].map(([label, value]) => (
            <div key={label} style={{background:'#0f0f1a',border:'1px solid #1f1f35',borderRadius:10,padding:12}}>
              <div style={{fontSize:11,color:'#7b739e',marginBottom:6}}>{label}</div>
              <div style={{fontSize:22,fontWeight:900,color:'#f0eeff'}}>{Number(value || 0).toLocaleString("es-MX")}</div>
            </div>
          ))}
        </div>
      </Card>

      <Card style={{gridColumn:'1 / -1'}}>
        <SectionTitle title="Nodos Registrados" subtitle="Estado real reportado por heartbeat"/>
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse'}}>
            <thead>
              <tr style={{fontSize:11,color:'#7b739e',textTransform:'uppercase',letterSpacing:1}}>
                <th align="left" style={{padding:'0 0 12px'}}>Nodo</th>
                <th align="left" style={{padding:'0 0 12px'}}>Estado</th>
                <th align="left" style={{padding:'0 0 12px'}}>Última sincronía</th>
                <th align="left" style={{padding:'0 0 12px'}}>Buffer</th>
                <th align="left" style={{padding:'0 0 12px'}}>Muestras</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map((node) => (
                <tr key={node.id} style={{borderTop:'1px solid #1f1f35'}}>
                  <td style={{padding:'13px 0'}}>
                    <b>{node.id}</b>
                    <div style={{color:'#7b739e',fontSize:12}}>{node.name}</div>
                  </td>
                  <td>{statusBadge(node.status)}</td>
                  <td style={{color:'#c4bdf0'}}>{node.last_sync ? new Date(node.last_sync).toLocaleString("es-MX") : "Sin sincronía"}</td>
                  <td style={{color:Number(node.buffer_pending || 0) > 0 ? "#f59e0b" : "#22c55e",fontWeight:800}}>
                    {Number(node.buffer_pending || 0)} pendientes
                  </td>
                  <td>{Number(node.samples || 0).toLocaleString("es-MX")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};




const App = () => {
  const [apiBuildings, setApiBuildings] = useState(null);
  const [apiNodes, setApiNodes] = useState(null);
  const [apiInsights, setApiInsights] = useState(null);
  const [apiAnomalies, setApiAnomalies] = useState(null);

  useEffect(() => {
    getDashboardSummary()
      .then((data) => console.log("Backend dashboard summary:", data))
      .catch((error) => console.error("Backend API error:", error));

    getBuildings()
      .then((data) => {
        const normalized = data.map((building) => ({
          id: building.id,
          name: building.name,
          faculty: building.faculty,
          campus: building.campus,
          node: building.node,
          status: building.status,
          power: building.power_kw,
          energy_week: building.energy_week_kwh,
          cost_week: building.cost_week_mxn,
          cost_today: building.cost_today_mxn,
          anomaly: building.anomaly,
          last_update: building.last_update,
        }));
        setApiBuildings(normalized);
      })
      .catch((error) => console.error("Buildings API error:", error));

    getNodes()
      .then((data) => {
        const normalized = data.map((node) => ({
          id: node.id,
          name: node.name,
          status: node.status,
          ip: node.ip,
          building: node.building,
          campus: node.campus,
          voltage: node.voltage,
          current: node.current,
          power: node.power_kw,
          energy_today: node.energy_today_kwh,
          pf: node.power_factor,
          freq: node.frequency_hz,
          last_sync: node.last_sync,
          buffer: node.buffer_pending,
          samples: node.samples,
          rpi_status: "ok",
          shelly_status: "ok",
          fw: "1.4.2",
        }));
        setApiNodes(normalized);
      })
      .catch((error) => console.error("Nodes API error:", error));

    getAiInsights()
      .then((data) => setApiInsights(data))
      .catch((error) => console.error("AI insights API error:", error));

    getDelegations()
      .then((data) => console.log("UdeC delegations:", data))
      .catch((error) => console.error("Delegations API error:", error));

    getAllOrgBuildings()
      .then((data) => console.log("UdeC org buildings:", data))
      .catch((error) => console.error("Org buildings API error:", error));

    getAnomalies()
      .then((data) => setApiAnomalies(data))
      .catch((error) => console.error("Anomalies API error:", error));
  }, []);

  const [page, setPage] = useState('dashboard');
  const [role, setRole] = useState('Administrador');
  const activeNodesCount = (apiNodes || []).filter((node) => node.status === "online").length;
  const activeNodesText = `${activeNodesCount} nodo${activeNodesCount === 1 ? "" : "s"} activo${activeNodesCount === 1 ? "" : "s"}`;

  const renderPage = () => {
    switch(page) {
      case 'dashboard': return <PageDashboard apiAnomalies={apiAnomalies}/>;
      case 'campus': return <PageCampus/>;
      case 'buildings': return <PageBuildings/>;
      case 'buildingDetail': return <PageBuildings/>;
      case 'deployments': return <PageDeployments/>;
      case 'live': return <PageLive/>;
      case 'cost': return <PageCost/>;
      case 'ai': return <PageAI apiInsights={apiInsights} apiAnomalies={apiAnomalies}/>;
      case 'mining': return <PageMining/>;
      case 'dataExplorer': return <PageDataExplorer/>;
      case 'reports': return <PageReports/>;
      case 'infra': return <PageInfra/>;
      case 'settings': return <PageSettings role={role} setRole={setRole}/>;
      default: return <PageDashboard apiAnomalies={apiAnomalies}/>;
    }
  };
  return (
    <div style={{display:'flex',minHeight:'100vh'}}>
      <Sidebar page={page} setPage={setPage} role={role} setRole={setRole}/>
      <div style={{marginLeft:230,flex:1,minHeight:'100vh',background:'#0a0a0f'}}>
        <Topbar page={page} activeNodesText={activeNodesText}/>
        <main style={{padding:'24px 28px'}}>
          {renderPage()}
        </main>
      </div>
    </div>
  );
};

export default App;

import PageDataExplorer from "./pages/PageDataExplorer";
import "./claude-app.css";
