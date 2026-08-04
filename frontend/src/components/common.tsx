// @ts-nocheck
import type { CSSProperties, ReactNode } from "react";
import * as LucideIcons from "lucide-react";

const PURPLE = "#7c5cbf";
const PURPLE_L = "#c4b5fd";

const STATUS_COLORS: Record<string, string> = {
  normal: "#22c55e",
  warning: "#f59e0b",
  critical: "#ef4444",
  offline: "#6b7280",
  online: "#22c55e",
};

const PRIORITY_META: Record<string, { label: string; color: string }> = {
  high: { label: "Alta", color: "#ef4444" },
  medium: { label: "Media", color: "#f59e0b" },
  low: { label: "Baja", color: "#22c55e" },
  info: { label: "Info", color: "#818cf8" },
};

type AnyProps = Record<string, any>;

export const Icon = ({
  name = "Circle",
  size = 16,
  color = "currentColor",
  stroke = 2,
  style = {},
}: {
  name?: string;
  size?: number;
  color?: string;
  stroke?: number;
  style?: CSSProperties;
}) => {
  const Cmp = (LucideIcons as AnyProps)[name] || (LucideIcons as AnyProps).Circle;
  return <Cmp size={size} color={color} strokeWidth={stroke} style={style} />;
};

export const Card = ({
  children,
  style = {},
  glow = false,
  className = "",
}: {
  children?: ReactNode;
  style?: CSSProperties;
  glow?: boolean;
  className?: string;
}) => (
  <div
    className={className}
    style={{
      background: "#11111c",
      border: `1px solid ${glow ? "#7c5cbf55" : "#23233a"}`,
      borderRadius: 16,
      padding: 20,
      boxShadow: glow ? "0 0 25px rgba(124,92,191,.18)" : "none",
      ...style,
    }}
  >
    {children}
  </div>
);

export const Badge = ({
  children,
  color = "#7c5cbf",
  bg,
}: {
  children?: ReactNode;
  color?: string;
  bg?: string;
}) => (
  <span
    style={{
      color,
      background: bg || `${color}18`,
      border: `1px solid ${color}44`,
      borderRadius: 999,
      padding: "4px 10px",
      fontSize: 11,
      fontWeight: 800,
      whiteSpace: "nowrap",
    }}
  >
    {children}
  </span>
);

export const StatusDot = ({ status = "offline" }: { status?: string }) => (
  <span
    style={{
      width: 9,
      height: 9,
      borderRadius: 999,
      display: "inline-block",
      background: STATUS_COLORS[status] || "#6b7280",
      boxShadow: `0 0 6px ${STATUS_COLORS[status] || "#6b7280"}`,
    }}
  />
);

export const StatCard = ({
  label,
  value,
  sub,
  icon,
  color = "#7c5cbf",
  trend,
}: {
  label?: ReactNode;
  value?: ReactNode;
  sub?: ReactNode;
  icon?: string;
  color?: string;
  trend?: number;
}) => (
  <Card style={{ flex: 1, minWidth: 140, padding: "18px 20px", borderTop: `1px solid ${color}55` }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
      <div style={{ color: "#7b739e", fontSize: 12 }}>{label}</div>
      {icon && <Icon name={icon} size={15} color={color} />}
    </div>
    <div style={{ color: "#f0eeff", fontSize: 26, fontWeight: 900 }}>{value}</div>
    <div style={{ color: "#7b739e", fontSize: 12, marginTop: 5 }}>{sub}</div>
    {typeof trend === "number" && (
      <div style={{ color: trend >= 0 ? "#ef4444" : "#22c55e", fontSize: 11, marginTop: 8, display: "flex", gap: 4, alignItems: "center" }}>
        <Icon name={trend >= 0 ? "TrendingUp" : "ArrowDown"} size={12} />
        {trend >= 0 ? "+" : "-"}
        {Math.abs(trend)}% vs sem. anterior
      </div>
    )}
  </Card>
);

export const SectionTitle = ({
  children,
  sub,
  title,
  subtitle,
}: {
  children?: ReactNode;
  sub?: ReactNode;
  title?: ReactNode;
  subtitle?: ReactNode;
}) => (
  <div style={{ marginBottom: 18 }}>
    <div style={{ color: "#f0eeff", fontSize: 18, fontWeight: 900 }}>{title || children}</div>
    {(subtitle || sub) && <div style={{ color: "#7b739e", fontSize: 12, marginTop: 4 }}>{subtitle || sub}</div>}
  </div>
);

export const AIInsightCard = ({ insights = [] }: { insights?: any[] }) => {
  const normalized = insights.map((ins: any, i: number) =>
    typeof ins === "string"
      ? { title: ins, description: "", priority: "info", building: "Sistema" }
      : { priority: "info", building: "Sistema", ...ins }
  );

  return (
    <Card glow style={{ borderColor: `${PURPLE}44` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <div style={{ background: "#7c5cbf18", border: "1px solid #7c5cbf33", borderRadius: 10, padding: 8, color: PURPLE_L }}>
            <Icon name="Brain" size={18} />
          </div>
          <div>
            <div style={{ color: "#f0eeff", fontWeight: 900 }}>AI Insights</div>
            <div style={{ color: "#7b739e", fontSize: 12 }}>Análisis automático del sistema</div>
          </div>
        </div>
        <Badge color={PURPLE_L}>AI Engine</Badge>
      </div>

      <div style={{ display: "grid", gap: 12 }}>
        {normalized.map((ins: any, i: number) => {
          const meta = PRIORITY_META[ins.priority] || PRIORITY_META.info;
          return (
            <div key={i} style={{ borderTop: "1px solid #23233a", paddingTop: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 6 }}>
                <b style={{ color: "#f0eeff" }}>{ins.title}</b>
                <Badge color={meta.color}>{meta.label}</Badge>
              </div>
              {ins.building && (
                <div style={{ color: PURPLE_L, fontSize: 12, display: "flex", gap: 6, alignItems: "center", marginBottom: 5 }}>
                  <Icon name="Building" size={14} color={PURPLE_L} />
                  {ins.building}
                </div>
              )}
              {ins.description && <div style={{ color: "#a9a2d0", fontSize: 13, lineHeight: 1.45 }}>{ins.description}</div>}
            </div>
          );
        })}
      </div>
    </Card>
  );
};

export const CustomTooltip = ({
  active,
  payload,
  label,
  prefix = "",
  suffix = "",
}: {
  active?: boolean;
  payload?: any[];
  label?: ReactNode;
  prefix?: string;
  suffix?: string;
}) => {
  if (!active || !payload || !payload.length) return null;

  return (
    <div style={{ background: "#11111c", border: "1px solid #2a2740", borderRadius: 10, padding: 10 }}>
      <div style={{ color: "#f0eeff", fontWeight: 800, marginBottom: 6 }}>{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color || "#c4b5fd", fontSize: 12 }}>
          {p.name}: {prefix}
          {p.value}
          {suffix}
        </div>
      ))}
    </div>
  );
};
