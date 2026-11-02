// components/slate/plays-table.tsx — the full board: every quote on the slate
// with its edge, fair line, card state and trust badge. The top play gets the
// hero card; the board keeps the whole environment visible.
import type { QualifiedPlaySummary, CardState } from "@/lib/types/slate";
import { deriveCardState } from "@/lib/types/slate";
import { VerificationBadge } from "@/components/primitives/verification-badge";
import { TabularNumber } from "@/components/primitives/tabular-number";

const CHIP: Record<CardState, string> = {
  QUALIFIED: "text-semantic-verified border-semantic-verified/40",
  WATCH: "text-semantic-observed border-semantic-observed/40",
  BLOCKED_DATA: "text-semantic-stale border-semantic-stale/40",
  BLOCKED_GATE: "text-semantic-stale border-semantic-stale/40",
};

export function PlaysTable({ plays }: { plays: QualifiedPlaySummary[] }) {
  if (plays.length === 0) return null;

  return (
    <section aria-labelledby="plays-heading" className="rounded border border-layer-3 bg-layer-1 p-4">
      <h2 id="plays-heading" className="text-[11px] uppercase tracking-wider text-text-secondary">
        Slate · {plays.length} quote{plays.length === 1 ? "" : "s"}
      </h2>
      <table className="mt-3 w-full text-[11px]">
        <thead>
          <tr className="text-left text-text-tertiary">
            <th scope="col" className="pb-1 font-normal">Player / market</th>
            <th scope="col" className="pb-1 text-right font-normal">Edge</th>
            <th scope="col" className="pb-1 text-right font-normal">Fair</th>
            <th scope="col" className="pb-1 text-right font-normal">State</th>
            <th scope="col" className="pb-1 text-right font-normal">Trust</th>
          </tr>
        </thead>
        <tbody>
          {plays.map((p) => {
            const state = deriveCardState(p);
            return (
              <tr key={p.play_id} className="border-t border-layer-3">
                <td className="py-1.5">
                  <div className="truncate text-text-primary">{p.player_name}</div>
                  <div className="text-[10px] text-text-tertiary">
                    {p.market} · {p.side} <TabularNumber>{p.line}</TabularNumber> · {p.book_id}
                  </div>
                </td>
                <td className="py-1.5 text-right">
                  <TabularNumber className="text-text-primary">
                    {p.edge_pct === null ? "—" : `${p.edge_pct >= 0 ? "+" : ""}${p.edge_pct.toFixed(1)}%`}
                  </TabularNumber>
                </td>
                <td className="py-1.5 text-right">
                  <TabularNumber className="text-text-secondary">{p.fair_line.toFixed(1)}</TabularNumber>
                </td>
                <td className="py-1.5 text-right">
                  <span className={`rounded border px-1.5 py-0.5 text-[9px] ${CHIP[state]}`}>{state}</span>
                </td>
                <td className="py-1.5 text-right">
                  <VerificationBadge status={p.verification_status} compact />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
