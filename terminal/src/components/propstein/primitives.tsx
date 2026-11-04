"use client";

/* PropStein — shared UI primitives
   StatusChip: one restrained status vocabulary, dot + text, never oversized.
   TeamMark: compact team graphic. Stat: mono quantitative value + micro label. */

import { cn } from "@/lib/utils";
import { EVIDENCE_STATUS_META, EvidenceStatus } from "@/lib/propstein/types";
import { TEAMS } from "@/lib/propstein/data";

export function StatusChip({
  status,
  size = "sm",
  showLabel = true,
  className,
}: {
  status: EvidenceStatus;
  size?: "xs" | "sm";
  showLabel?: boolean;
  className?: string;
}) {
  const meta = EVIDENCE_STATUS_META[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-[2px] border px-1.5 py-px",
        size === "xs" ? "text-[10px]" : "text-[11px]",
        className
      )}
      style={{
        minWidth: size === "xs" ? "52px" : "58px",
        justifyContent: "center",
        borderColor: "color-mix(in srgb, var(--ps-border) 70%, transparent)",
        background: "color-mix(in srgb, currentColor 6%, transparent)",
        color: meta.color,
      }}
      title={meta.description}
    >
      <span
        aria-hidden
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: meta.color }}
      />
      {showLabel ? (
        <span className="font-medium tracking-wide">{meta.short}</span>
      ) : (
        <span className="sr-only">{meta.label}</span>
      )}
    </span>
  );
}

export function TeamMark({
  abbr,
  size = 28,
  className,
}: {
  abbr: string;
  size?: number;
  className?: string;
}) {
  const team = TEAMS[abbr];
  if (!team) return null;
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-[3px] border font-data font-medium",
        className
      )}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.36,
        color: team.color,
        borderColor: `color-mix(in srgb, ${team.color} 38%, var(--ps-border))`,
        background: `color-mix(in srgb, ${team.color} 9%, transparent)`,
      }}
    >
      {abbr}
    </span>
  );
}

export function Stat({
  label,
  value,
  unit,
  hint,
  size = "md",
  accent,
  className,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  size?: "sm" | "md" | "lg";
  accent?: "default" | "sapphire" | "mint" | "caution";
  className?: string;
}) {
  const accentColor =
    accent === "sapphire"
      ? "text-sapphire"
      : accent === "mint"
        ? "text-mint"
        : accent === "caution"
          ? "text-caution"
          : "text-text";
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="label-micro">{label}</span>
      <span
        className={cn(
          "font-data leading-none",
          size === "sm" && "text-sm",
          size === "md" && "text-xl",
          size === "lg" && "text-3xl",
          accentColor
        )}
      >
        {value}
        {unit ? <span className="ml-1 text-[0.6em] font-normal text-text-muted">{unit}</span> : null}
      </span>
      {hint ? <span className="text-[11px] leading-snug text-text-muted">{hint}</span> : null}
    </div>
  );
}

export function SectionHeading({
  title,
  subtitle,
  action,
  id,
  className,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-3", className)} id={id}>
      <div>
        <h2 className="font-display text-[15px] font-semibold tracking-tight text-text">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-xs text-text-muted">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function Panel({
  children,
  className,
  as: As = "section",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "section" | "div" | "article" | "aside";
}) {
  return <As className={cn("rounded-[10px] border border-hairline bg-panel", className)}>{children}</As>;
}

/** Value with explicit sign color for divergences — restrained, data-first. */
export function DivergenceValue({
  z,
  lineDivergence,
  marketLabel,
}: {
  z: number | null;
  lineDivergence: number | null;
  marketLabel?: string;
}) {
  if (z === null || lineDivergence === null) {
    return <span className="font-data text-text-muted">—</span>;
  }
  const strong = Math.abs(z) >= 0.15;
  return (
    <span className="inline-flex flex-col items-end leading-tight">
      <span
        className={cn("font-data", strong ? "text-sapphire-hover" : "text-text")}
        title={`Model fair minus captured line, in model standard deviations${marketLabel ? ` (${marketLabel})` : ""}`}
      >
        {lineDivergence > 0 ? "+" : ""}
        {lineDivergence.toFixed(1)}
        <span className="ml-1 text-[10px] text-text-muted">z {z > 0 ? "+" : ""}{z.toFixed(2)}</span>
      </span>
    </span>
  );
}
