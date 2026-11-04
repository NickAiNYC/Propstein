import { ResearchBoardView } from "@/components/research/research-board";
import { loadResearchBoard } from "@/lib/data/research-board";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const metadata = {
  title: "PropStein Terminal — Research",
  description: "Read-only research surface over the ledger and frozen snapshots.",
};

export default async function ResearchPage() {
  const board = await loadResearchBoard();
  return (
    <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
      <ResearchBoardView board={board} />
    </main>
  );
}
