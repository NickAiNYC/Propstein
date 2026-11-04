// components/slate/feed-health-panel.tsx
import type { FeedSourceHealth } from "@/lib/types/slate";
import { VerificationBadge } from "@/components/primitives/verification-badge";
import { TabularNumber } from "@/components/primitives/tabular-number";

export function FeedHealthPanel({ sources }: { sources: FeedSourceHealth[] }) {
  const primary = sources.filter(s => s.tier === "primary");
  const secondary = sources.filter(s => s.tier === "secondary");
  const secondaryHealthy = secondary.every(s => s.status === "VERIFIED" || s.status === "OBSERVED");
  const oldestSecondary = secondary.reduce<FeedSourceHealth | null>(
    (oldest, s) => !oldest || s.last_success_at < oldest.last_success_at ? s : oldest,
    null
  );

  return (
    <section aria-labelledby="feed-heading" className="rounded border border-layer-3 bg-layer-1 p-4">
      <div className="flex items-center justify-between">
        <h2 id="feed-heading" className="text-[11px] uppercase tracking-wider text-text-secondary">
          Feed Health
        </h2>
        <span className="text-[10px] text-text-tertiary">
          {primary.length} primary · {secondary.length} secondary
        </span>
      </div>

      {/* Primary — full detail, sizing sources */}
      <table className="mt-3 w-full text-[11px]">
        <thead>
          <tr className="text-left text-text-tertiary">
            <th scope="col" className="pb-1 font-normal">Primary source</th>
            <th scope="col" className="pb-1 text-right font-normal">Quotes</th>
            <th scope="col" className="pb-1 text-right font-normal">Status</th>
            <th scope="col" className="pb-1 text-right font-normal">Age</th>
          </tr>
        </thead>
        <tbody>
          {primary.map((s) => (
            <tr key={s.source_id} className="border-t border-layer-3">
              <td className="py-1.5">
                <div className="text-text-primary">{s.source_id}</div>
                {s.book_id && <div className="text-[10px] text-text-tertiary">{s.book_id}</div>}
              </td>
              <td className="py-1.5 text-right">
                <TabularNumber className="text-text-primary">{s.quote_count}</TabularNumber>
              </td>
              <td className="py-1.5 text-right"><VerificationBadge status={s.status} compact /></td>
              <td className="py-1.5 text-right text-text-secondary">{ageLabel(s.last_success_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Secondary — compressed to a single health line */}
      {secondary.length > 0 && (
        <p className={`mt-3 rounded border px-2 py-1.5 text-[10px] leading-snug ${
          secondaryHealthy
            ? "border-layer-3 text-text-tertiary"
            : "border-semantic-observed/30 bg-semantic-observed/[0.05] text-semantic-observed"
        }`}>
          {secondary.length} secondary source{secondary.length === 1 ? "" : "s"}
          {oldestSecondary && ` · last update ${ageLabel(oldestSecondary.last_success_at)}`}
          {!secondaryHealthy && " · ⚠ one or more degraded"}
          <span className="ml-1 text-text-tertiary">
            (context only — not used for action)
          </span>
        </p>
      )}

      {primary.some(s => !s.verification_configured) && (
        <p className="mt-3 text-[10px] leading-snug text-semantic-observed">
          ⚠ A primary source has no hash audit configured. Action is locked on its quotes.
        </p>
      )}
    </section>
  );
}

function ageLabel(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "—";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
