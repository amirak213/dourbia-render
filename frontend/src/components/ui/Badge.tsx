import type { ReactNode } from "react";

interface BadgeProps {
  children: ReactNode;
  variant?: "default" | "warn";
}

export default function Badge({ children, variant = "default" }: BadgeProps) {
  return (
    <span className={`ui-badge${variant === "warn" ? " ui-badge-warn" : ""}`}>
      {children}
    </span>
  );
}
