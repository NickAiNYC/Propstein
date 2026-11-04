import { TabularNumber } from "@/components/primitives/tabular-number";

export function ModelStatusPanel({
  modelVersion,
  evaluableLabel = "0 / 600",
  committedCount = 472,
  gateLabel,
}: {
  modelVersion: string;
  evaluableLabel?: string;
  committedCount?: number | string;
  gateLabel?: string;
}) {
  const displayEvaluable = evaluableLabel ?? gateLabel ?? "0 / 600";
  return (
    <section aria-labelledby="model-status-heading" className="rounded border border-layer-3 bg-layer-1 p-4">
      <h2 id="model-status-heading" className="text-[11px] uppercase tracking-wider text-text-secondary">
        Model status
      </h2>
      <dl className="mt-3 space-y-2 text-[11px]">
        <div className="flex items-baseline justify-between gap-4">
          <dt className="text-text-tertiary">Version</dt>
          <dd className="text-text-primary">{modelVersion}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-4">
          <dt className="text-text-tertiary">Evaluable signals</dt>
          <dd className="text-text-primary">
            <TabularNumber>{displayEvaluable}</TabularNumber>
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-4">
          <dt className="text-text-tertiary">Committed forecasts</dt>
          <dd className="text-text-primary">
            <TabularNumber>{String(committedCount)}</TabularNumber>
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-[10px] leading-relaxed text-text-tertiary">
        0 evaluable signals evaluated against closing lines toward the 600 confirmatory gate. 472 prospective forecasts are committed under AMEND-001 awaiting close.
      </p>
    </section>
  );
}
