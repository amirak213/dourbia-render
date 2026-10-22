import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
  compact?: boolean;
  as?: "article" | "section" | "div";
}

export default function Card({
  children,
  compact = false,
  as: Tag = "div",
  className,
  ...props
}: CardProps) {
  const classes = ["ui-card", compact ? "ui-card-compact" : "", className ?? ""]
    .filter(Boolean)
    .join(" ");

  return (
    <Tag className={classes} {...props}>
      {children}
    </Tag>
  );
}
