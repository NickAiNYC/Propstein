import type { GameChip } from "@/lib/data/research-board";

export function WeekSlateStrip({ weekLabel, games }: { weekLabel: string; games: GameChip[] }) {
  return (
    <section aria-labelledby="week-slate-heading" className="rounded border border-layer-3 bg-layer-1 p-4">
      <h2 id="week-slate-heading" className="text-[11px] uppercase tracking-wider text-text-secondary">
        Week slate
      </h2>
      <p className="mt-1 text-sm text-text-primary">{weekLabel}</p>
      {games.length === 0 ? (
        <p className="mt-2 text-[11px] text-text-tertiary">unavailable</p>
      ) : (
        <ol className="mt-3 flex gap-2 overflow-x-auto pb-1">
          {games.map((game) => (
            <li key={game.eventId} className="shrink-0 rounded border border-layer-3 bg-layer-2 px-2 py-1.5">
              <p className="whitespace-nowrap font-mono text-[11px] text-text-primary">{game.eventId}</p>
              <p className="whitespace-nowrap text-[10px] text-text-tertiary">{game.kickoff}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
