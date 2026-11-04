import type { ResearchBoard } from "@/lib/data/research-board";
import { DivergenceList } from "@/components/research/divergence-list";
import { ModelStatusPanel } from "@/components/research/model-status-panel";
import { PlayerResearchCard } from "@/components/research/player-research-card";
import { WeekSlateStrip } from "@/components/research/week-slate-strip";

export function ResearchBoardView({ board }: { board: ResearchBoard }) {
  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-sm font-medium tracking-wide text-text-primary">Research board</h1>
        <p className="mt-1 text-[10px] leading-relaxed text-text-tertiary">
          Read-only. Figures appear only when the ledger or a frozen snapshot captured them.
        </p>
      </header>
      <ModelStatusPanel modelVersion={board.modelVersion} gateLabel={board.gateLabel} />
      <WeekSlateStrip weekLabel={board.weekLabel} games={board.games} />
      <div className="space-y-3">
        {board.cards.length === 0 ? (
          <p className="text-[11px] text-text-tertiary">unavailable</p>
        ) : (
          board.cards.map((card, index) => (
            <PlayerResearchCard key={`${card.eventId}-${card.playerName}-${card.market}-${index}`} card={card} />
          ))
        )}
      </div>
      <DivergenceList rows={board.divergence} researchLabel={board.researchLabel} />
    </div>
  );
}
