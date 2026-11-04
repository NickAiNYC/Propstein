import { TabularNumber } from "@/components/primitives/tabular-number";

export function ModelStatusPanel({
  modelVersion,
  gateLabel,
}: {
  modelVersion: string;
  gateLabel: string;
}) {
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
          <dt className="text-text-tertiary">Confirmatory count</dt>
          <dd className="text-text-primary">
            <TabularNumber>{gateLabel}</TabularNumber>
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-[10px] leading-relaxed text-text-tertiary">
        Count is the live prospective full board view for AMEND-001, shown against the confirmatory N of 600.
      </p>
    </section>
  );
}
