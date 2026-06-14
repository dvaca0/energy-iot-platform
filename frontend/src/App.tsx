import { getDashboardSummary, getHourlyCost, getBuildings, getNodes, getAiInsights, createDeployment } from "./services/api";

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
  const normalized = insights.map((ins,i) => typeof ins === 'string'
    ? { priority: i===0?'high':i===1?'medium':'info', category: i===0?'Optimización tarifaria':i===1?'Pronóstico operativo':'Recomendación', building: i===0?'Campus Colima':'Sistema', impact: i===0?'Impacto financiero alto':i===1?'Riesgo de sobrecosto':'Mejora potencial', desc: ins }
    : ins);
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
        <Badge color={PURPLE_L}>AI Engine</Badge>
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
              <div style={{fontSize:12,color:'#22c55e',fontWeight:700,marginBottom:8}}>{ins.impact}</div>
              <p style={{fontSize:12,color:'#a9a2d0',lineHeight:1.55}}>{ins.desc}</p>
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
const Topbar = ({ page }) => {
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
          <span style={{fontSize:11,color:'#22c55e',fontWeight:600}}>2 nodos activos</span>
        </div>
        <div style={{width:32,height:32,borderRadius:'50%',background:'linear-gradient(135deg,#7c5cbf,#4f3d9e)',display:'flex',alignItems:'center',justifyContent:'center',fontSize:13,fontWeight:700,color:'#fff'}}>U</div>
      </div>
    </div>
  );
};

// ─── PAGE: EXECUTIVE DASHBOARD ────────────────────────────────────────────────
const PageDashboard = () => {
  const [dashboardSummary, setDashboardSummary] = useState(null);
  const [hourlyCost, setHourlyCost] = useState(null);

  useEffect(() => {
    getDashboardSummary()
      .then(setDashboardSummary)
      .catch((error) => console.error("Dashboard summary API error:", error));

    getHourlyCost()
      .then((data) => {
        const normalized = data.map((item) => ({
          h: item.hour,
          kwh: item.kwh,
          cost: item.cost_mxn,
          tariff: item.tariff_period === "intermediate" ? "intermedia" : item.tariff_period === "peak" ? "punta" : "base",
        }));
        setHourlyCost(normalized);
      })
      .catch((error) => console.error("Hourly cost API error:", error));
  }, []);

  const mxn = (value) => `$${Number(value || 0).toLocaleString("es-MX")} MXN`;
  const hourlyChartData = hourlyCost || MOCK.hourly;

  const tariffData = [
    { name:'Base', kwh:38.4, cost:1228, pct:21 },
    { name:'Intermedia', kwh:82.1, cost:3362, pct:45 },
    { name:'Punta', kwh:29.5, cost:4288, pct:34 }
  ];
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
            <AreaChart data={MOCK.weeklyTrend} margin={{top:5,right:10,left:-10,bottom:0}}>
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
            {[{b:'FIME',cost:5312,pct:60},{b:'Lab. de Redes',cost:3566,pct:40}].map((d,i) => (
              <div key={i} style={{marginBottom:16}}>
                <div style={{display:'flex',justifyContent:'space-between',marginBottom:6,fontSize:13}}>
                  <span style={{color:'#c4bdf0'}}>{d.b}</span>
                  <span style={{color:'#f0eeff',fontWeight:700}}>${d.cost.toLocaleString()} MXN</span>
                </div>
                <div style={{height:8,background:'#1a1730',borderRadius:4,overflow:'hidden'}}>
                  <div style={{height:'100%',width:`${d.pct}%`,background:`linear-gradient(90deg,${PURPLE},${PURPLE_L})`,borderRadius:4}}/>
                </div>
              </div>
            ))}
            <div style={{background:'#1a1730',borderRadius:10,padding:'12px 14px',marginTop:16}}>
              <div style={{fontSize:11,color:'#6e6694',marginBottom:4}}>6 edificios sin monitoreo</div>
              <div style={{fontSize:13,color:'#9890c4'}}>Asignar nodos para ampliar cobertura</div>
            </div>
          </div>
        </Card>
      </div>
      <AIInsightCard insights={[
        'El periodo de punta representó el 21% del consumo en kWh pero generó el 39% del costo estimado total.',
        'FIME proyecta superar el costo de la semana anterior en un 14% si el patrón actual se mantiene.',
        'Desplazar cargas no críticas fuera del periodo punta podría generar un ahorro estimado de $3,250 MXN/mes.',
        'El factor de potencia de Lab. de Redes (0.89) está por debajo del mínimo recomendado (0.90) y genera penalización tarifaria.'
      ]}/>
    </div>
  );
};

// ─── PAGE: CAMPUS MAP ─────────────────────────────────────────────────────────
const PageCampus = ({ apiBuildings }) => {
  const [selected, setSelected] = useState(null);
  const buildings = apiBuildings || MOCK.buildings;
  return (
    <div>
      <div style={{display:'flex',gap:18,marginBottom:22,flexWrap:'wrap'}}>
        {MOCK.campuses.map((c,i) => (
          <Card key={i} style={{flex:1,minWidth:220,borderColor:c.status==='active'?`${PURPLE}44`:'#1e1b35'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:10}}>
              <div>
                <div style={{fontSize:13,fontWeight:700,color:'#f0eeff'}}>{c.name}</div>
                <div style={{fontSize:11,color:'#6e6694',marginTop:2}}>{c.monitored}/{c.buildings} edificios monitoreados</div>
              </div>
              <Badge color={c.status==='active'?'#22c55e':'#6b7280'}>{c.status==='active'?'Activo':'Inactivo'}</Badge>
            </div>
            {c.status==='active' && <>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8,marginTop:10}}>
                <div style={{background:'#0f0f1a',borderRadius:8,padding:'8px 10px'}}>
                  <div style={{fontSize:10,color:'#6e6694'}}>Potencia</div>
                  <div style={{fontSize:16,fontWeight:700,color:'#f0eeff'}}>{c.power} kW</div>
                </div>
                <div style={{background:'#0f0f1a',borderRadius:8,padding:'8px 10px'}}>
                  <div style={{fontSize:10,color:'#6e6694'}}>Costo/Sem.</div>
                  <div style={{fontSize:16,fontWeight:700,color:PURPLE_L}}>${c.cost_week.toLocaleString()}</div>
                </div>
              </div>
            </>}
          </Card>
        ))}
      </div>
      <div style={{display:'grid',gridTemplateColumns:selected?'1fr 340px':'1fr',gap:18}}>
        <Card>
          <SectionTitle sub="Estado de edificios · Campus Colima">Red de Edificios Inteligentes</SectionTitle>
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(160px,1fr))',gap:12,marginTop:4}}>
            {buildings.map(b => (
              <div key={b.id} onClick={() => setSelected(selected?.id===b.id ? null : b)}
                style={{
                  background:'#0f0f1a', borderRadius:12, padding:'14px',
                  border:`1px solid ${b.status==='normal'?'#22c55e44':b.status==='warning'?'#f59e0b44':b.status==='offline'?'#2a2740':'#ef444444'}`,
                  cursor:'pointer', transition:'all .2s',
                  boxShadow: selected?.id===b.id ? `0 0 16px ${PURPLE}44` : 'none'
                }}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:8}}>
                  <Icon name="Building" size={20} color={PURPLE_L}/>
                  <StatusDot status={b.status==='normal'?'online':b.status==='offline'?'offline':'warning'}/>
                </div>
                <div style={{fontSize:13,fontWeight:700,color:'#f0eeff',marginBottom:2}}>{b.name}</div>
                <div style={{fontSize:11,color:'#6e6694',marginBottom:8}}>{b.campus}</div>
                {b.status!=='offline' ? <>
                  <div style={{fontSize:13,fontWeight:700,color:PURPLE_L}}>{b.power} kW</div>
                  <div style={{fontSize:11,color:'#6e6694'}}>${b.cost_week.toLocaleString()} MXN/sem</div>
                </> : <div style={{fontSize:11,color:'#4b5563'}}>Sin monitoreo</div>}
                {b.anomaly && <div style={{marginTop:6,fontSize:10,background:'#ef444418',color:'#ef4444',borderRadius:20,padding:'2px 8px',display:'inline-block'}}>Anomalía</div>}
              </div>
            ))}
          </div>
        </Card>
        {selected && (
          <Card glow>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:16}}>
              <div>
                <div style={{fontSize:15,fontWeight:700,color:'#f0eeff'}}>{selected.name}</div>
                <div style={{fontSize:12,color:'#6e6694'}}>{selected.faculty}</div>
              </div>
              <button onClick={() => setSelected(null)} style={{background:'none',border:'none',color:'#6e6694',cursor:'pointer'}}><Icon name="X" size={18}/></button>
            </div>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
              {[
                {label:'Campus',value:selected.campus},
                {label:'Estado',value:selected.status},
                {label:'Nodo',value:selected.node||'—'},
                {label:'Última Actualización',value:selected.last_update},
                {label:'Potencia',value:`${selected.power} kW`},
                {label:'Energía/Semana',value:`${selected.energy_week} kWh`},
                {label:'Costo/Semana',value:`$${selected.cost_week.toLocaleString()} MXN`},
                {label:'Costo/Hoy',value:`$${selected.cost_today.toLocaleString()} MXN`}
              ].map((r,i) => (
                <div key={i} style={{background:'#0f0f1a',borderRadius:8,padding:'8px 10px'}}>
                  <div style={{fontSize:10,color:'#6e6694'}}>{r.label}</div>
                  <div style={{fontSize:13,fontWeight:600,color:'#f0eeff',marginTop:2}}>{r.value}</div>
                </div>
              ))}
            </div>
            {selected.anomaly && (
              <div style={{marginTop:14,background:'#ef444418',border:'1px solid #ef444433',borderRadius:10,padding:'10px 12px'}}>
                <div style={{fontSize:12,fontWeight:700,color:'#ef4444',marginBottom:4}}>Anomalía detectada</div>
                <div style={{fontSize:12,color:'#f87171'}}>Se detectó consumo anómalo en las últimas horas. Revisar en monitoreo en vivo.</div>
              </div>
            )}
          </Card>
        )}
      </div>
    </div>
  );
};

// ─── PAGE: BUILDINGS ──────────────────────────────────────────────────────────
const PageBuildings = ({ setPage, apiBuildings }) => {
  const [filter, setFilter] = useState({ campus:'', status:'' });
  const sourceBuildings = apiBuildings || MOCK.buildings;
  const filtered = sourceBuildings.filter(b =>
    (!filter.campus || b.campus === filter.campus) &&
    (!filter.status || b.status === filter.status)
  );
  const campuses = [...new Set(sourceBuildings.map(b => b.campus))];
  return (
    <div>
      <div style={{display:'flex',gap:12,marginBottom:18,flexWrap:'wrap',alignItems:'center'}}>
        <select value={filter.campus} onChange={e => setFilter(f=>({...f,campus:e.target.value}))} style={{width:180}}>
          <option value="">Todos los campus</option>
          {campuses.map(c => <option key={c}>{c}</option>)}
        </select>
        <select value={filter.status} onChange={e => setFilter(f=>({...f,status:e.target.value}))} style={{width:160}}>
          <option value="">Todos los estados</option>
          <option value="normal">Normal</option>
          <option value="warning">Advertencia</option>
          <option value="offline">Sin datos</option>
        </select>
        <div style={{marginLeft:'auto',fontSize:13,color:'#6e6694'}}>{filtered.length} edificios</div>
      </div>
      <Card style={{padding:0,overflow:'hidden'}}>
        <table style={{width:'100%',borderCollapse:'collapse'}}>
          <thead>
            <tr style={{borderBottom:'1px solid #1e1b35'}}>
              {['Edificio','Facultad','Campus','Nodo','Estado','Potencia','Energía/Sem','Costo/Sem','Anomalía'].map(h => (
                <th key={h} style={{padding:'12px 16px',textAlign:'left',fontSize:11,color:'#6e6694',fontWeight:600,textTransform:'uppercase',letterSpacing:.8}}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((b,i) => (
              <tr key={b.id} style={{borderBottom:'1px solid #0f0f1a',transition:'background .15s'}}
                onMouseEnter={e => e.currentTarget.style.background='#10101e'}
                onMouseLeave={e => e.currentTarget.style.background='transparent'}>
                <td style={{padding:'13px 16px',fontSize:13,fontWeight:700,color:'#f0eeff'}}>{b.name}</td>
                <td style={{padding:'13px 16px',fontSize:12,color:'#9890c4'}}>{b.faculty}</td>
                <td style={{padding:'13px 16px',fontSize:12,color:'#9890c4'}}>{b.campus}</td>
                <td style={{padding:'13px 16px'}}>
                  {b.node ? <Badge color="#7c5cbf">{b.node}</Badge> : <span style={{fontSize:12,color:'#4b5563'}}>—</span>}
                </td>
                <td style={{padding:'13px 16px'}}>
                  <div style={{display:'flex',alignItems:'center',gap:5}}>
                    <StatusDot status={b.status==='normal'?'online':b.status==='offline'?'offline':'warning'}/>
                    <span style={{fontSize:12,color:b.status==='normal'?'#22c55e':b.status==='warning'?'#f59e0b':'#6b7280'}}>
                      {b.status==='normal'?'Normal':b.status==='warning'?'Advertencia':'Sin datos'}
                    </span>
                  </div>
                </td>
                <td style={{padding:'13px 16px',fontSize:13,color:'#f0eeff',fontWeight:600}}>{b.power>0?`${b.power} kW`:'—'}</td>
                <td style={{padding:'13px 16px',fontSize:13,color:'#9890c4'}}>{b.energy_week>0?`${b.energy_week} kWh`:'—'}</td>
                <td style={{padding:'13px 16px',fontSize:13,fontWeight:700,color:b.cost_week>0?PURPLE_L:'#4b5563'}}>
                  {b.cost_week>0?`$${b.cost_week.toLocaleString()}`:'—'}
                </td>
                <td style={{padding:'13px 16px'}}>
                  {b.anomaly ? <Badge color="#ef4444">Sí</Badge> : <span style={{fontSize:12,color:'#4b5563'}}>—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
};

// ─── PAGE: BUILDING DETAIL ────────────────────────────────────────────────────
const PageBuildingDetail = ({ building }) => {
  const b = building || MOCK.buildings[0];
  return (
    <div>
      <div style={{display:'flex',gap:14,marginBottom:22,flexWrap:'wrap'}}>
        {[
          {l:'Potencia Actual',v:`${b.power} kW`,c:PURPLE_L},
          {l:'Tensión',v:'228.4 V',c:'#22c55e'},
          {l:'Corriente',v:'18.7 A',c:'#f59e0b'},
          {l:'Factor de Potencia',v:'0.93',c:'#22c55e'},
          {l:'Frecuencia',v:'60.02 Hz',c:'#818cf8'},
          {l:'Costo Hoy',v:`$${b.cost_today.toLocaleString()} MXN`,c:'#ef4444'}
        ].map((s,i) => (
          <div key={i} style={{background:'#10101e',border:'1px solid #1e1b35',borderRadius:12,padding:'14px 18px',flex:1,minWidth:130}}>
            <div style={{fontSize:10,color:'#6e6694',textTransform:'uppercase',letterSpacing:1}}>{s.l}</div>
            <div style={{fontSize:22,fontWeight:700,color:s.c,marginTop:4}}>{s.v}</div>
          </div>
        ))}
      </div>
      <div style={{display:'grid',gridTemplateColumns:'2fr 1fr',gap:18,marginBottom:18}}>
        <Card>
          <SectionTitle sub="Potencia registrada · últimas 24h">Potencia en el Tiempo</SectionTitle>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={MOCK.hourly.map(h => ({...h, power: (h.kwh * 0.9 + Math.random()*0.5).toFixed(2)}))}
              margin={{top:5,right:10,left:-10,bottom:0}}>
              <defs><linearGradient id="gp" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#22c55e" stopOpacity={0.4}/>
                <stop offset="95%" stopColor="#22c55e" stopOpacity={0}/>
              </linearGradient></defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID}/>
              <XAxis dataKey="h" tick={{fontSize:10,fill:'#6e6694'}} interval={3}/>
              <YAxis tick={{fontSize:10,fill:'#6e6694'}}/>
              <Tooltip content={<CustomTooltip suffix=" kW"/>}/>
              <Area type="monotone" dataKey="power" name="Potencia" stroke="#22c55e" fill="url(#gp)" strokeWidth={2}/>
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card>
          <SectionTitle sub="Perfil del edificio">Información</SectionTitle>
          {[
            {l:'Edificio', v:b.name},{l:'Facultad',v:b.faculty},{l:'Campus',v:b.campus},
            {l:'Nodo Asignado',v:b.node||'—'},{l:'Panel',v:'Tablero Principal'},
            {l:'Despliegue',v:'06/01 – 13/01/2025'},{l:'Energía/Semana',v:`${b.energy_week} kWh`}
          ].map((r,i) => (
            <div key={i} style={{display:'flex',justifyContent:'space-between',padding:'7px 0',borderBottom:'1px solid #0f0f1a',fontSize:12}}>
              <span style={{color:'#6e6694'}}>{r.l}</span>
              <span style={{color:'#f0eeff',fontWeight:600}}>{r.v}</span>
            </div>
          ))}
        </Card>
      </div>
      <AIInsightCard insights={[
        `${b.name} consume el 60% de la energía total monitoreada del campus esta semana.`,
        'El periodo punta genera el 41% del costo diario estimado con solo el 25% del tiempo operativo.',
        'Se detectó una reducción del 12% en el consumo base vs. semana anterior — posible mejora en eficiencia.'
      ]}/>
    </div>
  );
};

// ─── PAGE: DEPLOYMENTS ────────────────────────────────────────────────────────
const PageDeployments = ({ apiNodes }) => {
  const [form, setForm] = useState({ node:'N001', campus:'Colima', faculty:'', building:'', panel:'', start:'', end:'', notes:'' });
  const [saved, setSaved] = useState(false);
  const handleSave = async () => {
    try {
      await createDeployment({
        node_id: form.node,
        campus: form.campus,
        faculty: form.faculty,
        building_name: form.building,
        electrical_panel: form.panel,
        start_date: form.start,
        end_date: form.end,
        notes: form.notes,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (error) {
      console.error("Create deployment API error:", error);
      alert("No se pudo guardar el despliegue. Revisa que el backend esté corriendo.");
    }
  };
  return (
    <div style={{display:'grid',gridTemplateColumns:'1fr 1.4fr',gap:18}}>
      <div>
        <SectionTitle sub="Estado actual de los nodos de campo">Nodos Disponibles</SectionTitle>
        {(apiNodes || MOCK.nodes).map(n => (
          <Card key={n.id} style={{marginBottom:12,borderColor:n.status==='online'?'#22c55e33':'#1e1b35'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:12}}>
              <div style={{display:'flex',alignItems:'center',gap:10}}>
                <div style={{background:'#22c55e18',border:'1px solid #22c55e33',borderRadius:8,padding:10,color:'#22c55e'}}><Icon name="Cpu" size={18}/></div>
                <div>
                  <div style={{fontSize:14,fontWeight:700,color:'#f0eeff'}}>{n.name}</div>
                  <div style={{fontSize:11,color:'#6e6694'}}>{n.ip} · v{n.fw}</div>
                </div>
              </div>
              <Badge color="#22c55e">Online</Badge>
            </div>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
              {[
                {l:'Edificio',v:n.building},{l:'Última Sincronía',v:n.last_sync},
                {l:'Muestras',v:n.samples.toLocaleString()},{l:'Buffer',v:`${n.buffer} reg. pend.`},
                {l:'RPi',v:n.rpi_status==='ok'?'OK':'Warning'},{l:'Shelly',v:n.shelly_status==='ok'?'OK':'Warning'}
              ].map((r,i) => (
                <div key={i} style={{background:'#0f0f1a',borderRadius:8,padding:'7px 10px'}}>
                  <div style={{fontSize:10,color:'#6e6694'}}>{r.l}</div>
                  <div style={{fontSize:12,fontWeight:600,color:'#f0eeff',marginTop:2}}>{r.v}</div>
                </div>
              ))}
            </div>
          </Card>
        ))}
        <SectionTitle sub="Historial de despliegues" style={{marginTop:20}}>Despliegues Pasados</SectionTitle>
        {MOCK.deployments.filter(d=>d.status==='completed').map(d => (
          <Card key={d.id} style={{marginBottom:10}}>
            <div style={{display:'flex',justifyContent:'space-between',marginBottom:6}}>
              <span style={{fontSize:13,fontWeight:700,color:'#f0eeff'}}>{d.building}</span>
              <Badge color="#22c55e">Completado</Badge>
            </div>
            <div style={{fontSize:12,color:'#6e6694'}}>{d.node} · {d.start} – {d.end}</div>
            <div style={{fontSize:12,color:'#9890c4',marginTop:4}}>{d.completeness}% completitud · {d.samples.toLocaleString()} muestras</div>
          </Card>
        ))}
      </div>
      <div>
        <SectionTitle sub="Despliegues activos actualmente">En Curso</SectionTitle>
        {MOCK.deployments.filter(d=>d.status==='active').map(d => (
          <Card key={d.id} style={{marginBottom:14,borderColor:`${PURPLE}44`}} glow>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:12}}>
              <div>
                <div style={{fontSize:14,fontWeight:700,color:'#f0eeff'}}>{d.building}</div>
                <div style={{fontSize:11,color:'#6e6694'}}>{d.node} · {d.panel}</div>
              </div>
              <Badge color={PURPLE_L}>Activo</Badge>
            </div>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:8,marginBottom:12}}>
              {[{l:'Técnico',v:d.tech},{l:'Inicio',v:d.start},{l:'Fin',v:d.end}].map((r,i) => (
                <div key={i} style={{background:'#0f0f1a',borderRadius:8,padding:'7px 10px'}}>
                  <div style={{fontSize:10,color:'#6e6694'}}>{r.l}</div>
                  <div style={{fontSize:12,fontWeight:600,color:'#f0eeff',marginTop:2}}>{r.v}</div>
                </div>
              ))}
            </div>
            <div style={{marginBottom:8}}>
              <div style={{display:'flex',justifyContent:'space-between',fontSize:12,color:'#6e6694',marginBottom:4}}>
                <span>Progreso del despliegue</span>
                <span style={{color:PURPLE_L,fontWeight:700}}>{d.progress}%</span>
              </div>
              <div style={{height:8,background:'#1a1730',borderRadius:4,overflow:'hidden'}}>
                <div style={{height:'100%',width:`${d.progress}%`,background:`linear-gradient(90deg,${PURPLE},${PURPLE_L})`,borderRadius:4}}/>
              </div>
            </div>
            <div style={{display:'flex',justifyContent:'space-between',fontSize:12,marginTop:8}}>
              <span style={{color:'#6e6694'}}>Completitud de datos: <strong style={{color:'#22c55e'}}>{d.completeness}%</strong></span>
              <span style={{color:'#6e6694'}}>{d.samples.toLocaleString()} muestras · {d.buffer} buffer</span>
            </div>
            {d.notes && <div style={{marginTop:10,background:'#1a1730',borderRadius:8,padding:'8px 10px',fontSize:11,color:'#9890c4'}}>{d.notes}</div>}
          </Card>
        ))}
        <Card style={{borderColor:`${PURPLE}44`}}>
          <SectionTitle sub="Asignar nodo a edificio para nuevo despliegue">Asignar Nodo</SectionTitle>
          {saved && <div style={{background:'#22c55e18',border:'1px solid #22c55e33',borderRadius:10,padding:'10px 14px',marginBottom:14,fontSize:13,color:'#22c55e'}}>Despliegue registrado correctamente</div>}
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
            {[
              {l:'Nodo',f:'node',el:'select',opts:['N001','N002']},
              {l:'Campus',f:'campus',el:'select',opts:['Colima','Coquimatlán','Tecomán']},
              {l:'Facultad',f:'faculty',el:'input'},
              {l:'Edificio',f:'building',el:'input'},
              {l:'Panel Eléctrico',f:'panel',el:'input'},
              {l:'Fecha Inicio',f:'start',el:'date'},
              {l:'Fecha Fin',f:'end',el:'date'}
            ].map(field => (
              <div key={field.f} style={{display:'flex',flexDirection:'column',gap:5}}>
                <label style={{fontSize:11,color:'#6e6694',textTransform:'uppercase',letterSpacing:.8}}>{field.l}</label>
                {field.el==='select' ? (
                  <select value={form[field.f]} onChange={e => setForm(f=>({...f,[field.f]:e.target.value}))}>
                    {field.opts.map(o => <option key={o}>{o}</option>)}
                  </select>
                ) : (
                  <input type={field.el||'text'} value={form[field.f]} onChange={e => setForm(f=>({...f,[field.f]:e.target.value}))} placeholder={field.l}/>
                )}
              </div>
            ))}
          </div>
          <div style={{marginTop:12}}>
            <label style={{fontSize:11,color:'#6e6694',textTransform:'uppercase',letterSpacing:.8}}>Notas del Técnico</label>
            <textarea rows={3} value={form.notes} onChange={e => setForm(f=>({...f,notes:e.target.value}))} style={{width:'100%',marginTop:5,resize:'none'}} placeholder="Observaciones de instalación..."/>
          </div>
          <button onClick={handleSave} style={{
            marginTop:14, width:'100%', padding:'11px',
            background:`linear-gradient(135deg,${PURPLE},#4f3d9e)`, border:'none',
            borderRadius:10, color:'#fff', fontWeight:700, fontSize:14, cursor:'pointer'
          }}>Guardar Despliegue</button>
        </Card>
      </div>
    </div>
  );
};

// ─── PAGE: LIVE MONITORING ────────────────────────────────────────────────────
const PageLive = ({ apiNodes }) => {
  const [tick, setTick] = useState(0);
  useEffect(() => { const t = setInterval(() => setTick(x => x+1), 3000); return () => clearInterval(t); }, []);
  const jitter = (v, pct=0.02) => +(v * (1 + (Math.random()-0.5)*pct)).toFixed(2);
  return (
    <div>
      <div style={{display:'flex',gap:12,marginBottom:18,alignItems:'center'}}>
        <div style={{display:'flex',alignItems:'center',gap:8,background:'#22c55e18',border:'1px solid #22c55e33',borderRadius:20,padding:'5px 14px'}}>
          <div style={{width:8,height:8,borderRadius:'50%',background:'#22c55e',animation:'pulse 2s infinite'}}/>
          <span style={{fontSize:12,color:'#22c55e',fontWeight:600}}>EN VIVO</span>
        </div>
        <span style={{fontSize:12,color:'#6e6694'}}>Actualización cada 3s · Datos en tiempo real</span>
      </div>
      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}`}</style>
      {(apiNodes || MOCK.nodes).map(n => (
        <Card key={n.id} style={{marginBottom:18}} glow>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
            <div style={{display:'flex',alignItems:'center',gap:12}}>
              <div style={{background:'#22c55e18',border:'1px solid #22c55e33',borderRadius:10,padding:10,color:'#22c55e'}}><Icon name="Cpu" size={20}/></div>
              <div>
                <div style={{fontSize:15,fontWeight:700,color:'#f0eeff'}}>{n.name}</div>
                <div style={{fontSize:11,color:'#6e6694'}}>{n.ip} · {n.building} · {n.last_sync}</div>
              </div>
            </div>
            <Badge color="#22c55e">Online</Badge>
          </div>
          <div style={{display:'flex',flexWrap:'wrap',gap:12}}>
            {[
              {l:'Tensión (V)',v:jitter(n.voltage,0.01).toFixed(1),c:'#818cf8',unit:'V'},
              {l:'Corriente (A)',v:jitter(n.current,0.03).toFixed(2),c:'#f59e0b',unit:'A'},
              {l:'Potencia (kW)',v:jitter(n.power,0.03).toFixed(3),c:'#ef4444',unit:'kW'},
              {l:'Factor de Potencia',v:jitter(n.pf,0.01).toFixed(3),c:'#22c55e',unit:''},
              {l:'Frecuencia (Hz)',v:jitter(n.freq,0.005).toFixed(2),c:'#a78bfa',unit:'Hz'},
              {l:'Energía Hoy',v:n.energy_today,c:PURPLE_L,unit:'kWh'}
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
            {[{l:'RPi Status',v:'OK',c:'#22c55e'},{l:'Shelly Status',v:'OK',c:'#22c55e'},{l:'Buffer',v:`${n.buffer} pend.`,c:n.buffer>0?'#f59e0b':'#22c55e'}].map((s,i) => (
              <div key={i} style={{background:'#0a0a14',borderRadius:8,padding:'8px 12px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                <span style={{fontSize:11,color:'#6e6694'}}>{s.l}</span>
                <span style={{fontSize:12,fontWeight:700,color:s.c}}>{s.v}</span>
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
  const [peakReduce, setPeakReduce] = useState(20);
  const baseSavings = Math.round((peakReduce / 100) * 4288);
  const tariffBreakdown = [
    {name:'Base',kwh:38.4,cost:1228,rate:31.98,pct:14},
    {name:'Intermedia',kwh:82.1,cost:3362,rate:40.95,pct:38},
    {name:'Punta',kwh:29.5,cost:4288,rate:145.36,pct:48}
  ];
  return (
    <div>
      <div style={{display:'flex',flexWrap:'wrap',gap:14,marginBottom:22}}>
        <StatCard label="Costo Hoy" value="$1,373 MXN" sub="Estimado GDMTH" color="#ef4444" icon="Wallet"/>
        <StatCard label="Costo Esta Semana" value="$8,878 MXN" sub="Lun–Vie actual" color="#f59e0b" icon="Calendar" trend={12}/>
        <StatCard label="Proyección Mensual" value="$38,400 MXN" sub="Enero 2025" color={PURPLE_L} icon="TrendingUp"/>
        <StatCard label="Costo por Punta" value="48% del total" sub="Solo 23% del tiempo" color="#ef4444" icon="Bolt"/>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'2fr 1fr',gap:18,marginBottom:18}}>
        <Card>
          <SectionTitle sub="Desglose detallado por periodo tarifario GDMTH">Análisis por Periodo Tarifario</SectionTitle>
          {tariffBreakdown.map((t,i) => (
            <div key={i} style={{marginBottom:16}}>
              <div style={{display:'flex',justifyContent:'space-between',marginBottom:6}}>
                <div style={{display:'flex',alignItems:'center',gap:10}}>
                  <span style={{width:10,height:10,borderRadius:2,background:Object.values(TARIFF_COLORS)[i],display:'inline-block'}}/>
                  <span style={{fontSize:14,fontWeight:700,color:'#f0eeff'}}>{t.name}</span>
                </div>
                <div style={{textAlign:'right'}}>
                  <span style={{fontSize:15,fontWeight:700,color:Object.values(TARIFF_COLORS)[i]}}>${t.cost.toLocaleString()} MXN</span>
                  <span style={{fontSize:11,color:'#6e6694',marginLeft:8}}>{t.kwh} kWh</span>
                </div>
              </div>
              <div style={{height:8,background:'#1a1730',borderRadius:4,overflow:'hidden',marginBottom:4}}>
                <div style={{height:'100%',width:`${t.pct}%`,background:Object.values(TARIFF_COLORS)[i],borderRadius:4,opacity:.8}}/>
              </div>
              <div style={{display:'flex',justifyContent:'space-between',fontSize:11,color:'#6e6694'}}>
                <span>{t.pct}% del costo total</span>
                <span>Tarifa: ${t.rate}/kWh</span>
              </div>
            </div>
          ))}
        </Card>
        <div>
          <Card style={{marginBottom:14}}>
            <SectionTitle sub="Fuente: CFE">Tarifa Activa</SectionTitle>
            <div style={{background:'#0f0f1a',borderRadius:10,padding:'14px'}}>
              <div style={{fontSize:20,fontWeight:800,color:PURPLE_L}}>GDMTH</div>
              <div style={{fontSize:11,color:'#6e6694',marginTop:2}}>Gran Demanda en Media Tensión H</div>
            </div>
            {[{l:'Cargo Base',v:'$31.98/kWh'},{l:'Cargo Intermedia',v:'$40.95/kWh'},{l:'Cargo Punta',v:'$145.36/kWh'},{l:'Última actualización',v:'Ene 2025'},{l:'Estado CFE API',v:'Manual (fallback)'}].map((r,i) => (
              <div key={i} style={{display:'flex',justifyContent:'space-between',padding:'6px 0',borderBottom:'1px solid #0f0f1a',fontSize:12}}>
                <span style={{color:'#6e6694'}}>{r.l}</span>
                <span style={{color:'#f0eeff',fontWeight:600}}>{r.v}</span>
              </div>
            ))}
          </Card>
        </div>
      </div>
      <Card>
        <SectionTitle sub="Simulador interactivo de ahorro energético">Simulador de Ahorro</SectionTitle>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:24}}>
          <div>
            <div style={{marginBottom:20}}>
              <div style={{display:'flex',justifyContent:'space-between',marginBottom:8,fontSize:13}}>
                <label style={{color:'#c4bdf0'}}>Reducir consumo en punta</label>
                <span style={{color:PURPLE_L,fontWeight:700}}>{peakReduce}%</span>
              </div>
              <input type="range" min={0} max={80} step={5} value={peakReduce}
                onChange={e => setPeakReduce(+e.target.value)}
                style={{width:'100%',accentColor:PURPLE_L}}/>
            </div>
            <div style={{background:'#22c55e18',border:'1px solid #22c55e33',borderRadius:12,padding:'16px 20px'}}>
              <div style={{fontSize:12,color:'#6e6694',marginBottom:4}}>Ahorro estimado mensual</div>
              <div style={{fontSize:32,fontWeight:800,color:'#22c55e'}}>${(baseSavings * 4.3).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g,',')} MXN</div>
              <div style={{fontSize:12,color:'#6e6694',marginTop:4}}>Reduciendo {peakReduce}% de carga en periodo punta</div>
            </div>
          </div>
          <div>
            <div style={{background:'#1a1730',borderRadius:12,padding:'16px'}}>
              <div style={{fontSize:13,fontWeight:700,color:'#f0eeff',marginBottom:14}}>Distribución actual vs optimizada</div>
              {tariffBreakdown.map((t,i) => {
                const newCost = i===2 ? Math.round(t.cost * (1 - peakReduce/100)) : t.cost;
                return (
                  <div key={i} style={{marginBottom:12}}>
                    <div style={{display:'flex',justifyContent:'space-between',fontSize:12,marginBottom:4}}>
                      <span style={{color:'#9890c4'}}>{t.name}</span>
                      <span style={{color:'#f0eeff'}}>${newCost.toLocaleString()} <span style={{color:'#22c55e',fontSize:11}}>{i===2?`(-${peakReduce}%)`:''}</span></span>
                    </div>
                    <div style={{height:6,background:'#0f0f1a',borderRadius:3,overflow:'hidden'}}>
                      <div style={{height:'100%',width:`${Math.round(newCost/8878*100)}%`,background:Object.values(TARIFF_COLORS)[i],opacity:.8,borderRadius:3}}/>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
};

// ─── PAGE: AI CENTER ──────────────────────────────────────────────────────────
const PageAI = ({ apiInsights }) => {
  const [tab, setTab] = useState('forecast');
  const [chat, setChat] = useState(MOCK.chatHistory);
  const [input, setInput] = useState('');
  const chatEndRef = useRef(null);
  const sendMsg = () => {
    if (!input.trim()) return;
    const userMsg = { role:'user', msg: input };
    const key = Object.keys(MOCK.chatResponses).find(k => input.toLowerCase().includes(k)) || 'default';
    const botMsg = { role:'assistant', msg: MOCK.chatResponses[key] };
    setChat(c => [...c, userMsg, botMsg]);
    setInput('');
    setTimeout(() => chatEndRef.current?.scrollIntoView({behavior:'smooth'}), 100);
  };
  const tabs = [{id:'forecast',label:'Pronóstico'},{id:'anomalies',label:'Anomalías'},{id:'recommendations',label:'Recomendaciones'},{id:'chat',label:'Asistente IA'}];
  return (
    <div>
      <div style={{display:'flex',gap:4,marginBottom:20,background:'#0f0f1a',borderRadius:12,padding:4,width:'fit-content'}}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding:'8px 18px', borderRadius:9, border:'none', cursor:'pointer',
            background: tab===t.id ? '#7c5cbf' : 'transparent',
            color: tab===t.id ? '#fff' : '#6e6694', fontWeight:600, fontSize:13
          }}>{t.label}</button>
        ))}
      </div>
      {tab==='forecast' && (
        <div>
          <div style={{display:'flex',gap:14,marginBottom:18,flexWrap:'wrap'}}>
            <StatCard label="Proyección Mañana" value="$1,520 MXN" sub="±$180 intervalo" color="#818cf8" icon="ArrowRight"/>
            <StatCard label="Proyección Semana" value="$9,400 MXN" sub="±8% confianza" color={PURPLE_L} icon="BarChart"/>
            <StatCard label="Proyección Mensual" value="$38,400 MXN" sub="Tendencia creciente" color="#f59e0b" icon="TrendingUp"/>
          </div>
          <Card>
            <SectionTitle sub="Consumo real vs predicción del modelo · intervalo de confianza 90%">Pronóstico de Costo (MXN)</SectionTitle>
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={MOCK.forecast} margin={{top:5,right:20,left:-10,bottom:0}}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID}/>
                <XAxis dataKey="day" tick={{fontSize:11,fill:'#6e6694'}}/>
                <YAxis tick={{fontSize:10,fill:'#6e6694'}}/>
                <Tooltip content={<CustomTooltip prefix="$" suffix=" MXN"/>}/>
                <Area type="monotone" dataKey="upper" stroke="none" fill="#7c5cbf22" legendType="none"/>
                <Area type="monotone" dataKey="lower" stroke="none" fill="#0a0a0f" legendType="none"/>
                <Line type="monotone" dataKey="actual" name="Real" stroke="#22c55e" strokeWidth={2} dot={{fill:'#22c55e',r:4}} connectNulls={false}/>
                <Line type="monotone" dataKey="pred" name="Predicción" stroke={PURPLE_L} strokeWidth={2} strokeDasharray="6 3" dot={{fill:PURPLE_L,r:4}}/>
              </ComposedChart>
            </ResponsiveContainer>
          </Card>
        </div>
      )}
      {tab==='anomalies' && (
        <div>
          <div style={{display:'flex',gap:14,marginBottom:18}}>
            <StatCard label="Anomalías Hoy" value="3" sub="2 activas" color="#ef4444" icon="Alert"/>
            <StatCard label="Anomalías Esta Semana" value="7" sub="Revisadas: 4" color="#f59e0b" icon="FileText"/>
          </div>
          {MOCK.anomalies.map(a => (
            <Card key={a.id} style={{marginBottom:12,borderLeft:`4px solid ${a.severity==='critical'?'#ef4444':a.severity==='warning'?'#f59e0b':'#818cf8'}`,borderRadius:'0 12px 12px 0',paddingLeft:20}}>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:8}}>
                <div>
                  <div style={{fontSize:14,fontWeight:700,color:'#f0eeff'}}>{a.type}</div>
                  <div style={{fontSize:11,color:'#6e6694',marginTop:2}}>{a.building} · {a.time}</div>
                </div>
                <Badge color={a.severity==='critical'?'#ef4444':a.severity==='warning'?'#f59e0b':'#818cf8'}>
                  {a.severity==='critical'?'Crítico':a.severity==='warning'?'Advertencia':'Info'}
                </Badge>
              </div>
              <div style={{display:'flex',gap:16,fontSize:12}}>
                <span style={{color:'#6e6694'}}>Detectado: <strong style={{color:'#ef4444'}}>{a.value}</strong></span>
                <span style={{color:'#6e6694'}}>Esperado: <strong style={{color:'#22c55e'}}>{a.expected}</strong></span>
              </div>
            </Card>
          ))}
        </div>
      )}
      {tab==='recommendations' && (
        <div>
          {MOCK.recommendations.map(r => (
            <Card key={r.id} style={{marginBottom:14}} glow>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:10}}>
                <div>
                  <Badge color={r.priority==='alta'?'#ef4444':'#f59e0b'} style={{marginBottom:8}}>
                    {r.priority==='alta'?'Alta prioridad':'Prioridad media'}
                  </Badge>
                  <div style={{fontSize:15,fontWeight:700,color:'#f0eeff',marginTop:8}}>{r.title}</div>
                  <div style={{fontSize:12,color:'#6e6694',marginTop:3}}>{r.building}</div>
                </div>
                <div style={{textAlign:'right'}}>
                  <div style={{fontSize:10,color:'#6e6694'}}>Ahorro estimado</div>
                  <div style={{fontSize:22,fontWeight:800,color:'#22c55e'}}>${r.savings.toLocaleString()}</div>
                  <div style={{fontSize:10,color:'#6e6694'}}>MXN/mes</div>
                </div>
              </div>
              <p style={{fontSize:13,color:'#9890c4',lineHeight:1.6,marginBottom:10}}>{r.desc}</p>
              <div style={{background:'#1a1730',borderRadius:8,padding:'8px 12px',fontSize:12,color:PURPLE_L,display:'flex',alignItems:'center',gap:8}}><Icon name="ArrowRight" size={13}/>{r.action}</div>
            </Card>
          ))}
        </div>
      )}
      {tab==='chat' && (
        <Card style={{height:520,display:'flex',flexDirection:'column'}}>
          <div style={{flex:1,overflowY:'auto',padding:'4px 0',marginBottom:14}}>
            {chat.map((m,i) => (
              <div key={i} style={{marginBottom:14,display:'flex',gap:10,alignItems:'flex-start',flexDirection:m.role==='user'?'row-reverse':'row'}}>
                <div style={{width:32,height:32,borderRadius:'50%',background:m.role==='user'?'#7c5cbf22':'#1a1730',display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0,fontSize:14}}>
                  <Icon name={m.role==='user'?'User':'Bot'} size={16} color={m.role==='user'?PURPLE_L:'#9890c4'}/>
                </div>
                <div style={{
                  background:m.role==='user'?'#7c5cbf22':'#0f0f1a',
                  border:`1px solid ${m.role==='user'?`${PURPLE}44`:'#1e1b35'}`,
                  borderRadius:12, padding:'10px 14px', maxWidth:'75%',
                  fontSize:13, color:'#c4bdf0', lineHeight:1.6
                }}>{m.msg}</div>
              </div>
            ))}
            <div ref={chatEndRef}/>
          </div>
          <div style={{display:'flex',gap:10}}>
            <input value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key==='Enter' && sendMsg()}
              placeholder="Pregunta sobre costos, anomalías, ahorro…" style={{flex:1}}/>
            <button onClick={sendMsg} style={{
              padding:'0 20px', background:`linear-gradient(135deg,${PURPLE},#4f3d9e)`,
              border:'none', borderRadius:10, color:'#fff', fontWeight:700, cursor:'pointer'
            }}>Enviar</button>
          </div>
          <div style={{marginTop:10,display:'flex',flexWrap:'wrap',gap:6}}>
            {['¿Qué edificio costó más esta semana?','¿Cuánto podemos ahorrar en punta?','¿Hubo anomalías hoy?','Proyección de costo del mes'].map(q => (
              <button key={q} onClick={() => { setInput(q); }} style={{
                padding:'4px 12px', background:'#1a1730', border:'1px solid #2a2740',
                borderRadius:20, color:'#9890c4', fontSize:11, cursor:'pointer'
              }}>{q}</button>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
};

// ─── PAGE: DATA MINING ────────────────────────────────────────────────────────
const PageMining = () => {
  const clusters = [
    {name:'Carga Constante',buildings:['Data Center','Lab. Redes'],color:'#818cf8',desc:'Consumo uniforme 24/7, alta correlación temporal'},
    {name:'Horario Administrativo',buildings:['Rectoría','Biblioteca'],color:'#22c55e',desc:'Picos 08:00–17:00, consumo mínimo nocturno'},
    {name:'Alta Demanda Académica',buildings:['FIME','Lab. Química'],color:'#ef4444',desc:'Picos en periodos de clases, alta varianza'},
    {name:'Uso Mixto',buildings:['Fac. Ingeniería','C. Cómputo'],color:'#f59e0b',desc:'Patrón híbrido sin correlación clara'}
  ];
  const correlationData = MOCK.weeklyTrend.map((d,i) => ({...d, fime: d.cost, redes: Math.round(d.cost*0.67)}));
  return (
    <div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:18,marginBottom:18}}>
        <Card>
          <SectionTitle sub="K-Means clustering de comportamiento de consumo">Clustering de Edificios</SectionTitle>
          <div style={{display:'flex',flexDirection:'column',gap:12,marginTop:4}}>
            {clusters.map((c,i) => (
              <div key={i} style={{background:'#0f0f1a',borderRadius:12,padding:'14px',borderLeft:`4px solid ${c.color}`}}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:6}}>
                  <div style={{fontSize:13,fontWeight:700,color:'#f0eeff'}}>{c.name}</div>
                  <Badge color={c.color}>{c.buildings.length} edificios</Badge>
                </div>
                <div style={{fontSize:11,color:'#6e6694',marginBottom:6}}>{c.desc}</div>
                <div style={{display:'flex',gap:6,flexWrap:'wrap'}}>
                  {c.buildings.map(b => <Badge key={b} color={c.color}>{b}</Badge>)}
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <SectionTitle sub="Correlación de consumo entre edificios monitoreados">Correlación FIME vs Lab. Redes</SectionTitle>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={correlationData} margin={{top:5,right:10,left:-10,bottom:0}}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID}/>
              <XAxis dataKey="day" tick={{fontSize:10,fill:'#6e6694'}}/>
              <YAxis tick={{fontSize:10,fill:'#6e6694'}}/>
              <Tooltip content={<CustomTooltip prefix="$" suffix=" MXN"/>}/>
              <Line dataKey="fime" name="FIME" stroke={PURPLE_L} strokeWidth={2} dot={{r:3}}/>
              <Line dataKey="redes" name="Lab. Redes" stroke="#22c55e" strokeWidth={2} dot={{r:3}} strokeDasharray="4 2"/>
            </LineChart>
          </ResponsiveContainer>
          <div style={{background:'#0f0f1a',borderRadius:10,padding:'10px 14px',marginTop:10}}>
            <div style={{fontSize:12,color:'#9890c4'}}>Coeficiente de correlación Pearson: <strong style={{color:PURPLE_L}}>0.87</strong> — Alta correlación positiva</div>
          </div>
        </Card>
      </div>
      <Card style={{marginBottom:18}}>
        <SectionTitle sub="Patrones descubiertos por el motor de minería de datos">Descubrimiento de Patrones</SectionTitle>
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(220px,1fr))',gap:12}}>
          {[
            {icon:'Activity',title:'Baseload Nocturno Anómalo',building:'Lab. de Redes',detail:'2.4 kW detectados entre 02:00–05:00 vs. esperado 0.8 kW',severity:'warning'},
            {icon:'BarChart',title:'Carga Constante',building:'Data Center',detail:'Desviación estándar < 0.3 kW en 72h. Patrón de carga base estable.',severity:'info'},
            {icon:'Calendar',title:'Alta Dependencia Laboral',building:'FIME',detail:'Ratio lunes-viernes/fin de semana = 4.8x. Correlación académica.',severity:'info'},
            {icon:'TrendingUp',title:'Tendencia Creciente',building:'FIME',detail:'Incremento del 14% semana sobre semana. Proyección supera límite.',severity:'warning'}
          ].map((p,i) => (
            <div key={i} style={{background:'#0f0f1a',borderRadius:12,padding:'14px',border:`1px solid ${p.severity==='warning'?'#f59e0b33':'#1e1b35'}`}}>
              <div style={{width:34,height:34,borderRadius:9,background:p.severity==='warning'?'#f59e0b18':'#7c5cbf18',border:`1px solid ${p.severity==='warning'?'#f59e0b33':'#7c5cbf33'}`,display:'flex',alignItems:'center',justifyContent:'center',marginBottom:10,color:p.severity==='warning'?'#f59e0b':PURPLE_L}}><Icon name={p.icon} size={17}/></div>
              <div style={{fontSize:13,fontWeight:700,color:'#f0eeff',marginBottom:4}}>{p.title}</div>
              <div style={{fontSize:11,color:PURPLE_L,marginBottom:6}}>{p.building}</div>
              <div style={{fontSize:11,color:'#6e6694',lineHeight:1.5}}>{p.detail}</div>
            </div>
          ))}
        </div>
      </Card>
      <AIInsightCard insights={[
        '"Data Center" presenta firma de carga constante — comportamiento 24/7 sin variación significativa.',
        '"FIME" y "Lab. de Redes" muestran correlación de Pearson 0.87 — patrones de uso académico similares.',
        'Los edificios administrativos presentan alta dependencia laboral con ratio semana/fin de semana de 4.8x.',
        'El baseload nocturno en Lab. de Redes es 3x superior al esperado — posible equipo encendido innecesariamente.'
      ]}/>
    </div>
  );
};

// ─── PAGE: REPORTS ────────────────────────────────────────────────────────────
const PageReports = () => {
  const reports = [
    {title:'Resumen Semanal de Costo',type:'Ejecutivo',date:'13 Ene 2025',icon:'Wallet',status:'Disponible'},
    {title:'Comparación de Edificios',type:'Técnico',date:'13 Ene 2025',icon:'Building',status:'Disponible'},
    {title:'Reporte de Anomalías IA',type:'IA',date:'13 Ene 2025',icon:'Alert',status:'Disponible'},
    {title:'Reporte de Despliegue de Nodos',type:'Técnico',date:'13 Ene 2025',icon:'Cpu',status:'Disponible'},
    {title:'Reporte de Sostenibilidad',type:'Ejecutivo',date:'Ene 2025',icon:'Leaf',status:'En preparación'},
    {title:'Dataset Completo CSV',type:'Datos',date:'13 Ene 2025',icon:'BarChart',status:'Disponible'}
  ];
  return (
    <div>
      <div style={{display:'flex',gap:14,marginBottom:22,flexWrap:'wrap'}}>
        {['PDF','CSV','Excel'].map(fmt => (
          <button key={fmt} style={{
            padding:'10px 24px', background:`linear-gradient(135deg,${PURPLE},#4f3d9e)`,
            border:'none', borderRadius:10, color:'#fff', fontWeight:700, fontSize:14, cursor:'pointer'
          }}>Exportar {fmt}</button>
        ))}
      </div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(280px,1fr))',gap:14}}>
        {reports.map((r,i) => (
          <Card key={i} style={{cursor:'pointer'}} glow={r.status==='Disponible'}>
            <div style={{display:'flex',gap:12,marginBottom:12}}>
              <div style={{width:42,height:42,borderRadius:11,background:'#7c5cbf18',border:'1px solid #7c5cbf33',display:'flex',alignItems:'center',justifyContent:'center',color:PURPLE_L}}><Icon name={r.icon} size={20}/></div>
              <div style={{flex:1}}>
                <div style={{fontSize:14,fontWeight:700,color:'#f0eeff'}}>{r.title}</div>
                <div style={{fontSize:11,color:'#6e6694',marginTop:2}}>{r.type} · {r.date}</div>
              </div>
            </div>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
              <Badge color={r.status==='Disponible'?'#22c55e':'#f59e0b'}>{r.status}</Badge>
              {r.status==='Disponible' && (
                <button style={{background:'none',border:`1px solid ${PURPLE}44`,borderRadius:8,padding:'5px 14px',color:PURPLE_L,fontSize:12,cursor:'pointer'}}>Descargar</button>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};

// ─── PAGE: INFRASTRUCTURE ─────────────────────────────────────────────────────
const PageInfra = () => {
  const services = [
    {name:'API Backend (FastAPI)',status:'mock',latency:'—',icon:'Plug'},
    {name:'Base de Datos SQLite (Edge)',status:'ok',latency:'2ms',icon:'Database'},
    {name:'Servicio de Sincronía',status:'ok',latency:'—',icon:'Sync'},
    {name:'Tailscale VPN',status:'ok',latency:'14ms',icon:'Lock'},
    {name:'Raspberry Pi — Node 001',status:'ok',latency:'8ms',icon:'Monitor'},
    {name:'Raspberry Pi — Node 002',status:'ok',latency:'11ms',icon:'Monitor'},
    {name:'Shelly Pro — Node 001',status:'ok',latency:'3ms',icon:'Bolt'},
    {name:'Shelly Pro — Node 002',status:'ok',latency:'5ms',icon:'Bolt'}
  ];
  return (
    <div>
      <div style={{display:'flex',gap:14,marginBottom:22,flexWrap:'wrap'}}>
        <StatCard label="Nodos Online" value="2/2" sub="100% disponibilidad" color="#22c55e" icon="Activity"/>
        <StatCard label="Muestras Acumuladas" value="14,850" sub="Ambos nodos" color={PURPLE_L} icon="BarChart"/>
        <StatCard label="Buffer Pendiente" value="3 reg." sub="Node 002" color="#f59e0b" icon="Clock"/>
        <StatCard label="Uptime Sistema" value="99.2%" sub="Últimas 168h" color="#22c55e" icon="TrendingUp"/>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:14}}>
        {services.map((s,i) => (
          <Card key={i} style={{display:'flex',alignItems:'center',gap:14,padding:'14px 18px'}}>
            <div style={{width:38,height:38,borderRadius:10,background:'#10101e',border:'1px solid #2a2740',display:'flex',alignItems:'center',justifyContent:'center',color:PURPLE_L}}><Icon name={s.icon} size={18}/></div>
            <div style={{flex:1}}>
              <div style={{fontSize:13,fontWeight:700,color:'#f0eeff'}}>{s.name}</div>
              {s.latency!=='—' && <div style={{fontSize:11,color:'#6e6694',marginTop:2}}>Latencia: {s.latency}</div>}
            </div>
            <div>
              <StatusDot status={s.status==='ok'?'online':s.status==='mock'?'warning':'offline'}/>
              <span style={{fontSize:11,color:s.status==='ok'?'#22c55e':s.status==='mock'?'#f59e0b':'#ef4444',fontWeight:600}}>
                {s.status==='ok'?'OK':s.status==='mock'?'Mock/Dev':'Error'}
              </span>
            </div>
          </Card>
        ))}
      </div>
      {MOCK.nodes.map(n => (
        <Card key={n.id} style={{marginTop:14}}>
          <div style={{fontSize:14,fontWeight:700,color:'#f0eeff',marginBottom:12}}>{n.name} — Detalle de Hardware</div>
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(130px,1fr))',gap:10}}>
            {[
              {l:'IP (Tailscale)',v:n.ip},{l:'Firmware',v:`v${n.fw}`},
              {l:'Muestras',v:n.samples.toLocaleString()},{l:'Buffer',v:`${n.buffer} pend.`},
              {l:'RPi Status',v:n.rpi_status.toUpperCase()},{l:'Shelly Status',v:n.shelly_status.toUpperCase()},
              {l:'Última Sync',v:n.last_sync},{l:'Edificio',v:n.building}
            ].map((r,i) => (
              <div key={i} style={{background:'#0f0f1a',borderRadius:8,padding:'8px 10px'}}>
                <div style={{fontSize:10,color:'#6e6694'}}>{r.l}</div>
                <div style={{fontSize:12,fontWeight:600,color:'#f0eeff',marginTop:2}}>{r.v}</div>
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
};

// ─── PAGE: SETTINGS ───────────────────────────────────────────────────────────
const PageSettings = ({ role, setRole }) => (
  <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:18}}>
    <div>
      <Card style={{marginBottom:14}}>
        <SectionTitle sub="Gestión de perfil de usuario">Perfil de Usuario</SectionTitle>
        {[{l:'Nombre',v:'Dr. Carlos Mendoza'},{l:'Email',v:'c.mendoza@ucol.mx'},{l:'Rol',v:role},{l:'Campus',v:'Campus Colima'}].map((r,i) => (
          <div key={i} style={{display:'flex',justifyContent:'space-between',padding:'9px 0',borderBottom:'1px solid #0f0f1a',fontSize:13}}>
            <span style={{color:'#6e6694'}}>{r.l}</span>
            <span style={{color:'#f0eeff',fontWeight:600}}>{r.v}</span>
          </div>
        ))}
      </Card>
      <Card>
        <SectionTitle sub="Simulación de vista por rol">Selector de Rol</SectionTitle>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
          {ROLES.map(r => (
            <button key={r} onClick={() => setRole(r)} style={{
              padding:'12px', borderRadius:10, border:`1px solid ${role===r?PURPLE:'#2a2740'}`,
              background: role===r ? '#7c5cbf22' : '#0f0f1a',
              color: role===r ? PURPLE_L : '#9890c4', fontWeight: role===r ? 700 : 400,
              fontSize:13, cursor:'pointer'
            }}>{r}</button>
          ))}
        </div>
      </Card>
    </div>
    <div>
      <Card style={{marginBottom:14}}>
        <SectionTitle sub="Configuración tarifaria CFE">Tarifas (placeholder)</SectionTitle>
        {[{l:'Tarifa activa',v:'GDMTH'},{l:'Cargo base',v:'$31.98/kWh'},{l:'Cargo intermedia',v:'$40.95/kWh'},{l:'Cargo punta',v:'$145.36/kWh'}].map((r,i) => (
          <div key={i} style={{display:'flex',justifyContent:'space-between',padding:'8px 0',borderBottom:'1px solid #0f0f1a',fontSize:13}}>
            <span style={{color:'#6e6694'}}>{r.l}</span>
            <span style={{color:'#f0eeff',fontWeight:600}}>{r.v}</span>
          </div>
        ))}
        <button style={{marginTop:12,width:'100%',padding:'9px',background:'#1a1730',border:'1px solid #2a2740',borderRadius:10,color:'#9890c4',fontSize:13,cursor:'pointer'}}>Actualizar Tarifas CFE</button>
      </Card>
      <Card>
        <SectionTitle sub="Umbrales de alertas del sistema">Umbrales de Alertas</SectionTitle>
        {[{l:'Alerta de costo diario',v:'$2,000 MXN'},{l:'Factor de potencia mínimo',v:'0.90'},{l:'Pico de demanda máximo',v:'10 kW'},{l:'Tiempo sin sincronía',v:'15 min'}].map((r,i) => (
          <div key={i} style={{display:'flex',justifyContent:'space-between',padding:'8px 0',borderBottom:'1px solid #0f0f1a',fontSize:13}}>
            <span style={{color:'#6e6694'}}>{r.l}</span>
            <span style={{color:PURPLE_L,fontWeight:600}}>{r.v}</span>
          </div>
        ))}
      </Card>
    </div>
  </div>
);

// ─── APP ROOT ─────────────────────────────────────────────────────────────────
const App = () => {
  const [apiBuildings, setApiBuildings] = useState(null);
  const [apiNodes, setApiNodes] = useState(null);
  const [apiInsights, setApiInsights] = useState(null);

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
  }, []);

  const [page, setPage] = useState('dashboard');
  const [role, setRole] = useState('Administrador');
  const renderPage = () => {
    switch(page) {
      case 'dashboard': return <PageDashboard/>;
      case 'campus': return <PageCampus apiBuildings={apiBuildings}/>;
      case 'buildings': return <PageBuildings setPage={setPage} apiBuildings={apiBuildings}/>;
      case 'buildingDetail': return <PageBuildingDetail building={MOCK.buildings[0]}/>;
      case 'deployments': return <PageDeployments apiNodes={apiNodes}/>;
      case 'live': return <PageLive apiNodes={apiNodes}/>;
      case 'cost': return <PageCost/>;
      case 'ai': return <PageAI apiInsights={apiInsights}/>;
      case 'mining': return <PageMining/>;
      case 'reports': return <PageReports/>;
      case 'infra': return <PageInfra/>;
      case 'settings': return <PageSettings role={role} setRole={setRole}/>;
      default: return <PageDashboard/>;
    }
  };
  return (
    <div style={{display:'flex',minHeight:'100vh'}}>
      <Sidebar page={page} setPage={setPage} role={role} setRole={setRole}/>
      <div style={{marginLeft:230,flex:1,minHeight:'100vh',background:'#0a0a0f'}}>
        <Topbar page={page}/>
        <main style={{padding:'24px 28px'}}>
          {renderPage()}
        </main>
      </div>
    </div>
  );
};

export default App;

import "./claude-app.css";
