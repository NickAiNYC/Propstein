import type { ReactNode } from "react";

// Numbers are the interface — tabular, monospace, never proportional fonts.
export function TabularNumber({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <span className={`font-mono tabular-nums ${className}`}>{children}</span>;
}
