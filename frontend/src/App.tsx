// @ts-nocheck
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ucolLogo from "./assets/ucol-logo.png";
import { getDashboardSummary, getHourlyCost, getBuildings, getNodes, getAiInsights, createDeployment, getDelegations, getAllOrgBuildings, getCampusesByDelegation, getUnitsByCampus, getBuildingsByUnit, getPanelsByBuilding, getLatestReadings, getLiveMetrics, getMetricsHourly, getMetricsTariffs, getMetricsDaily, getMetricsBuildings, getAnomalies,
  getCfeStatus, getCampusMetrics, getDeployments, finishDeployment, getDeploymentReports, generateDeploymentReport, getCostSummary, getSystemSettings, getInfrastructureStatus, getMiningAnalytics, getAiCenter, askAiAssistant } from "./services/api";

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ComposedChart
} from "recharts";

const TARIFF_COLORS = { base:'#2563eb', intermedia:'#f59e0b', punta:'#ef4444' };
const STATUS_COLORS = { online:'#22c55e', offline:'#6b7280', warning:'#f59e0b', normal:'#22c55e', active:'#22c55e', inactive:'#6b7280', error:'#ef4444', ok:'#22c55e' };
// Design tokens — mirror of the CSS custom properties in src/index.css.
// A single accent (blue). Every other hue is a status, never decoration.
const ACCENT = '#2563eb';
const ACCENT_QUIET = '#3b82f6';
const SURFACE = '#171a1d';
const SURFACE_INNER = '#121417';
const BORDER = '#252a31';
const BORDER_SOFT = '#1e2227';
const TEXT = '#f5f7fa';
const TEXT_SECONDARY = '#9aa4af';
const TEXT_MUTED = '#7c8793';
const CARD_SHADOW = '0 1px 2px rgba(0,0,0,.24)';
const CHART_GRID = '#1e2227';
const TH = { padding:'0 10px 10px 0', fontWeight:500 };
const TD = { padding:'9px 10px 9px 0', verticalAlign:'middle' };
const BTN_PRIMARY = { background:ACCENT, color:'#fff', border:`1px solid ${ACCENT}`, borderRadius:6, padding:'9px 16px', fontWeight:500, fontSize:13, cursor:'pointer' };
const BTN_SECONDARY = { background:SURFACE_INNER, color:TEXT_SECONDARY, border:`1px solid ${BORDER}`, borderRadius:6, padding:'9px 16px', fontWeight:500, fontSize:13, cursor:'pointer' };
const TOOLTIP_STYLE = { background:SURFACE, border:`1px solid ${BORDER}`, borderRadius:'6px', color:TEXT, fontSize:12, boxShadow:'0 4px 16px rgba(0,0,0,.4)' };


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
  BarChart: <><path d="M4 19V5M4 19h17M8 16v-5M13 16V8M18 16v-9"/></>,
  Zap: <><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/></>,
  AlertTriangle: <><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></>,
  Clipboard: <><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/></>
};
const Icon = ({ name='Activity', size=16, color='currentColor', stroke=1.8, style }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={{display:'block',...style}}>
    {ICONS[name] || ICONS.Activity}
  </svg>
);
const iconForNav = (name) => ({ LayoutDashboard:'Dashboard', MapPin:'Map', Building2:'Building', Cpu:'Cpu', Activity:'Activity', DollarSign:'Dollar', BrainCircuit:'Brain', Database:'Database', BarChart2:'BarChart', FileText:'FileText', Server:'Server', PlugZap:'Plug', Settings:'Settings' }[name] || 'Activity');
const PRIORITY_META = {
  high:{label:'Alta prioridad',color:'#ef4444'},
  medium:{label:'Prioridad media',color:'#f59e0b'},
  low:{label:'Observación',color:'#2563eb'},
  info:{label:'Información',color:ACCENT_QUIET}
};

// Professional inline SVG icons — no CDN dependency

// ─── COMMON COMPONENTS ────────────────────────────────────────────────────────
const Card = ({ children, style, glow, className }) => (
  <div style={{
    background:SURFACE, border:`1px solid ${glow ? '#2b3540' : BORDER}`, borderRadius:12,
    padding:'18px 20px', position:'relative', overflow:'hidden',
    boxShadow:CARD_SHADOW,
    ...style
  }} className={className}>{children}</div>
);

const Badge = ({ children, color='#2563eb', bg }) => (
  <span style={{
    background: bg || `${color}14`, color, border:`1px solid ${color}33`,
    borderRadius:4, padding:'3px 8px', fontSize:11, fontWeight:500, letterSpacing:.2,
    whiteSpace:'nowrap'
  }}>{children}</span>
);

const StatusDot = ({ status }) => (
  <span style={{
    display:'inline-block', width:7, height:7, borderRadius:'50%',
    background: STATUS_COLORS[status] || TEXT_MUTED,
    marginRight:6
  }}/>
);

// Call sites still pass a `color`; the enterprise theme deliberately ignores it.
// Metric tiles stay neutral so colour only ever means status, never decoration.
const StatCard = ({ label, value, sub, icon, trend, trendLabel }) => (
  <Card style={{flex:1,minWidth:140,padding:'16px 18px'}}>
    <div style={{display:'flex',alignItems:'center',gap:7,marginBottom:10}}>
      {icon && <Icon name={icon} size={13} color={TEXT_MUTED} stroke={1.6}/>} 
      <div style={{fontSize:10.5,color:TEXT_MUTED,textTransform:'uppercase',letterSpacing:.9,fontWeight:600}}>{label}</div>
    </div>
    <div style={{fontSize:25,fontWeight:600,color:TEXT,letterSpacing:-0.6,lineHeight:1.1,fontVariantNumeric:'tabular-nums'}}>{value}</div>
    {sub && <div style={{fontSize:12,color:TEXT_SECONDARY,marginTop:7,lineHeight:1.45}}>{sub}</div>}
    {trendLabel && (
      <div style={{
        display:'inline-flex',
        alignItems:'center',
        gap:4,
        fontSize:11,
        color: trend === null || trend === undefined ? TEXT_MUTED : trend > 0 ? '#ef4444' : '#22c55e',
        marginTop:8,
        fontWeight:500
      }}>
        {trend !== null && trend !== undefined && <Icon name={trend > 0 ? 'TrendingUp' : 'ArrowDown'} size={12}/>}
        {trendLabel}
      </div>
    )}
  </Card>
);

// Two calling conventions grew up in this file: `children`+`sub` (4 call sites)
// and `title`+`subtitle` (18 call sites). Only the first was ever supported, so
// the other eighteen headings rendered as empty <h2> elements. Resolve both
// shapes here rather than editing every call site.
const SectionTitle = ({ children, sub, title, subtitle }) => {
  const heading = title ?? children;
  const caption = subtitle ?? sub;
  return (
    <div style={{marginBottom:16}}>
      <h2 style={{fontSize:14,fontWeight:600,color:TEXT,letterSpacing:-0.1}}>{heading}</h2>
      {caption && <p style={{fontSize:11.5,color:TEXT_MUTED,marginTop:3}}>{caption}</p>}
    </div>
  );
};

const STATUS_META = {
  active:   { label:'Activa',   color:'#ef4444' },
  resolved: { label:'Resuelta', color:'#22c55e' },
};

const fmtInsightValue = (value, unit) =>
  value === null || value === undefined
    ? '—'
    : `${Number(value).toFixed(2)}${unit || ''}`;

const fmtInsightTime = (value) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('es-MX');
};

/**
 * `archived` marks the whole list as history because the selected deployment
 * has stopped reporting. A finding that was ACTIVE at the moment measurement
 * ended is still not happening *now* — nothing is — so the card says
 * "histórica" rather than implying a live problem.
 */
const AIInsightCard = ({ insights, archived = false }) => {
  const normalized = insights.map((ins, i) => {
    if (typeof ins === 'string') {
      return {
        priority: i === 0 ? 'medium' : 'info',
        category: 'Sistema',
        building: 'Sin edificio',
        impact: 'Sin clasificación',
        title: 'Mensaje del sistema',
        desc: ins,
        status: null,
      };
    }

    return {
      priority: ins.priority || ins.severity || 'info',
      category: ins.category || 'Anomalía',
      building: ins.building || ins.node_id || 'Sin edificio',
      impact: ins.threshold !== undefined && ins.threshold !== null
        ? `Umbral: ${Number(ins.threshold).toFixed(2)}${ins.unit || ''}`
        : 'Evento detectado',
      title: ins.title || 'Anomalía detectada',
      desc: ins.description || ins.desc || 'Sin descripción',
      status: ins.status || null,
      unit: ins.unit || '',
      previousValue: ins.previous_value,
      previousAt: ins.previous_at,
      currentValue: ins.current_value,
      currentAt: ins.current_at,
      recoveredAt: ins.recovered_at,
    };
  });

  const activeCount = normalized.filter((ins) => ins.status === 'active').length;

  if (normalized.length === 0) {
    return (
      <Card>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <div style={{background:SURFACE_INNER,border:`1px solid ${BORDER}`,borderRadius:8,padding:8,color:TEXT_SECONDARY,display:'flex'}}><Icon name="Brain" size={16} stroke={1.6}/></div>
          <div>
            <div style={{fontSize:13.5,fontWeight:600,color:TEXT,letterSpacing:-0.1}}>Centro de Insights</div>
            <div style={{fontSize:11,color:TEXT_MUTED,marginTop:2}}>
              Sin anomalías registradas para este despliegue.
            </div>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:10,marginBottom:16}}>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <div style={{background:SURFACE_INNER,border:`1px solid ${BORDER}`,borderRadius:8,padding:8,color:TEXT_SECONDARY,display:'flex'}}><Icon name="Brain" size={16} stroke={1.6}/></div>
          <div>
            <div style={{fontSize:13.5,fontWeight:600,color:TEXT,letterSpacing:-0.1}}>Centro de Insights</div>
            <div style={{fontSize:11,color:TEXT_MUTED,marginTop:2}}>
              {archived
                ? `${normalized.length} evento(s) histórico(s) · despliegue sin telemetría`
                : `${activeCount} activa(s) · ${normalized.length - activeCount} resuelta(s)`}
            </div>
          </div>
        </div>
        <Badge color={TEXT_SECONDARY}>Anomaly Engine</Badge>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(260px,1fr))',gap:12}}>
        {normalized.map((ins,i) => {
          const meta = PRIORITY_META[ins.priority] || PRIORITY_META.info;
          // An archived deployment has no "now", so nothing in it is live.
          const effectiveStatus = archived && ins.status ? 'resolved' : ins.status;
          const status = effectiveStatus ? STATUS_META[effectiveStatus] : null;
          // Severity only colours the card while the condition is live;
          // a recovered finding is history and is not tinted red.
          const accent = status
            ? (effectiveStatus === 'active' ? meta.color : STATUS_META.resolved.color)
            : meta.color;
          const showRecovery = ins.status === 'resolved';
          return (
            <div key={i} style={{background:SURFACE_INNER,border:`1px solid ${BORDER}`,borderLeft:`2px solid ${accent}`,borderRadius:8,padding:'13px 14px'}}>
              <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:8,marginBottom:10}}>
                <div style={{display:'flex',alignItems:'center',gap:6,flexWrap:'wrap'}}>
                  {status && <Badge color={status.color}>{status.label}</Badge>}
                  {archived && <Badge color={TEXT_MUTED}>Histórica</Badge>}
                  {!status && <Badge color={meta.color}>{meta.label}</Badge>}
                </div>
                <span style={{fontSize:10,color:TEXT_MUTED,textTransform:'uppercase',letterSpacing:.7}}>{ins.category}</span>
              </div>
              <div style={{display:'flex',alignItems:'center',gap:7,marginBottom:8}}>
                <Icon name="Building" size={13} color={TEXT_MUTED} stroke={1.6}/>
                <span style={{fontSize:12,color:TEXT,fontWeight:500}}>{ins.building}</span>
              </div>
              <div style={{fontSize:12,color:TEXT,fontWeight:500,marginBottom:6}}>{ins.title}</div>
              <p style={{fontSize:12,color:TEXT_SECONDARY,lineHeight:1.55,marginBottom:8}}>{ins.desc}</p>

              {showRecovery && (
                <div style={{
                  display:'grid', gridTemplateColumns:'auto 1fr', gap:'4px 10px',
                  fontSize:11, marginBottom:8, paddingTop:8,
                  borderTop:`1px solid ${BORDER}`
                }}>
                  <span style={{color:TEXT_MUTED}}>Valor previo</span>
                  <span style={{color:TEXT,fontVariantNumeric:'tabular-nums'}}>
                    {fmtInsightValue(ins.previousValue, ins.unit)}
                    <span style={{color:TEXT_MUTED}}> · {fmtInsightTime(ins.previousAt)}</span>
                  </span>
                  <span style={{color:TEXT_MUTED}}>Valor actual</span>
                  <span style={{color:TEXT,fontVariantNumeric:'tabular-nums'}}>
                    {fmtInsightValue(ins.currentValue, ins.unit)}
                    <span style={{color:TEXT_MUTED}}> · {fmtInsightTime(ins.currentAt)}</span>
                  </span>
                  <span style={{color:TEXT_MUTED}}>Recuperado</span>
                  <span style={{color:'#22c55e'}}>{fmtInsightTime(ins.recoveredAt)}</span>
                </div>
              )}

              {effectiveStatus === 'active' && ins.currentValue !== null && ins.currentValue !== undefined && (
                <div style={{
                  display:'grid', gridTemplateColumns:'auto 1fr', gap:'4px 10px',
                  fontSize:11, marginBottom:8, paddingTop:8,
                  borderTop:`1px solid ${BORDER}`
                }}>
                  <span style={{color:TEXT_MUTED}}>Valor actual</span>
                  <span style={{color:TEXT,fontVariantNumeric:'tabular-nums'}}>
                    {fmtInsightValue(ins.currentValue, ins.unit)}
                    <span style={{color:TEXT_MUTED}}> · {fmtInsightTime(ins.currentAt)}</span>
                  </span>
                </div>
              )}

              <div style={{fontSize:11,color:TEXT_MUTED}}>{ins.impact}</div>
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
      <div style={{padding:'8px 11px'}}>
        <div style={{fontSize:11,color:TEXT_MUTED,marginBottom:6}}>{label}</div>
        {payload.map((p,i) => (
          <div key={i} style={{fontSize:12.5,color:p.color||TEXT,fontWeight:500,fontVariantNumeric:'tabular-nums'}}>
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
  { id:'dataExplorer', label:'Explorador de Datos', icon:'BarChart2' },
  { id:'reports', label:'Reportes', icon:'FileText' },
  { id:'infra', label:'Infraestructura', icon:'Server' },
  { id:'smartplugs', label:'Smart Plugs', icon:'PlugZap' },
  { id:'settings', label:'Configuración', icon:'Settings' }
];




const ROLE_ACCESS = {
  Administrador: "all",
  Ejecutivo: ["dashboard", "campus", "buildings", "cost", "ai", "reports", "dataExplorer"],
  Técnico: ["dashboard", "campus", "buildings", "deployments", "live", "infra", "reports"],
  Investigador: ["dashboard", "campus", "buildings", "mining", "dataExplorer", "ai", "reports"],
};

const canAccessPage = (role, pageId) => {
  const access = ROLE_ACCESS[role] || ROLE_ACCESS.Administrador;
  return access === "all" || access.includes(pageId);
};

const firstAllowedPage = (role) => {
  const access = ROLE_ACCESS[role] || ROLE_ACCESS.Administrador;
  if (access === "all") return "dashboard";
  return access[0] || "dashboard";
};

const Sidebar = ({ page, setPage, role, setRole }) => {
  return (
    <div style={{
      width: 230,
      background: '#0b0d10',
      borderRight: `1px solid ${BORDER}`,
      position: 'fixed',
      left: 0,
      top: 0,
      bottom: 0,
      zIndex: 20,
      display: 'flex',
      flexDirection: 'column'
    }}>
      <div style={{padding:'0 18px',height:56,display:'flex',alignItems:'center',borderBottom:`1px solid ${BORDER}`}}>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <div style={{
            width:26,
            height:26,
            borderRadius:6,
            background:ACCENT,
            display:'flex',
            alignItems:'center',
            justifyContent:'center',
            flexShrink:0
          }}>
            <Icon name="Bolt" size={14} color="#fff" stroke={2}/>
          </div>
          <div>
            <div style={{color:TEXT,fontWeight:600,fontSize:13,letterSpacing:-0.1}}>Energy IQ</div>
            <div style={{color:TEXT_MUTED,fontSize:9.5,textTransform:'uppercase',letterSpacing:.9,marginTop:1}}>UCol Platform</div>
          </div>
        </div>
      </div>

      <nav style={{padding:'10px 0',flex:1,overflowY:'auto'}}>
        {NAV_ITEMS.filter((item) => canAccessPage(role, item.id)).map((item) => (
          <button
            key={item.id}
            className={page===item.id ? 'nav-item nav-item-active' : 'nav-item'}
            onClick={() => setPage(item.id)}
            style={{
              width:'100%',
              background: page===item.id ? '#14181c' : 'transparent',
              border:0,
              borderRadius:0,
              display:'flex',
              alignItems:'center',
              gap:10,
              padding:'8px 18px',
              color: page===item.id ? TEXT : TEXT_SECONDARY,
              fontWeight: 500,
              fontSize:12.5,
              cursor:'pointer',
              boxShadow: page===item.id ? `inset 2px 0 0 ${ACCENT}` : 'none',
              textAlign:'left'
            }}
          >
            <Icon name={iconForNav(item.icon)} size={14} stroke={1.6} color={page===item.id ? TEXT_SECONDARY : TEXT_MUTED}/>
            {item.label}
          </button>
        ))}
      </nav>
    </div>
  );
};

// ─── TOPBAR ───────────────────────────────────────────────────────────────────
const Topbar = ({page, activeNodesText}) => {
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const currentRole = localStorage.getItem("energy_role") || "Administrador";
  const currentUser = localStorage.getItem("energy_user") || (
    currentRole === "Ejecutivo" ? "ejecutivo@ucol.mx" :
    currentRole === "Técnico" ? "tecnico@ucol.mx" :
    currentRole === "Investigador" ? "investigador@ucol.mx" :
    "admin@ucol.mx"
  );

  const logout = () => {
    localStorage.removeItem("energy_auth");
    localStorage.removeItem("energy_role");
    localStorage.removeItem("energy_user");
    window.location.reload();
  };
  const titles = { dashboard:'Dashboard Ejecutivo', campus:'Mapa de Campus', buildings:'Edificios',
    deployments:'Despliegues', live:'Monitoreo en Vivo', cost:'Análisis de Costo',
    ai:'Centro IA & Forecasting', mining:'Minería de Datos', dataExplorer:'Explorador de Datos', reports:'Reportes',
    infra:'Infraestructura', smartplugs:'Smart Plugs', settings:'Configuración' };
  const [time, setTime] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setTime(new Date()), 30000); return () => clearInterval(t); }, []);
  return (
    <div style={{
      background:'#0b0d10', borderBottom:`1px solid ${BORDER}`,
      padding:'0 28px', height:56, display:'flex', alignItems:'center',
      justifyContent:'space-between', position:'sticky', top:0, zIndex:90
    }}>
      <div>
        <h1 style={{fontSize:14,fontWeight:600,color:TEXT,letterSpacing:-0.1}}>{titles[page] || page}</h1>
        <p style={{fontSize:11,color:TEXT_MUTED,marginTop:1}}>Universidad de Colima · GDMTH · jueves, 18 de junio de 2026</p>
      </div>
      <div style={{display:'flex',alignItems:'center',gap:14}}>
        <div style={{fontSize:12,color:TEXT_MUTED,fontVariantNumeric:'tabular-nums'}}>
          {time.toLocaleTimeString('es-MX', {hour:'2-digit',minute:'2-digit'})}
        </div>
        <div style={{display:'flex',alignItems:'center',gap:7,background:SURFACE_INNER,border:`1px solid ${BORDER}`,borderRadius:4,padding:'4px 10px'}}>
          <StatusDot status="online"/>
          <span style={{fontSize:11,color:TEXT_SECONDARY,fontWeight:500}}>{activeNodesText}</span>
        </div>
        <div style={{position:"relative"}}>
            <button
              onClick={() => setUserMenuOpen(!userMenuOpen)}
              style={{
                width:30,
                height:30,
                borderRadius:"50%",
                border:`1px solid ${BORDER}`,
                background:SURFACE_INNER,
                color:TEXT_SECONDARY,
                fontSize:12,
                fontWeight:600,
                padding:0,
                cursor:"pointer"
              }}
            >
              {currentRole.charAt(0)}
            </button>

            {userMenuOpen && (
              <div style={{
                position:"absolute",
                right:0,
                top:42,
                width:260,
                background:SURFACE,
                border:`1px solid ${BORDER}`,
                borderRadius:10,
                padding:14,
                zIndex:50,
                boxShadow:"0 12px 32px rgba(0,0,0,.5)"
              }}>
                <div style={{fontSize:10,color:TEXT_MUTED,textTransform:"uppercase",letterSpacing:.9,fontWeight:600}}>Sesión activa</div>
                <div style={{marginTop:9,color:TEXT,fontWeight:500,fontSize:13}}>{currentUser}</div>
                <div style={{marginTop:3,color:TEXT_SECONDARY,fontSize:12}}>{currentRole}</div>
                <div style={{marginTop:10,color:TEXT_MUTED,fontSize:11.5,lineHeight:1.5}}>
                  Energy Intelligence Platform · Universidad de Colima
                </div>
                <button
                  onClick={logout}
                  style={{
                    marginTop:14,
                    width:"100%",
                    background:"transparent",
                    border:"1px solid #ef444455",
                    color:"#ef4444",
                    borderRadius:6,
                    padding:"8px 12px",
                    fontSize:12.5,
                    fontWeight:500,
                    cursor:"pointer"
                  }}
                >
                  Cerrar sesión
                </button>
              </div>
            )}
          </div>
      </div>
    </div>
  );
};

// ─── DEPLOYMENT SELECTOR ──────────────────────────────────────────────────────
/**
 * ACTIVE / ARCHIVED here is `telemetry_state` from the backend — whether the
 * deployment is producing data right now — not `status`, which is the
 * administrative lifecycle. A campaign can be marked "completed" and still be
 * measuring, and the header must say what is true of the data on screen.
 */
const isLive = (deployment) => deployment?.telemetry_state === "active";

/** Newest data first, so the most relevant campaign leads each group. */
const byNewestReading = (a, b) =>
  String(b.last_reading_at || "").localeCompare(String(a.last_reading_at || ""));

/**
 * Which deployment the dashboard opens on:
 *   1. one still producing telemetry,
 *   2. otherwise the one with the newest data,
 *   3. otherwise none.
 */
const pickDefaultDeployment = (deployments) => {
  if (!deployments?.length) return null;
  const live = deployments.filter(isLive).sort(byNewestReading);
  if (live.length) return live[0].id;
  const withData = deployments.filter((d) => d.last_reading_at).sort(byNewestReading);
  if (withData.length) return withData[0].id;
  return deployments[0].id;
};

const deploymentLabel = (deployment) =>
  `${deployment.node_id} · ${deployment.building_name}`;

const DeploymentBadge = ({ deployment }) => {
  const live = isLive(deployment);
  const color = live ? '#22c55e' : TEXT_MUTED;
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap:6,
      background:`${color}14`, border:`1px solid ${color}33`, color,
      borderRadius:4, padding:'3px 8px', fontSize:10.5, fontWeight:600,
      letterSpacing:.6, textTransform:'uppercase', whiteSpace:'nowrap'
    }}>
      <span style={{width:6,height:6,borderRadius:'50%',background:color,display:'inline-block'}}/>
      {live ? 'Active' : 'Archived'}
    </span>
  );
};

const DeploymentSelector = ({ deployments, selectedId, onSelect }) => {
  const current = deployments.filter(isLive).sort(byNewestReading);
  const historical = deployments.filter((d) => !isLive(d)).sort(byNewestReading);
  const selected = deployments.find((d) => d.id === selectedId);

  if (!deployments.length) return null;

  return (
    <div style={{display:'flex',alignItems:'center',gap:10,flexWrap:'wrap'}}>
      <select
        value={selectedId ?? ''}
        onChange={(e) => onSelect(Number(e.target.value))}
        aria-label="Despliegue"
        style={{
          background:SURFACE_INNER, color:TEXT, border:`1px solid ${BORDER}`,
          borderRadius:6, padding:'7px 11px', fontSize:12.5, minWidth:280
        }}
      >
        {current.length > 0 && (
          <optgroup label="Despliegues actuales">
            {current.map((d) => (
              <option key={d.id} value={d.id}>{deploymentLabel(d)}</option>
            ))}
          </optgroup>
        )}
        {historical.length > 0 && (
          <optgroup label="Despliegues históricos">
            {historical.map((d) => (
              <option key={d.id} value={d.id}>{deploymentLabel(d)}</option>
            ))}
          </optgroup>
        )}
      </select>
      {selected && <DeploymentBadge deployment={selected}/>}
    </div>
  );
};

// ─── PAGE: EXECUTIVE DASHBOARD ────────────────────────────────────────────────
const PageDashboard = () => {
  const [dashboardSummary, setDashboardSummary] = useState(null);
  const [hourlyCost, setHourlyCost] = useState(null);
  const [tariffMetrics, setTariffMetrics] = useState(null);
  const [dailyMetrics, setDailyMetrics] = useState(null);
  const [buildingMetrics, setBuildingMetrics] = useState(null);
  const [deployments, setDeployments] = useState([]);
  const [selectedDeploymentId, setSelectedDeploymentId] = useState(null);
  const [scopedAnomalies, setScopedAnomalies] = useState(null);

  // The deployment list is loaded once; the selection it produces is what every
  // widget below keys off.
  useEffect(() => {
    getDeployments()
      .then((data) => {
        const list = Array.isArray(data) ? data : [];
        setDeployments(list);
        setSelectedDeploymentId((current) => current ?? pickDefaultDeployment(list));
      })
      .catch((error) => console.error("Deployments API error:", error));
  }, []);

  const selectedDeployment = deployments.find((d) => d.id === selectedDeploymentId) || null;

  useEffect(() => {
    // Nothing is fetched until a deployment is chosen: the dashboard shows one
    // deployment at a time, so an unscoped first paint would briefly display
    // fleet-wide figures under a deployment heading.
    if (selectedDeploymentId === null) return;
    const scope = selectedDeploymentId;

    getAnomalies(scope, true)
      .then(setScopedAnomalies)
      .catch((error) => console.error("Anomalies API error:", error));

    getDashboardSummary(scope)
      .then(setDashboardSummary)
      .catch((error) => console.error("Dashboard summary API error:", error));

    getMetricsHourly(scope)
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

    getMetricsTariffs(scope)
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

    getMetricsDaily(scope)
      .then((data) => {
        const normalized = data.map((item) => ({
          day: item.day,
          cost: item.cost_mxn,
          kwh: item.kwh,
        }));
        setDailyMetrics(normalized);
      })
      .catch((error) => console.error("Daily metrics API error:", error));

    getMetricsBuildings(scope)
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
    // Re-runs on every change of selection, which is what reloads the KPIs,
    // all four charts and the insight list together.
  }, [selectedDeploymentId]);

  const mxn = (value) => `$${Number(value || 0).toLocaleString("es-MX")} MXN`;
  const hourlyChartData = hourlyCost || [];

  const tariffData = tariffMetrics || [
    { name:'Base', kwh:0, cost:0, pct:0 },
    { name:'Intermedia', kwh:0, cost:0, pct:0 },
    { name:'Punta', kwh:0, cost:0, pct:0 }
  ];
  const dailyChartData = dailyMetrics || [];
  const buildingChartData = buildingMetrics || [];

  if (deployments.length === 0) {
    return (
      <Card>
        <SectionTitle title="Sin despliegues registrados"
                      subtitle="El dashboard muestra un despliegue a la vez; registra uno en Despliegues para comenzar."/>
      </Card>
    );
  }

  return (
    <div>
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        gap:14, flexWrap:'wrap', marginBottom:18
      }}>
        <div>
          <h2 style={{fontSize:14,fontWeight:600,color:TEXT,letterSpacing:-0.1}}>
            {selectedDeployment ? selectedDeployment.building_name : 'Sin despliegue seleccionado'}
          </h2>
          <p style={{fontSize:11.5,color:TEXT_MUTED,marginTop:3}}>
            {selectedDeployment
              ? `Despliegue #${selectedDeployment.id} · ${selectedDeployment.node_id} · ${selectedDeployment.electrical_panel} · ${selectedDeployment.campus} · ${selectedDeployment.start_date} → ${selectedDeployment.end_date || 'sin cierre'}`
              : 'Selecciona un despliegue'}
          </p>
        </div>
        <DeploymentSelector
          deployments={deployments}
          selectedId={selectedDeploymentId}
          onSelect={setSelectedDeploymentId}
        />
      </div>

      {selectedDeployment && !isLive(selectedDeployment) && (
        <div style={{
          display:'flex', alignItems:'center', gap:8, marginBottom:18,
          background:SURFACE_INNER, border:`1px solid ${BORDER}`, borderRadius:8,
          padding:'9px 12px', fontSize:12, color:TEXT_SECONDARY
        }}>
          <Icon name="Clock" size={13} stroke={1.6} color={TEXT_MUTED}/>
          Despliegue archivado · sin telemetría desde{' '}
          {selectedDeployment.last_reading_at
            ? new Date(selectedDeployment.last_reading_at).toLocaleString('es-MX')
            : 'sin lecturas'}. Las cifras y los insights son históricos.
        </div>
      )}

      <div style={{display:'flex',flexWrap:'wrap',gap:14,marginBottom:22}}>
        <StatCard label="Costo Estimado Hoy" value={dashboardSummary ? mxn(dashboardSummary.estimated_cost_today_mxn) : "Cargando..."} sub={dashboardSummary?.most_expensive_building?.name ? `Mayor consumo: ${dashboardSummary.most_expensive_building.name}` : `${dashboardSummary?.online_nodes || 0}/${dashboardSummary?.total_nodes || 0} nodos activos`} color="#2563eb" trend={dashboardSummary?.has_previous_day_data ? Number(dashboardSummary.daily_comparison_pct) : null}
            trendLabel={dashboardSummary?.daily_comparison_label || "Histórico insuficiente"} icon="Wallet"/>
        <StatCard label="Costo Esta Semana" value={dashboardSummary ? mxn(dashboardSummary.estimated_cost_week_mxn) : "Cargando..."} sub="Acumulado lun–hoy" color="#ef4444" trend={dashboardSummary?.has_previous_week_data ? Number(dashboardSummary.week_comparison_pct) : null}
            trendLabel={dashboardSummary?.comparison_label || "Histórico insuficiente"} icon="Calendar"/>
        <StatCard label="Proyección Mensual" value={dashboardSummary ? mxn(dashboardSummary.projected_monthly_cost_mxn) : "Cargando..."} sub="Estimado GDMTH" color="#f59e0b" icon="TrendingUp"/>
        <StatCard label="Ahorro Potencial" value={dashboardSummary ? `${mxn(dashboardSummary.potential_savings_mxn_month)}/mes` : "Cargando..."} sub="Recomendaciones activas" color="#22c55e" icon="ArrowDown"/>
        <StatCard label="Edificio más costoso" value={dashboardSummary ? (dashboardSummary.most_expensive_building?.name || "Sin consumo") : "Cargando..."} sub={dashboardSummary?.most_expensive_building ? `${mxn(dashboardSummary.most_expensive_building.cost_week_mxn)} esta semana` : "Sin costo registrado esta semana"} color="#3b82f6" icon="Building"/>
        <StatCard label="Nodos Online" value={dashboardSummary ? `${dashboardSummary.online_nodes} / ${dashboardSummary.total_nodes}` : "Cargando..."} sub="Sistema operativo" color="#22c55e" icon="Activity"/>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'2fr 1fr',gap:18,marginBottom:18}}>
        <Card>
          <SectionTitle sub="Costo estimado por hora · tarifa GDMTH">Costo por Hora (MXN)</SectionTitle>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={hourlyChartData} margin={{top:0,right:0,left:-10,bottom:0}}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID}/>
              <XAxis dataKey="h" tick={{fontSize:10,fill:TEXT_MUTED}} interval={3}/>
              <YAxis tick={{fontSize:10,fill:TEXT_MUTED}}/>
              <Tooltip content={<CustomTooltip prefix="$" suffix=" MXN"/>}/>
              <Bar dataKey="cost" name="Costo MXN" radius={[2,2,0,0]}>
                {hourlyChartData.map((d,i) => <Cell key={i} fill={TARIFF_COLORS[d.tariff]} opacity={0.9}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div style={{display:'flex',gap:16,marginTop:10}}>
            {Object.entries(TARIFF_COLORS).map(([k,v]) => (
              <span key={k} style={{fontSize:11,color:TEXT_SECONDARY,display:'flex',alignItems:'center',gap:6}}>
                <span style={{width:8,height:8,borderRadius:2,background:v,display:'inline-block'}}/>
                {k.charAt(0).toUpperCase()+k.slice(1)}
              </span>
            ))}
          </div>
        </Card>
        <Card>
          <SectionTitle sub="Distribución por periodo tarifario">Costo por Tarifa</SectionTitle>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie data={tariffData} dataKey="cost" nameKey="name" cx="50%" cy="50%" innerRadius={52} outerRadius={74} paddingAngle={1} stroke="none">
                {tariffData.map((d,i) => <Cell key={i} fill={Object.values(TARIFF_COLORS)[i]}/>)}
              </Pie>
              <Tooltip formatter={(v) => `$${v.toLocaleString()} MXN`}/>
            </PieChart>
          </ResponsiveContainer>
          {tariffData.map((d,i) => (
            <div key={i} style={{display:'flex',justifyContent:'space-between',padding:'5px 0',borderTop:`1px solid ${BORDER_SOFT}`,fontSize:12}}>
              <span style={{display:'flex',alignItems:'center',gap:7,color:TEXT_SECONDARY}}>
                <span style={{width:8,height:8,borderRadius:2,background:Object.values(TARIFF_COLORS)[i],display:'inline-block'}}/>
                {d.name}
              </span>
              <span style={{color:'#f5f7fa',fontWeight:600}}>${d.cost.toLocaleString()}</span>
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
                  <stop offset="5%" stopColor={ACCENT} stopOpacity={0.22}/>
                  <stop offset="95%" stopColor={ACCENT} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID}/>
              <XAxis dataKey="day" tick={{fontSize:11,fill:TEXT_MUTED}}/>
              <YAxis tick={{fontSize:10,fill:TEXT_MUTED}}/>
              <Tooltip content={<CustomTooltip prefix="$" suffix=" MXN"/>}/>
              <Area type="monotone" dataKey="cost" name="Costo MXN" stroke={ACCENT_QUIET} fill="url(#gc)" strokeWidth={1.5} dot={false} activeDot={{r:3,strokeWidth:0}}/>
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card>
          <SectionTitle sub="Edificios actualmente monitoreados">Costo por Edificio · Semana</SectionTitle>
          <div style={{marginTop:8}}>
            {buildingChartData.length === 0 ? (
              <div style={{background:'#121417',borderRadius:10,padding:'12px 14px',fontSize:13,color:'#9aa4af'}}>
                Sin datos reales de edificios todavía.
              </div>
            ) : buildingChartData.map((d,i) => (
              <div key={i} style={{marginBottom:16}}>
                <div style={{display:'flex',justifyContent:'space-between',marginBottom:6,fontSize:13}}>
                  <span style={{color:'#c3cbd4'}}>{d.b}</span>
                  <span style={{color:'#f5f7fa',fontWeight:500}}>${Number(d.cost || 0).toLocaleString("es-MX")} MXN</span>
                </div>
                <div style={{height:6,background:SURFACE_INNER,border:`1px solid ${BORDER_SOFT}`,borderRadius:3,overflow:'hidden'}}>
                  <div style={{height:'100%',width:`${d.pct}%`,background:ACCENT,borderRadius:3}}/>
                </div>
                <div style={{fontSize:11,color:TEXT_MUTED}}>{Number(d.kwh || 0).toFixed(4)} kWh</div>
              </div>
            ))}
            <div style={{background:'#121417',borderRadius:10,padding:'12px 14px',marginTop:16}}>
              <div style={{fontSize:11,color:TEXT_MUTED,marginBottom:4}}>6 edificios sin monitoreo</div>
              <div style={{fontSize:13,color:'#9aa4af'}}>Asignar nodos para ampliar cobertura</div>
            </div>
          </div>
        </Card>
      </div>
      <SmartPlugDashboardWidget deploymentId={selectedDeploymentId}/>
      <AIInsightCard
        insights={scopedAnomalies?.anomalies || []}
        archived={selectedDeployment ? !isLive(selectedDeployment) : false}
      />
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
                <div style={{fontSize:15,fontWeight:600,color:'#f5f7fa'}}>{campus.name}</div>
                <div style={{fontSize:11,color:'#9aa4af'}}>{campus.delegation}</div>
                <div style={{fontSize:11,color:'#9aa4af',marginTop:3}}>
                  {campus.monitored_buildings}/{campus.total_buildings} edificios monitoreados
                </div>
              </div>
              <Badge color={campus.status === "active" ? "#22c55e" : "#6b7280"}>
                {campus.status === "active" ? "Activo" : "Sin datos"}
              </Badge>
            </div>

            <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:12}}>
              <div>
                <div style={{fontSize:10,color:TEXT_MUTED,textTransform:'uppercase',letterSpacing:.8}}>Potencia</div>
                <div style={{fontSize:19,fontWeight:600,color:'#f5f7fa'}}>{Number(campus.power_kw || 0).toFixed(2)} kW</div>
              </div>
              <div>
                <div style={{fontSize:10,color:TEXT_MUTED,textTransform:'uppercase',letterSpacing:.8}}>Energía hoy</div>
                <div style={{fontSize:19,fontWeight:600,color:'#f5f7fa'}}>{Number(campus.energy_today_kwh || 0).toFixed(3)} kWh</div>
              </div>
              <div>
                <div style={{fontSize:10,color:TEXT_MUTED,textTransform:'uppercase',letterSpacing:.8}}>Costo hoy</div>
                <div style={{fontSize:19,fontWeight:600,color:ACCENT_QUIET}}>${Number(campus.cost_today_mxn || 0).toLocaleString("es-MX")} MXN</div>
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
                background:SURFACE_INNER,
                border:`1px solid ${BORDER}`,
                borderLeft:`2px solid ${color}`,
                borderRadius:8,
                padding:16,
                minHeight:156,
              }}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:14}}>
                  <Icon name="Building" size={20} color={ACCENT_QUIET}/>
                  <StatusDot status={building.anomaly ? "warning" : isActive ? "online" : "offline"}/>
                </div>

                <div style={{fontSize:13,fontWeight:600,color:'#f5f7fa',marginBottom:3}}>{building.name}</div>
                <div style={{fontSize:11,color:'#9aa4af',marginBottom:10}}>{building.campus}</div>

                {isActive ? (
                  <>
                    <div style={{fontSize:15,fontWeight:600,color:ACCENT_QUIET}}>{Number(building.power_kw || 0).toFixed(2)} kW</div>
                    <div style={{fontSize:11,color:'#9aa4af'}}>${Number(building.cost_today_mxn || 0).toLocaleString("es-MX")} MXN hoy</div>
                    <div style={{fontSize:11,color:'#9aa4af'}}>{Number(building.energy_today_kwh || 0).toFixed(4)} kWh</div>
                    {building.anomaly && (
                      <div style={{display:'inline-block',marginTop:8,padding:'2px 7px',background:'#ef444414',border:'1px solid #ef444433',borderRadius:4,color:'#ef4444',fontSize:10,fontWeight:500}}>
                        Anomalía
                      </div>
                    )}
                  </>
                ) : (
                  <div style={{fontSize:12,color:TEXT_MUTED}}>Sin lecturas reales</div>
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
          <select value={campusFilter} onChange={(e) => setCampusFilter(e.target.value)} style={{background:SURFACE_INNER,color:TEXT,border:`1px solid ${BORDER}`,borderRadius:6,padding:'8px 11px',fontSize:13}}>
            <option value="all">Todos los campus</option>
            {campuses.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{background:SURFACE_INNER,color:TEXT,border:`1px solid ${BORDER}`,borderRadius:6,padding:'8px 11px',fontSize:13}}>
            <option value="all">Todos los estados</option>
            <option value="monitored">Monitoreado</option>
            <option value="no_data">Sin lecturas</option>
            <option value="anomaly">Con anomalía</option>
          </select>
        </div>
        <div style={{fontSize:12,color:'#9aa4af'}}>{filteredBuildings.length} edificios</div>
      </div>

      <Card>
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse',fontSize:12.5}}>
            <thead>
              <tr style={{color:TEXT_MUTED,fontSize:10.5,textTransform:'uppercase',letterSpacing:.7,fontWeight:500}}>
                <th align="left" style={TH}>Edificio</th>
                <th align="left" style={TH}>Unidad</th>
                <th align="left" style={TH}>Campus</th>
                <th align="left" style={TH}>Estado</th>
                <th align="left" style={TH}>Potencia</th>
                <th align="left" style={TH}>Energía hoy</th>
                <th align="left" style={TH}>Costo hoy</th>
                <th align="left" style={TH}>Anomalía</th>
              </tr>
            </thead>

            <tbody>
              {filteredBuildings.map((b) => (
                <tr key={b.id} style={{borderTop:`1px solid ${BORDER_SOFT}`}}>
                  <td style={{...TD,paddingTop:9,paddingBottom:9}}>
                    <div style={{fontWeight:500,color:TEXT}}>{b.name}</div>
                    <div style={{fontSize:11,color:TEXT_MUTED,marginTop:1}}>{b.delegation}</div>
                  </td>

                  <td style={{...TD,color:TEXT_SECONDARY}}>{b.organizational_unit}</td>
                  <td style={{...TD,color:TEXT_SECONDARY}}>{b.campus}</td>

                  <td style={TD}>
                    <span style={{
                      color:b.status === 'monitored' ? '#22c55e' : TEXT_MUTED,
                      fontWeight:500,
                      fontSize:12
                    }}>
                      {b.status === 'monitored' ? 'Monitoreado' : 'Sin lecturas'}
                    </span>
                  </td>

                  <td style={{...TD,fontWeight:500,color:TEXT}}>
                    {Number(b.power_kw || 0).toFixed(2)} kW
                  </td>

                  <td style={{...TD,color:TEXT_SECONDARY}}>
                    {Number(b.energy_today_kwh || 0).toFixed(4)} kWh
                  </td>

                  <td style={{...TD,fontWeight:500,color:TEXT}}>
                    ${Number(b.cost_today_mxn || 0).toLocaleString('es-MX')} MXN
                  </td>

                  <td style={TD}>
                    {b.anomaly ? (
                      <span style={{background:'#ef444414',color:'#ef4444',border:'1px solid #ef444433',padding:'2px 7px',borderRadius:4,fontSize:11,fontWeight:500}}>
                        Sí
                      </span>
                    ) : <span style={{color:TEXT_MUTED}}>—</span>}
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
  const [finishingDeploymentId, setFinishingDeploymentId] = useState(null);

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

  const handleFinishDeployment = async (deployment) => {
    try {
      setFinishingDeploymentId(deployment.id);

      const check = await finishDeployment(deployment.id, true);

      if (!check.ok) {
        alert(`No se puede finalizar todavía: ${check.reason || "validación fallida"}\nBuffer pendiente: ${check.buffer_pending ?? "N/A"}`);
        return;
      }

      const confirmed = window.confirm(
        `Finalizar despliegue?\n\nNodo: ${check.node_id}\nEdificio: ${check.building}\nLecturas preservadas: ${Number(check.reading_count || 0).toLocaleString("es-MX")}\nBuffer pendiente: ${check.buffer_pending}\n\nEsto marcará el despliegue como completado y el nodo como disponible.`
      );

      if (!confirmed) return;

      const result = await finishDeployment(deployment.id, false);

      if (!result.ok) {
        alert(`No se pudo finalizar: ${result.reason || "error desconocido"}`);
        return;
      }

      alert("Despliegue finalizado correctamente. Los datos históricos fueron preservados.");
      loadBase();
    } catch (error) {
      console.error("Finish deployment API error:", error);
      alert("No se pudo finalizar el despliegue.");
    } finally {
      setFinishingDeploymentId(null);
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
                <div style={{background:SURFACE_INNER,border:`1px solid ${BORDER}`,borderRadius:6,padding:'7px 10px',color:TEXT_SECONDARY,fontWeight:500,fontSize:11,letterSpacing:.5}}>NODE</div>
                <div>
                  <div style={{fontWeight:600,color:'#f5f7fa'}}>{node.name}</div>
                  <div style={{fontSize:11,color:'#9aa4af'}}>{node.ip || "Sin IP"}</div>
                </div>
              </div>
              <Badge color={node.status === "online" ? "#22c55e" : "#6b7280"}>{node.status}</Badge>
            </div>

            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12,fontSize:12}}>
              <div>
                <div style={{color:TEXT_MUTED}}>Despliegue actual</div>
                {node.current_deployment ? (
                  <b>{node.current_deployment.building_name} · {node.current_deployment.electrical_panel}</b>
                ) : (
                  <b style={{color:'#9aa4af'}}>Sin despliegue activo</b>
                )}
                {!node.current_deployment && node.last_completed_deployment && (
                  <div style={{fontSize:11,color:'#6b7580',marginTop:2}}>
                    Último: {node.last_completed_deployment.building_name}
                  </div>
                )}
              </div>
              <div><div style={{color:TEXT_MUTED}}>Última sincronía</div><b>{fmtSync(node.last_sync)}</b></div>
              <div><div style={{color:TEXT_MUTED}}>Muestras</div><b>{Number(node.samples || 0).toLocaleString("es-MX")}</b></div>
              <div><div style={{color:TEXT_MUTED}}>Buffer</div><b>{Number(node.buffer_pending || 0)} reg. pend.</b></div>
              <div><div style={{color:TEXT_MUTED}}>Raspberry</div><b>{node.status === "online" ? "OK" : "Sin datos"}</b></div>
              <div><div style={{color:TEXT_MUTED}}>Shelly</div><b>{node.status === "online" ? "OK" : "Sin datos"}</b></div>
            </div>
          </Card>
        ))}

        <SectionTitle title="Despliegues Pasados" subtitle="Historial real de despliegues cerrados"/>
        {pastDeployments.length === 0 ? (
          <Card>
            <div style={{fontSize:13,color:'#9aa4af'}}>No hay despliegues pasados registrados todavía.</div>
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
            <div style={{fontSize:12,color:'#9aa4af',marginTop:6}}>
              {deployment.node_id} · {deployment.start_date} – {deployment.end_date}
            </div>
          </Card>
        ))}
      </div>

      <div>
        <SectionTitle title="En Curso" subtitle="Despliegues activos desde backend"/>
        {activeDeployments.length === 0 ? (
          <Card style={{marginBottom:14}}>
            <div style={{fontSize:13,color:'#9aa4af'}}>No hay despliegues activos.</div>
          </Card>
        ) : activeDeployments.map((deployment) => (
          <Card key={deployment.id} style={{marginBottom:14}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
              <div>
                <div style={{fontSize:16,fontWeight:600,color:'#f5f7fa'}}>{deployment.building_name}</div>
                <div style={{fontSize:12,color:'#9aa4af'}}>
                  {deployment.node_id} · {deployment.electrical_panel}
                </div>
              </div>
              <div style={{display:'flex',gap:8,alignItems:'center'}}>
                <Badge color="#22c55e">Activo</Badge>
                <button
                  onClick={() => handleFinishDeployment(deployment)}
                  disabled={finishingDeploymentId === deployment.id}
                  style={{
                    background:'transparent',
                    border:'1px solid #ef444455',
                    color:'#ef4444',
                    borderRadius:6,
                    padding:'6px 12px',
                    fontSize:12,
                    fontWeight:500,
                    cursor: finishingDeploymentId === deployment.id ? 'not-allowed' : 'pointer'
                  }}
                >
                  {finishingDeploymentId === deployment.id ? 'Validando...' : 'Finalizar'}
                </button>
              </div>
            </div>

            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:12,fontSize:12,marginBottom:14}}>
              <div><div style={{color:TEXT_MUTED}}>Unidad</div><b>{deployment.organizational_unit}</b></div>
              <div><div style={{color:TEXT_MUTED}}>Inicio</div><b>{deployment.start_date}</b></div>
              <div><div style={{color:TEXT_MUTED}}>Fin</div><b>{deployment.end_date}</b></div>
            </div>

            <div style={{background:'#121417',borderRadius:8,padding:'9px 12px',fontSize:12,color:'#9aa4af'}}>
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
        <div style={{display:'flex',alignItems:'center',gap:7,background:'#22c55e14',border:'1px solid #22c55e33',borderRadius:4,padding:'4px 10px'}}>
          <div style={{width:7,height:7,borderRadius:'50%',background:'#22c55e',animation:'pulse 2.4s ease-in-out infinite'}}/>
          <span style={{fontSize:11,color:'#22c55e',fontWeight:500,letterSpacing:.3}}>EN VIVO</span>
        </div>
        <span style={{fontSize:11.5,color:TEXT_MUTED}}>Actualización cada 3s · Datos desde /api/metrics/live</span>
      </div>

      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}`}</style>

      {metrics.length === 0 ? (
        <Card>
          <div style={{fontSize:13,color:'#9aa4af'}}>No hay nodos con métricas reales todavía.</div>
        </Card>
      ) : metrics.map((n) => (
        <Card key={n.node_id} style={{marginBottom:18}} glow={n.status === "online"}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
            <div style={{display:'flex',alignItems:'center',gap:12}}>
              <div style={{
                background:SURFACE_INNER,
                border:`1px solid ${BORDER}`,
                borderRadius:6,
                padding:'7px 10px',
                fontSize:11,
                color:TEXT_SECONDARY,
                fontWeight:500,
                letterSpacing:.5
              }}>
                NODE
              </div>
              <div>
                <div style={{fontSize:15,fontWeight:500,color:'#f5f7fa'}}>{n.node_id}</div>
                <div style={{fontSize:11,color:TEXT_MUTED}}>
                  {n.last_reading_building || "Lectura sin edificio"} · Última lectura {n.latest_reading ? new Date(n.latest_reading).toLocaleString("es-MX") : "sin datos"}
                </div>
              </div>
            </div>
            <Badge color={n.status === "online" ? "#22c55e" : "#6b7280"}>
              {n.status === "online" ? "Real API" : "Offline"}
            </Badge>
          </div>

          <div style={{display:'flex',flexWrap:'wrap',gap:12}}>
            {[
              {l:'Tensión (V)',v:Number(n.voltage || 0).toFixed(1),c:'#2563eb',unit:'V'},
              {l:'Corriente (A)',v:Number(n.current || 0).toFixed(2),c:'#f59e0b',unit:'A'},
              {l:'Potencia (kW)',v:Number(n.power_kw || 0).toFixed(3),c:'#ef4444',unit:'kW'},
              {l:'Factor de Potencia',v:Number(n.power_factor || 0).toFixed(3),c:'#22c55e',unit:''},
              {l:'Frecuencia (Hz)',v:Number(n.frequency_hz || 0).toFixed(2),c:'#3b82f6',unit:'Hz'},
              {l:'Energía Hoy',v:Number(n.energy_today_kwh || 0).toFixed(3),c:ACCENT_QUIET,unit:'kWh'}
            ].map((m,i) => (
              <div key={i} style={{
                background:SURFACE_INNER, borderRadius:8, padding:'13px 15px',
                flex:1, minWidth:120, border:`1px solid ${BORDER}`
              }}>
                <div style={{fontSize:10,color:TEXT_MUTED,textTransform:'uppercase',letterSpacing:.7,marginBottom:7}}>{m.l}</div>
                <div style={{fontSize:22,fontWeight:600,color:TEXT,letterSpacing:-0.4,fontVariantNumeric:'tabular-nums'}}>{m.v}</div>
                <div style={{fontSize:11,color:TEXT_MUTED,marginTop:3}}>{m.unit}</div>
              </div>
            ))}
          </div>

          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:10,marginTop:12}}>
            {[
              {l:'RPi Status',v:n.rpi_status === "ok" ? "OK" : "Offline",c:n.rpi_status === "ok" ? '#22c55e' : '#6b7280'},
              {l:'Shelly Status',v:n.shelly_status === "ok" ? "OK" : "Offline",c:n.shelly_status === "ok" ? '#22c55e' : '#6b7280'},
              {l:'Buffer',v:`${Number(n.buffer_pending || 0)} pend.`,c:Number(n.buffer_pending || 0)>0?'#f59e0b':'#22c55e'}
            ].map((item,i) => (
              <div key={i} style={{background:'#0e1114',borderRadius:8,padding:'8px 12px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                <span style={{fontSize:11,color:TEXT_MUTED}}>{item.l}</span>
                <span style={{fontSize:12,fontWeight:500,color:item.c}}>{item.v}</span>
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
};


// ─── PAGE: COST ANALYTICS ─────────────────────────────────────────────────────
const PageCost = ({ cfeStatus }) => {
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
        <StatCard label="Proyección mensual" value={mxn(summary?.projected_month_mxn)} sub="Extrapolación simple" color="#3b82f6" icon="TrendingUp"/>
        <StatCard label="Costo por punta" value={`${Number(peakShare || 0).toFixed(1)}%`} sub="Participación real actual" color="#ef4444" icon="Zap"/>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'2fr 1fr',gap:18,marginBottom:22}}>
        <Card>
          <SectionTitle title="Análisis por Periodo Tarifario" subtitle="Desglose real por periodo tarifario GDMTH"/>
          {periods.length === 0 ? (
            <div style={{fontSize:13,color:'#9aa4af'}}>Sin consumo real registrado todavía.</div>
          ) : periods.map((p, i) => {
            const color = p.period === "peak" ? "#ef4444" : p.period === "intermediate" ? "#f59e0b" : "#2563eb";
            const label = p.period === "peak" ? "Punta" : p.period === "intermediate" ? "Intermedia" : "Base";
            const width = Math.max(2, (Number(p.cost_mxn || 0) / totalCost) * 100);

            return (
              <div key={i} style={{marginBottom:22}}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
                  <div style={{display:'flex',alignItems:'center',gap:8}}>
                    <div style={{width:10,height:10,borderRadius:2,background:color}}/>
                    <b>{label}</b>
                  </div>
                  <div style={{fontWeight:600,color}}>{mxn(p.cost_mxn)}</div>
                </div>
                <div style={{height:6,background:SURFACE_INNER,border:`1px solid ${BORDER_SOFT}`,borderRadius:3,overflow:'hidden'}}>
                  <div style={{height:'100%',width:`${width}%`,background:color,borderRadius:3}}/>
                </div>
                <div style={{display:'flex',justifyContent:'space-between',fontSize:11,color:'#9aa4af',marginTop:6}}>
                  <span>{Number(p.share_pct || 0).toFixed(1)}% del costo total</span>
                  <span>{Number(p.kwh || 0).toFixed(4)} kWh</span>
                </div>
              </div>
            );
          })}
        </Card>

        <Card>
          <SectionTitle title="Tarifa Activa" subtitle="Fuente: configuración local"/>
          <div style={{fontSize:24,fontWeight:600,color:ACCENT_QUIET,marginBottom:4}}>GDMTH</div>
          <div style={{fontSize:12,color:'#9aa4af',marginBottom:22}}>Gran Demanda en Media Tensión H</div>

          {[
            ["Base", rates.base],
            ["Intermedia", rates.intermediate],
            ["Punta", rates.peak],
          ].map(([name, value]) => (
            <div key={name} style={{display:'flex',justifyContent:'space-between',fontSize:13,marginBottom:14}}>
              <span style={{color:'#9aa4af'}}>Cargo {name}</span>
              <b>${Number(value || 0).toFixed(2)}/kWh</b>
            </div>
          ))}

          <div style={{display:'flex',justifyContent:'space-between',fontSize:13,marginTop:20}}>
            <span style={{color:'#9aa4af'}}>Estado CFE API</span>
            <b>{cfeStatus?.label || "Manual fallback"}</b>
          </div>
        </Card>
      </div>

      <Card>
        <SectionTitle title="Simulador de Ahorro" subtitle="Deshabilitado hasta contar con histórico suficiente"/>
        <div style={{background:'#121417',borderRadius:12,padding:18,color:'#9aa4af',fontSize:13}}>
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
      <div style={{display:'flex',gap:3,background:SURFACE_INNER,border:`1px solid ${BORDER}`,padding:3,borderRadius:8,width:'fit-content',marginBottom:20}}>
        {tabs.map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} style={{
            background:tab === key ? SURFACE : 'transparent',
            color:tab === key ? TEXT : TEXT_SECONDARY,
            border:0,
            borderRadius:5,
            padding:'7px 16px',
            fontSize:12.5,
            fontWeight:500,
            boxShadow:tab === key ? `inset 0 -2px 0 ${ACCENT}` : 'none',
            cursor:'pointer',
          }}>
            {label}
          </button>
        ))}
      </div>

      {tab === "forecast" && (
        <>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:16,marginBottom:18}}>
            <StatCard label="Proyección mañana" value={mxn(forecast.tomorrow_mxn)} sub={`Confianza ${(Number(forecast.confidence || 0) * 100).toFixed(0)}%`} color="#2563eb" icon="ArrowRight"/>
            <StatCard label="Proyección semana" value={mxn(forecast.week_mxn)} sub="Basado en consumo real" color="#3b82f6" icon="BarChart"/>
            <StatCard label="Proyección mensual" value={mxn(forecast.month_mxn)} sub="Tendencia actual" color="#f59e0b" icon="TrendingUp"/>
          </div>

          <Card>
            <SectionTitle title="Pronóstico de Costo (MXN)" subtitle={`${forecast.method || "Modelo basado en datos reales"} · intervalo de confianza dinámico`}/>
            <div style={{height:240,border:'1px solid #252a31',borderRadius:12,padding:16}}>
              <svg width="100%" height="200" viewBox="0 0 600 200" preserveAspectRatio="none">
                <line x1="0" y1="180" x2="600" y2="180" stroke={BORDER}/>
                <line x1="0" y1="120" x2="600" y2="120" stroke={BORDER_SOFT} strokeDasharray="3 4"/>
                <line x1="0" y1="60" x2="600" y2="60" stroke={BORDER_SOFT} strokeDasharray="3 4"/>
                {(() => {
                  const pts = forecast.points || [];
                  const max = Math.max(...pts.map(p => p.value || 0), 1);
                  const points = pts.map((p, i) => `${(i / Math.max(pts.length - 1, 1)) * 600},${180 - ((p.value || 0) / max) * 150}`).join(" ");
                  return <polyline points={points} fill="none" stroke={ACCENT_QUIET} strokeWidth="1.75" strokeDasharray="6 4"/>;
                })()}
              </svg>
              <div style={{display:'flex',justifyContent:'space-between',fontSize:12,color:'#9aa4af'}}>
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
              <div style={{fontSize:13,color:'#9aa4af'}}>No hay anomalías activas con los datos actuales.</div>
            </Card>
          ) : anomalies.items.map((item, i) => (
            <Card key={i} style={{marginBottom:12,borderLeft:`4px solid ${item.color || '#2563eb'}`}}>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                <div>
                  <div style={{fontWeight:600,color:'#f5f7fa',marginBottom:4}}>{item.title}</div>
                  <div style={{fontSize:12,color:'#9aa4af'}}>{item.building} · {item.time}</div>
                  <div style={{fontSize:12,color:'#9aa4af',marginTop:10}}>
                    Detectado: <b style={{color:'#ef4444'}}>{item.detected}</b>
                    <span style={{marginLeft:18}}>Esperado: <b style={{color:'#22c55e'}}>{item.expected}</b></span>
                  </div>
                </div>
                <Badge color={item.color || '#2563eb'}>{item.severity}</Badge>
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
                  <div style={{fontSize:16,fontWeight:600,color:'#f5f7fa',marginTop:10}}>{rec.title}</div>
                  <div style={{fontSize:12,color:'#9aa4af',marginBottom:14}}>{rec.building}</div>
                  <div style={{fontSize:13,color:'#9aa4af',lineHeight:1.5}}>{rec.description}</div>
                  <div style={{marginTop:14,background:'#1c2126',borderRadius:8,padding:'9px 12px',fontSize:13,color:'#c3cbd4'}}>
                    → {rec.action}
                  </div>
                </div>
                <div style={{minWidth:120,textAlign:'right'}}>
                  <div style={{fontSize:11,color:'#9aa4af'}}>Ahorro estimado</div>
                  <div style={{fontSize:26,fontWeight:600,color:'#22c55e'}}>${Number(rec.saving_mxn_month || 0).toLocaleString("es-MX")}</div>
                  <div style={{fontSize:11,color:'#9aa4af'}}>MXN/mes</div>
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
                  background:msg.role === "user" ? ACCENT : SURFACE_INNER,
                  border:`1px solid ${msg.role === "user" ? ACCENT : BORDER}`,
                  borderRadius:8,
                  padding:'11px 13px',
                  fontSize:13,
                  lineHeight:1.55,
                  color:'#f5f7fa',
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
                  background:'#121417',
                  border:'1px solid #252a31',
                  color:'#f5f7fa',
                  borderRadius:8,
                  padding:'12px',
                }}
              />
              <button onClick={sendQuestion} style={{
                ...BTN_PRIMARY,
                padding:'0 22px',
              }}>
                Enviar
              </button>
            </div>
            <div style={{display:'flex',gap:6,marginTop:10,flexWrap:'wrap'}}>
              {["¿Qué edificio costó más esta semana?","¿Cuánto podemos ahorrar?","¿Hubo anomalías hoy?","Proyección de costo del mes"].map((q) => (
                <button key={q} onClick={() => setQuestion(q)} style={{
                  background:SURFACE_INNER,
                  border:`1px solid ${BORDER}`,
                  color:TEXT_SECONDARY,
                  borderRadius:4,
                  padding:'5px 10px',
                  fontSize:11,
                  fontWeight:400,
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
  const clusterColors = ["#2563eb", "#22c55e", "#ef4444", "#f59e0b", "#3b82f6"];

  const BlockTitle = ({title, subtitle}) => (
    <div style={{marginBottom:18}}>
      <div style={{fontSize:18,fontWeight:600,color:'#f5f7fa',marginBottom:4}}>{title}</div>
      <div style={{fontSize:12,color:'#9aa4af'}}>{subtitle}</div>
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
                border:`1px solid ${BORDER}`,
                borderLeft:`2px solid ${color}`,
                padding:'13px 15px',
                marginBottom:10,
                background:SURFACE_INNER,
                borderRadius:8,
              }}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
                  <div style={{fontWeight:600,color:'#f5f7fa'}}>{cluster.name}</div>
                  <Badge color={color}>{cluster.count} edificio{cluster.count === 1 ? "" : "s"}</Badge>
                </div>
                <div style={{fontSize:12,color:'#9aa4af',marginBottom:8}}>{cluster.description}</div>
                <div style={{display:'flex',gap:6,flexWrap:'wrap'}}>
                  {(cluster.buildings || []).length === 0 ? (
                    <span style={{fontSize:12,color:TEXT_MUTED}}>Sin edificios clasificados todavía</span>
                  ) : cluster.buildings.map((name) => (
                    <span key={name} style={{
                      border:`1px solid ${color}33`,
                      color,
                      borderRadius:4,
                      padding:'2px 7px',
                      fontSize:11,
                      fontWeight:500,
                      background:`${color}14`,
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
              <div style={{height:210,border:'1px solid #252a31',borderRadius:12,padding:14,marginBottom:14}}>
                <svg width="100%" height="170" viewBox="0 0 500 170" preserveAspectRatio="none">
                  <line x1="0" y1="150" x2="500" y2="150" stroke={BORDER} />
                  <line x1="0" y1="100" x2="500" y2="100" stroke={BORDER_SOFT} strokeDasharray="3 4" />
                  <line x1="0" y1="50" x2="500" y2="50" stroke={BORDER_SOFT} strokeDasharray="3 4" />
                  {(() => {
                    const a = correlation.series_a || [];
                    const b = correlation.series_b || [];
                    const vals = [...a.map(x => x.value), ...b.map(x => x.value)];
                    const max = Math.max(...vals, 1);
                    const pointsA = a.map((x, i) => `${(i / Math.max(a.length - 1, 1)) * 500},${150 - (x.value / max) * 130}`).join(" ");
                    const pointsB = b.map((x, i) => `${(i / Math.max(b.length - 1, 1)) * 500},${150 - (x.value / max) * 130}`).join(" ");
                    return (
                      <>
                        <polyline points={pointsA} fill="none" stroke={ACCENT_QUIET} strokeWidth="1.75"/>
                        <polyline points={pointsB} fill="none" stroke="#22c55e" strokeWidth="1.75" strokeDasharray="5 4"/>
                      </>
                    );
                  })()}
                </svg>
              </div>
              <div style={{fontSize:13,color:'#9aa4af'}}>
                Coeficiente de correlación Pearson: <b style={{color:ACCENT_QUIET}}>{Number(correlation.coefficient || 0).toFixed(2)}</b>
              </div>
            </>
          ) : (
            <div style={{height:210,display:'flex',alignItems:'center',justifyContent:'center',border:'1px solid #252a31',borderRadius:12,color:'#9aa4af',fontSize:13,textAlign:'center',padding:20}}>
              {correlation.message || "Se requieren al menos 2 edificios con lecturas reales."}
            </div>
          )}
        </Card>
      </div>

      <Card style={{marginBottom:18}}>
        <BlockTitle title="Descubrimiento de Patrones" subtitle="Patrones descubiertos por el motor de minería de datos"/>
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(210px,1fr))',gap:14}}>
          {patterns.map((pattern, i) => {
            const color = pattern.severity === "high" ? "#ef4444" : pattern.severity === "warning" ? "#f59e0b" : pattern.severity === "medium" ? "#3b82f6" : "#2563eb";
            return (
              <div key={i} style={{
                border:`1px solid ${BORDER}`,
                borderTop:`2px solid ${color}`,
                borderRadius:8,
                padding:14,
                background:SURFACE_INNER,
              }}>
                <div style={{marginBottom:12}}>
                  <Icon name={pattern.severity === "high" ? "TrendingUp" : pattern.severity === "warning" ? "Zap" : "Database"} size={18} color={color}/>
                </div>
                <div style={{fontWeight:600,color:'#f5f7fa',marginBottom:4}}>{pattern.title}</div>
                <div style={{fontSize:12,color:ACCENT_QUIET,marginBottom:8}}>{pattern.building}</div>
                <div style={{fontSize:12,color:'#9aa4af',lineHeight:1.45}}>{pattern.description}</div>
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
  const API_ORIGIN = `${window.location.protocol}//${window.location.hostname}:8010`;
  const API = `${API_ORIGIN}/api/reports`;
  const download = (path) => window.open(`${API}${path}`, "_blank");

  const [deploymentReports, setDeploymentReports] = useState([]);
  const [generatingId, setGeneratingId] = useState(null);
  const [deploymentSearch, setDeploymentSearch] = useState("");
  const [deploymentStatusFilter, setDeploymentStatusFilter] = useState("all");

  const loadDeploymentReports = () => {
    getDeploymentReports()
      .then(setDeploymentReports)
      .catch((error) => console.error("Deployment reports API error:", error));
  };

  useEffect(() => {
    loadDeploymentReports();
  }, []);

  const handleGenerateDeploymentReport = async (deploymentId) => {
    try {
      setGeneratingId(deploymentId);
      await generateDeploymentReport(deploymentId);
      alert("Reporte generado y guardado correctamente.");
      loadDeploymentReports();
    } catch (error) {
      console.error("Generate deployment report error:", error);
      alert("No se pudo generar el reporte.");
    } finally {
      setGeneratingId(null);
    }
  };

  const filteredDeploymentReports = deploymentReports.filter((deployment) => {
    const search = deploymentSearch.trim().toLowerCase();
    const statusOk = deploymentStatusFilter === "all" || deployment.status === deploymentStatusFilter;

    const text = [
      deployment.id,
      deployment.node_id,
      deployment.building_name,
      deployment.campus,
      deployment.organizational_unit,
      deployment.electrical_panel,
      deployment.status,
      deployment.real_start,
      deployment.real_end,
    ].join(" ").toLowerCase();

    return statusOk && (!search || text.includes(search));
  });

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
        <button onClick={() => download("/raw-readings.pdf")} style={BTN_PRIMARY}>Exportar PDF</button>
        <button onClick={() => download("/dataset.csv")} style={BTN_SECONDARY}>Exportar CSV</button>
        <button onClick={() => download("/dataset.xlsx")} style={BTN_SECONDARY}>Exportar Excel</button>
      </div>

      <Card style={{marginBottom:24}}>
        <SectionTitle title="Reportes por Despliegue" subtitle="Exportar campañas específicas por nodo, edificio y periodo"/>
        <div style={{display:'grid',gridTemplateColumns:'1fr 220px',gap:12,marginBottom:14}}>
          <input
            value={deploymentSearch}
            onChange={(e) => setDeploymentSearch(e.target.value)}
            placeholder="Buscar por nodo, edificio, campus, estado..."
            style={{background:'#121417',border:'1px solid #252a31',color:'#f5f7fa',borderRadius:10,padding:'10px 12px'}}
          />
          <select
            value={deploymentStatusFilter}
            onChange={(e) => setDeploymentStatusFilter(e.target.value)}
            style={{background:'#121417',border:'1px solid #252a31',color:'#f5f7fa',borderRadius:10,padding:'10px 12px'}}
          >
            <option value="all">Todos los estados</option>
            <option value="active">Activos</option>
            <option value="completed">Completados</option>
            <option value="historico">Históricos</option>
            <option value="failed">Fallidos</option>
          </select>
        </div>

        {deploymentReports.length === 0 ? (
          <div style={{fontSize:13,color:'#9aa4af'}}>No hay despliegues registrados todavía.</div>
        ) : filteredDeploymentReports.length === 0 ? (
          <div style={{fontSize:13,color:'#9aa4af'}}>No hay despliegues que coincidan con el filtro.</div>
        ) : (
          <div style={{display:'grid',gap:12,maxHeight:520,overflowY:'auto',paddingRight:6}}>
            {filteredDeploymentReports.map((deployment) => (
              <div key={deployment.id} style={{
                border:'1px solid #252a31',
                borderRadius:12,
                padding:14,
                background:'#121417',
                display:'grid',
                gridTemplateColumns:'1fr auto',
                gap:14,
                alignItems:'center'
              }}>
                <div>
                  <div style={{fontWeight:600,color:'#f5f7fa',marginBottom:4}}>
                    Despliegue #{deployment.id} · {deployment.building_name}
                  </div>
                  <div style={{fontSize:12,color:'#9aa4af',lineHeight:1.5}}>
                    {deployment.node_id} · {deployment.electrical_panel}
                    <br/>
                    Periodo real: {deployment.real_start || deployment.start_date} → {deployment.real_end || deployment.end_date}
                    <br/>
                    Planeado: {deployment.start_date} – {deployment.end_date}
                    <br/>
                    {Number(deployment.reading_count || 0).toLocaleString("es-MX")} lecturas reales · Estado: {deployment.status}
                  </div>
                </div>

                <div style={{display:'flex',gap:8,flexWrap:'wrap',justifyContent:'flex-end'}}>
                  <button onClick={() => download(deployment.pdf)} style={{...BTN_PRIMARY,padding:'7px 12px',fontSize:12}}>PDF</button>
                  <button onClick={() => download(deployment.csv)} style={{...BTN_SECONDARY,padding:'7px 12px',fontSize:12}}>CSV</button>
                  <button onClick={() => download(deployment.xlsx)} style={{...BTN_SECONDARY,padding:'7px 12px',fontSize:12}}>Excel</button>
                  <button
                    onClick={() => handleGenerateDeploymentReport(deployment.id)}
                    disabled={generatingId === deployment.id}
                    style={{...BTN_SECONDARY,padding:'7px 12px',fontSize:12,cursor:generatingId === deployment.id ? 'not-allowed' : 'pointer'}}
                  >
                    {generatingId === deployment.id ? 'Generando...' : 'Guardar'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(330px,1fr))',gap:16}}>
        {reports.map((report) => (
          <Card key={report.title}>
            <div style={{display:'flex',gap:16,alignItems:'flex-start'}}>
              <div style={{
                width:38,height:38,borderRadius:8,background:SURFACE_INNER,
                border:`1px solid ${BORDER}`,display:'flex',alignItems:'center',
                justifyContent:'center',flexShrink:0
              }}>
                <Icon name={report.icon} size={17} stroke={1.6} color={TEXT_SECONDARY}/>
              </div>

              <div style={{flex:1}}>
                <div style={{fontSize:16,fontWeight:600,color:'#f5f7fa',marginBottom:4}}>
                  {report.title}
                </div>
                <div style={{fontSize:12,color:'#9aa4af',marginBottom:18}}>
                  {report.type} · {report.date}
                </div>

                <div style={{display:'flex',alignItems:'center',justifyContent:'space-between'}}>
                  <Badge color={report.status === "Disponible" ? "#22c55e" : "#f59e0b"}>
                    {report.status}
                  </Badge>

                  <button
                    onClick={() => download(report.path)}
                    style={{...BTN_SECONDARY,padding:'7px 14px',fontSize:12}}
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
        <StatCard label="Muestras acumuladas" value={Number(summary.total_samples || 0).toLocaleString("es-MX")} sub="Reportadas por edge" color="#3b82f6" icon="BarChart"/>
        <StatCard label="Buffer pendiente" value={`${summary.buffer_pending || 0} reg.`} sub="Pendientes de sincronía" color="#f59e0b" icon="Clock"/>
        <StatCard label="Lecturas backend" value={Number(summary.total_readings || 0).toLocaleString("es-MX")} sub="En base de datos" color="#22c55e" icon="Database"/>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:14,marginBottom:18}}>
        {services.map((service, i) => (
          <Card key={i}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
              <div style={{display:'flex',alignItems:'center',gap:12}}>
                <div style={{border:`1px solid ${BORDER}`,background:SURFACE_INNER,borderRadius:8,padding:9,display:'flex'}}>
                  <Icon name={service.name.includes("Base") ? "Database" : service.name.includes("VPN") ? "Lock" : "Server"} size={16} stroke={1.6} color={TEXT_SECONDARY}/>
                </div>
                <div>
                  <div style={{fontWeight:600,color:'#f5f7fa'}}>{service.name}</div>
                  <div style={{fontSize:12,color:'#9aa4af'}}>{service.detail}</div>
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
            <div><div style={{color:TEXT_MUTED}}>IP</div><b>{node.ip || "Sin IP"}</b></div>
            <div><div style={{color:TEXT_MUTED}}>Estado</div><b style={{color:statusColor(node.status)}}>{node.status}</b></div>
            <div><div style={{color:TEXT_MUTED}}>Muestras</div><b>{Number(node.samples || 0).toLocaleString("es-MX")}</b></div>
            <div><div style={{color:TEXT_MUTED}}>Buffer</div><b>{Number(node.buffer_pending || 0)} pend.</b></div>
            <div><div style={{color:TEXT_MUTED}}>RPi Status</div><b>{node.rpi_status}</b></div>
            <div><div style={{color:TEXT_MUTED}}>Shelly Status</div><b>{node.shelly_status}</b></div>
            <div><div style={{color:TEXT_MUTED}}>Última Sync</div><b>{node.last_sync ? new Date(node.last_sync).toLocaleString("es-MX") : "Sin sync"}</b></div>
            <div>
              <div style={{color:TEXT_MUTED}}>Despliegue actual</div>
              <b>{node.current_deployment ? node.current_deployment.building_name : "Sin despliegue activo"}</b>
            </div>
            <div>
              <div style={{color:TEXT_MUTED}}>Último despliegue</div>
              <b>{node.last_completed_deployment ? node.last_completed_deployment.building_name : "—"}</b>
            </div>
          </div>

          <div style={{display:'grid',gridTemplateColumns:'repeat(5,1fr)',gap:12,fontSize:12,marginTop:14}}>
            <div><div style={{color:TEXT_MUTED}}>Voltaje</div><b>{node.voltage ? Number(node.voltage).toFixed(1) : "0.0"} V</b></div>
            <div><div style={{color:TEXT_MUTED}}>Corriente</div><b>{node.current ? Number(node.current).toFixed(2) : "0.00"} A</b></div>
            <div><div style={{color:TEXT_MUTED}}>Potencia</div><b>{node.power_kw ? Number(node.power_kw).toFixed(3) : "0.000"} kW</b></div>
            <div><div style={{color:TEXT_MUTED}}>FP</div><b>{node.power_factor ? Number(node.power_factor).toFixed(3) : "0.000"}</b></div>
            <div><div style={{color:TEXT_MUTED}}>Frecuencia</div><b>{node.frequency_hz ? Number(node.frequency_hz).toFixed(2) : "0.00"} Hz</b></div>
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
      fontWeight:600
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
            <span style={{color:'#9aa4af'}}>{label}</span>
            <b style={{color:'#f5f7fa'}}>{value}</b>
          </div>
        ))}
      </Card>

      <Card>
        <SectionTitle title="Tarifa Activa" subtitle="Valores reales usados por el motor de costos"/>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:18}}>
          <div>
            <div style={{fontSize:26,fontWeight:600,color:ACCENT_QUIET}}>GDMTH</div>
            <div style={{fontSize:12,color:'#9aa4af'}}>Gran Demanda en Media Tensión H · {tariffs.month || "JUN-26"}</div>
          </div>
          <Badge color={cfeStatus?.status === "ready" ? "#22c55e" : "#f59e0b"}>{cfeStatus?.label || tariffs.source || "Manual fallback"}</Badge>
        </div>

        {[
          ["Cargo Base", tariffs.base],
          ["Cargo Intermedia", tariffs.intermediate],
          ["Cargo Punta", tariffs.peak],
        ].map(([label, value]) => (
          <div key={label} style={{display:'flex',justifyContent:'space-between',marginBottom:13,fontSize:13}}>
            <span style={{color:'#9aa4af'}}>{label}</span>
            <b>${Number(value || 0).toFixed(4)}/kWh</b>
          </div>
        ))}

        <button disabled style={{
          width:'100%',
          marginTop:14,
          opacity:.55,
          cursor:'not-allowed',
          background:'#1c2126',
          border:'1px solid #252a31',
          color:'#3b82f6',
          borderRadius:8,
          padding:'9px 12px',
          fontWeight:500
        }}>
          Actualizar desde CFE API / scraper pendiente
        </button>
      </Card>

      <Card>
        <SectionTitle title="Selector de Rol" subtitle="Cambia la vista operativa del dashboard"/>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
          {["Administrador","Ejecutivo","Técnico","Investigador"].map((item) => (
            <button key={item} onClick={() => setRole(item)} style={{
              background:role === item ? '#14181c' : '#121417',
              border:`1px solid ${role === item ? '#3b82f6' : '#252a31'}`,
              color:role === item ? '#c3cbd4' : '#9aa4af',
              borderRadius:10,
              padding:'12px',
              fontWeight:600
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
            <span style={{color:'#9aa4af'}}>{label}</span>
            <b style={{color:value === "online" ? "#22c55e" : "#f5f7fa"}}>{value}</b>
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
            <span style={{color:'#9aa4af',fontSize:13}}>{label}</span>
            <input
              type="number"
              step={step}
              value={thresholds[key] ?? 0}
              onChange={(e) => updateThreshold(key, e.target.value)}
              style={{
                background:'#121417',
                border:'1px solid #252a31',
                color:'#f5f7fa',
                borderRadius:8,
                padding:'8px 10px',
                textAlign:'right'
              }}
            />
            <span style={{color:ACCENT_QUIET,fontSize:12,fontWeight:600}}>{unit}</span>
          </div>
        ))}

        <div style={{fontSize:11,color:'#9aa4af',marginTop:10}}>
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
            <div key={label} style={{background:'#121417',border:'1px solid #252a31',borderRadius:10,padding:12}}>
              <div style={{fontSize:11,color:'#9aa4af',marginBottom:6}}>{label}</div>
              <div style={{fontSize:22,fontWeight:600,color:'#f5f7fa'}}>{Number(value || 0).toLocaleString("es-MX")}</div>
            </div>
          ))}
        </div>
      </Card>

      <Card style={{gridColumn:'1 / -1'}}>
        <SectionTitle title="Nodos Registrados" subtitle="Estado real reportado por heartbeat"/>
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse'}}>
            <thead>
              <tr style={{fontSize:11,color:'#9aa4af',textTransform:'uppercase',letterSpacing:1}}>
                <th align="left" style={{padding:'0 0 12px'}}>Nodo</th>
                <th align="left" style={{padding:'0 0 12px'}}>Estado</th>
                <th align="left" style={{padding:'0 0 12px'}}>Última sincronía</th>
                <th align="left" style={{padding:'0 0 12px'}}>Buffer</th>
                <th align="left" style={{padding:'0 0 12px'}}>Muestras</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map((node) => (
                <tr key={node.id} style={{borderTop:'1px solid #252a31'}}>
                  <td style={{padding:'13px 0'}}>
                    <b>{node.id}</b>
                    <div style={{color:'#9aa4af',fontSize:12}}>{node.name}</div>
                  </td>
                  <td>{statusBadge(node.status)}</td>
                  <td style={{color:'#c3cbd4'}}>{node.last_sync ? new Date(node.last_sync).toLocaleString("es-MX") : "Sin sincronía"}</td>
                  <td style={{color:Number(node.buffer_pending || 0) > 0 ? "#f59e0b" : "#22c55e",fontWeight:600}}>
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
  const [isAuthenticated, setIsAuthenticated] = useState(() => localStorage.getItem("energy_auth") === "true");
  const [apiBuildings, setApiBuildings] = useState(null);
  const [apiNodes, setApiNodes] = useState(null);
  const [cfeStatus, setCfeStatus] = useState(null);
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
          building: node.current_deployment ? node.current_deployment.building_name : null,
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

    getCfeStatus()
      .then((data) => setCfeStatus(data))
      .catch((error) => console.error("CFE status API error:", error));

    getAnomalies()
      .then((data) => setApiAnomalies(data))
      .catch((error) => console.error("Anomalies API error:", error));
  }, []);

  const [page, setPage] = useState('dashboard');
  const [role, setRole] = useState(() => localStorage.getItem("energy_role") || 'Administrador');

  useEffect(() => {
    if (!canAccessPage(role, page)) {
      setPage(firstAllowedPage(role));
    }
  }, [role, page]);

  const handleLogin = (loginRole) => {
    setRole(loginRole);
    setIsAuthenticated(true);
  };

  if (!isAuthenticated) {
    return <LoginPage onLogin={handleLogin} />;
  }
  const activeNodesCount = (apiNodes || []).filter((node) => node.status === "online").length;
  const activeNodesText = `${activeNodesCount} nodo${activeNodesCount === 1 ? "" : "s"} activo${activeNodesCount === 1 ? "" : "s"}`;

  const renderPage = () => {
    if (!canAccessPage(role, page)) {
      return <PageDashboard/>;
    }

    switch(page) {
      case 'dashboard': return <PageDashboard/>;
      case 'campus': return <PageCampus/>;
      case 'buildings': return <PageBuildings/>;
      case 'buildingDetail': return <PageBuildings/>;
      case 'deployments': return <PageDeployments/>;
      case 'live': return <PageLive/>;
      case 'cost': return <PageCost cfeStatus={cfeStatus}/>;
      case 'ai': return <PageAI apiInsights={apiInsights} apiAnomalies={apiAnomalies}/>;
      case 'mining': return <PageMining/>;
      case 'dataExplorer': return <PageDataExplorer/>;
      case 'reports': return <PageReports/>;
      case 'infra': return <PageInfra/>;
      case 'smartplugs': return <PageSmartPlugs/>;
      case 'settings': return <PageSettingsNew role={role} setRole={setRole} settings={null} onLogout={() => { localStorage.clear(); window.location.reload(); }}/>
      default: return <PageDashboard/>;
    }
  };
  return (
    <div style={{display:'flex',minHeight:'100vh'}}>
      <Sidebar page={page} setPage={setPage} role={role} setRole={setRole}/>
      <div style={{marginLeft:230,flex:1,minHeight:'100vh',background:'#0b0d10'}}>
        <Topbar page={page} activeNodesText={activeNodesText}/>
        <main style={{padding:'22px 28px 40px'}}>
          {renderPage()}
        </main>
      </div>
    </div>
  );
};

export default App;

import PageDataExplorer from "./pages/PageDataExplorer";
import LoginPage from "./pages/LoginPage";
import PageSettingsNew from "./pages/PageSettings";
import PageSmartPlugs from "./pages/PageSmartPlugs";
import { SmartPlugDashboardWidget } from "./components/smartplugs/SmartPlugDashboardWidget";
import "./claude-app.css";
