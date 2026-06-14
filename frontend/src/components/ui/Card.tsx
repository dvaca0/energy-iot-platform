import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  glow?: boolean;
}

export function Card({ children, className = "", glow = false }: CardProps) {
  return (
    <section
      className={`card ${className}`}
      style={{
        boxShadow: glow ? "0 0 40px rgba(124, 92, 191, 0.16)" : undefined,
        borderColor: glow ? "rgba(167, 139, 250, 0.32)" : undefined,
      }}
    >
      {children}
    </section>
  );
}
