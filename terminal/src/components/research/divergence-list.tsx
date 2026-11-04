import { TabularNumber } from "@/components/primitives/tabular-number";
import type { DivergenceItem } from "@/lib/data/research-board";

export function DivergenceList({
  rows,
  researchLabel,
}: {
  rows: DivergenceItem[];
  researchLabel: string;
}) {
  return (
    <section aria-labelledby="divergence-heading" className="rounded border border-layer-3 bg-layer-1 p-4">
      <h2 id="divergence-heading" className="text-[11px] uppercase tracking-wider text-text-secondary">
        Research divergence
      </h2>
      <p className="mt-1 text-[11px] text-text-secondary">{researchLabel}</p>
      {rows.length === 0 ? (
        <p className="mt-3 text-[11px] text-text-tertiary">unavailable</p>
      ) : (
        <table className="mt-3 w-full text-[11px]">
          <thead>
            <tr className="text-left text-text-tertiary">
              <th scope="col" className="pb-1 font-normal">Player</th>
              <th scope="col" className="pb-1 font-normal">Market</th>
              <th scope="col" className="pb-1 text-right font-normal">Divergence (σ)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.playerName}-${row.market}-${row.book}-${index}`} className="border-t border-layer-3">
                <td className="py-1.5 text-text-primary">{row.playerName}</td>
                <td className="py-1.5 text-text-secondary">{row.market}</td>
                <td className="py-1.5 text-right text-text-primary">
                  <TabularNumber>{row.divergence}</TabularNumber>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
