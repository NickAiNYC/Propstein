import { TabularNumber } from "@/components/primitives/tabular-number";
import type { PlayerCard } from "@/lib/data/research-board";

export function PlayerResearchCard({ card }: { card: PlayerCard }) {
  return (
    <article className="rounded border border-layer-3 bg-layer-1 p-4">
      <header className="flex items-baseline justify-between gap-3">
        <h2 className="truncate text-sm text-text-primary">{card.playerName}</h2>
        <p className="text-[10px] uppercase tracking-wide text-text-tertiary">{card.market}</p>
      </header>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[11px]">
        <div>
          <dt className="text-text-tertiary">Fair line (median)</dt>
          <dd className="text-text-primary">
            <TabularNumber>{card.fairLine}</TabularNumber>
          </dd>
        </div>
        <div>
          <dt className="text-text-tertiary">Projected volume (mean)</dt>
          <dd className="text-text-primary">
            <TabularNumber>{card.projectedVolume}</TabularNumber>
          </dd>
        </div>
        {card.quotes.map((quote, index) => (
          <div key={`${quote.book}-${index}`} className="col-span-2 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-layer-3 pt-2">
            <div>
              <dt className="text-text-tertiary">Captured line</dt>
              <dd className="text-text-primary">
                <TabularNumber>{quote.line}</TabularNumber>
              </dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Book</dt>
              <dd className="text-text-primary">{quote.book}</dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Capture timestamp</dt>
              <dd className="text-text-secondary">{quote.capturedAt}</dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Verification</dt>
              <dd className="text-text-secondary">{quote.verification}</dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Staleness</dt>
              <dd className="text-text-secondary">{quote.staleness}</dd>
            </div>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-[10px] text-text-tertiary">Snapshot timestamp {card.snapshotClock}</p>
    </article>
  );
}
