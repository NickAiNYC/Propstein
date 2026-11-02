import type { VerificationStatus } from "@/lib/types/slate";

// Verification is a visual state, not a label. Color is never the only
// signal: glyph + text + aria-label all encode the status. aria-labels are
// distinct per status and pinned by
// tests/slate-overview-failure-modes.spec.ts — never just "unverified".
const META: Record<
  VerificationStatus,
  { label: string; aria: string; glyph: string; cls: string }
> = {
  VERIFIED: {
    label: "VERIFIED",
    aria: "Quote verified by hash audit",
    glyph: "✓",
    cls: "border-semantic-verified/40 text-semantic-verified",
  },
  OBSERVED: {
    label: "OBSERVED",
    aria: "Quote observed but not verified",
    glyph: "!",
    cls: "border-semantic-observed/40 text-semantic-observed",
  },
  STALE: {
    label: "STALE",
    aria: "Quote stale — action locked",
    glyph: "!",
    cls: "border-semantic-observed/40 text-semantic-observed",
  },
  CONFLICT: {
    label: "CONFLICT",
    aria: "Feed conflict — action locked",
    glyph: "✕",
    cls: "border-semantic-stale/40 text-semantic-stale",
  },
};

export function VerificationBadge({
  status,
  compact = false,
}: {
  status: VerificationStatus;
  compact?: boolean;
}) {
  const m = META[status];
  return (
    <span
      role="status"
      aria-label={m.aria}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono uppercase tracking-wide ${
        m.cls
      } ${compact ? "text-[9px]" : "text-[10px]"}`}
    >
      <span aria-hidden="true">{m.glyph}</span>
      {m.label}
    </span>
  );
}
