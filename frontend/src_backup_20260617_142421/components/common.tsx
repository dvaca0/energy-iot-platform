import React from "react";
import { PURPLE, PURPLE_L, STATUS_COLORS, TOOLTIP_STYLE } from "../styles/theme";

export const Card = ({ children, style, glow, className }) => (
  <div style={{
    background:'#10101e', border:`1px solid #1e1b35`, borderRadius:14,
    padding:'18px 20px', position:'relative', overflow:'hidden',
    ...(glow ? {boxShadow:`0 0 24px 0 ${PURPLE}22`} : {}),
    ...style
  }} className={className}>{children}</div>
);

export const Badge = ({ children, color='#7c5cbf', bg }) => (
  <span style={{
    background: bg || `${color}22`, color, border:`1px solid ${color}44`,
    borderRadius:20, padding:'2px 10px', fontSize:11, fontWeight:600, letterSpacing:.5
  }}>{children}</span>
);

export const StatusDot = ({ status }) => (
  <span style={{
    display:'inline-block', width:8, height:8, borderRadius:'50%',
    background: STATUS_COLORS[status] || '#6b7280',
    boxShadow: `0 0 6px ${STATUS_COLORS[status] || '#6b7280'}`,
    marginRight:6
  }}/>
);

export const StatCard = ({ label, value, sub, icon, color='#7c5cbf', trend }) => (
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

export const SectionTitle = ({ children, sub }) => (
  <div style={{marginBottom:18}}>
    <h2 style={{fontSize:17,fontWeight:700,color:'#f0eeff'}}>{children}</h2>
    {sub && <p style={{fontSize:12,color:'#6e6694',marginTop:3}}>{sub}</p>}
  </div>
);

export const AIInsightCard = ({ insights }) => {
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

export const CustomTooltip = ({ active, payload, label, prefix='', suffix='' }) => {
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
