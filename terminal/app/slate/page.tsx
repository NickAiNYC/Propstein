// app/slate/page.tsx — the Slate Overview route.
//
// Server-rendered from the versioned viewer/ artifacts on every request.
// `?__mock=` fixtures are gated to the test environment inside the data
// layer; production and local dev always render real artifacts.
import { getSlateOverview } from "@/lib/data/slate-overview";
import { TopQualifiedPlay } from "@/components/slate/top-qualified-play";
import { FeedHealthPanel } from "@/components/slate/feed-health-panel";
import { PlaysTable } from "@/components/slate/plays-table";

export const dynamic = "force-dynamic";

export default async function SlatePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const mockKey = typeof params.__mock === "string" ? params.__mock : undefined;
  const data = await getSlateOverview(mockKey);

  const conflict =
    data.conflict || data.plays.some((p) => p.verification_status === "CONFLICT");
  const lastGood =
    data.sources
      .filter((s) => s.status === "VERIFIED")
      .map((s) => s.last_success_at)
      .sort()
      .pop() ?? null;
  const primaryBlocked = data.sources.some(
    (s) => s.tier === "primary" && s.status !== "VERIFIED"
  );

  return (
    <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
      <header className="flex items-baseline justify-between gap-4">
        <h1 className="text-sm font-medium tracking-wide text-text-primary">Slate Overview</h1>
        <p className="text-[10px] text-text-tertiary">
          {data.slate_id} · cutoff {data.data_cutoff_timestamp || "unknown"}
        </p>
      </header>

      {conflict && (
        <div
          role="alert"
          className="rounded border border-semantic-stale/60 bg-semantic-stale/[0.07] p-3"
        >
          <p className="text-xs font-medium text-semantic-stale">
            FEED CONFLICT — sharp books disagree beyond the drift threshold. Action locked.
          </p>
          <p className="mt-0.5 text-[10px] text-text-secondary">
            Last good verified snapshot: {lastGood ?? "none this session"} · No bet placement
            until CONFLICT clears.
          </p>
        </div>
      )}

      {!conflict && primaryBlocked && (
        <div role="alert" className="rounded border border-semantic-observed/50 bg-semantic-observed/[0.06] p-3 text-xs text-semantic-observed">
          Feed not independently verified. Research lines may be shown below; all execution is locked.
          Last good verified snapshot: {lastGood ?? "none"}.
        </div>
      )}

      <TopQualifiedPlay play={data.plays[0] ?? null} />
      <FeedHealthPanel sources={data.sources} />
      <PlaysTable plays={data.plays} />

      <footer className="pt-2 text-[10px] leading-relaxed text-text-tertiary">
        Research display only. The Python model artifacts supply the numbers; this surface
        does not price, size, or verify a quote. No LLM participates in the decision path.
      </footer>
    </div>
  );
}
