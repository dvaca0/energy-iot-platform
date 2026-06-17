interface BadgeProps {
  children: React.ReactNode;
  tone?: "green" | "yellow" | "red" | "purple" | "gray";
}

const tones = {
  green: ["#22c55e", "rgba(34,197,94,.12)", "rgba(34,197,94,.28)"],
  yellow: ["#f59e0b", "rgba(245,158,11,.12)", "rgba(245,158,11,.28)"],
  red: ["#ef4444", "rgba(239,68,68,.12)", "rgba(239,68,68,.28)"],
  purple: ["#a78bfa", "rgba(124,92,191,.16)", "rgba(167,139,250,.28)"],
  gray: ["#9ca3af", "rgba(156,163,175,.10)", "rgba(156,163,175,.20)"],
};

export function Badge({ children, tone = "purple" }: BadgeProps) {
  const [color, background, border] = tones[tone];

  return (
    <span
      style={{
        color,
        background,
        border: `1px solid ${border}`,
        borderRadius: 999,
        padding: "3px 9px",
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: 0.3,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}
