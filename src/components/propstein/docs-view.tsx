'use client';

/**
 * PropStein — Docs view: in-app specification + live copy compliance report.
 */

import { useEffect, useState } from 'react';
import Markdown from 'react-markdown';
import { DOCS } from '@/content/docs';
import { Note, SectionLabel } from './shared';
import { cn } from '@/lib/utils';

interface ComplianceReport {
  scannedStrings: number;
  violations: { pattern: string; text: string; context: string }[];
  status: string;
  checkedAtUtc: string;
}

export function DocsView() {
  const [active, setActive] = useState(DOCS[0].id);
  const [report, setReport] = useState<ComplianceReport | null>(null);

  useEffect(() => {
    fetch('/api/copy-compliance')
      .then((r) => r.json())
      .then((j) => {
        if (j.ok) setReport(j);
      })
      .catch(() => undefined);
  }, []);

  const doc = DOCS.find((d) => d.id === active) ?? DOCS[0];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-zinc-900">Specification</h2>
        <p className="mt-0.5 text-[12.5px] text-zinc-500">
          Product spec, database schema, API contract, and launch checklist. The full exported specification PDF adds
          the prohibited-vocabulary appendix and complete test report.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {DOCS.map((d) => (
          <button
            key={d.id}
            onClick={() => setActive(d.id)}
            className={cn(
              'rounded-sm border px-2.5 py-1 text-[12.5px] transition-colors',
              active === d.id
                ? 'border-zinc-800 bg-zinc-800 text-zinc-50'
                : 'border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50',
            )}
            aria-pressed={active === d.id}
          >
            {d.title}
          </button>
        ))}
        <button
          onClick={() => setActive('copy-compliance')}
          className={cn(
            'rounded-sm border px-2.5 py-1 text-[12.5px] transition-colors',
            active === 'copy-compliance'
              ? 'border-zinc-800 bg-zinc-800 text-zinc-50'
              : 'border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50',
          )}
          aria-pressed={active === 'copy-compliance'}
        >
          Copy compliance
        </button>
      </div>

      <article className="pst-card rounded-md p-5 max-w-3xl">
        {active === 'copy-compliance' ? (
          <div>
            <h3 className="text-[15px] font-semibold text-zinc-900">Copy compliance report</h3>
            <p className="mt-1 text-[12.5px] text-zinc-500">
              The linter scans every string in the product copy registry (and the test suite additionally scans all UI
              component string literals). The prohibited vocabulary itself is enumerated only in the exported
              specification PDF, never rendered as product copy.
            </p>
            {report ? (
              <div className="mt-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'inline-flex items-center rounded-sm border px-2.5 py-0.5 text-xs font-semibold',
                      report.status === 'COMPLIANT'
                        ? 'border-teal-800/40 bg-teal-800/5 text-teal-900'
                        : 'border-amber-800/40 bg-amber-800/5 text-amber-900',
                    )}
                    role="status"
                  >
                    {report.status}
                  </span>
                  <span className="pst-num text-[12px] text-zinc-500">
                    {report.scannedStrings} strings scanned · {report.violations.length} findings
                  </span>
                </div>
                {report.violations.length === 0 ? (
                  <Note tone="teal">
                    All product copy surfaces are clean: no picks, no sizing language, no urgency language, no
                    actionable-signal claims. Checked {new Date(report.checkedAtUtc).toISOString().slice(0, 19).replace('T', ' ')} UTC.
                  </Note>
                ) : (
                  <ul className="text-[12.5px] text-amber-800 list-disc pl-4">
                    {report.violations.map((v, i) => (
                      <li key={i}>
                        {v.pattern}: {v.context.slice(0, 80)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <p className="text-[12.5px] text-zinc-400 mt-2">Running the linter…</p>
            )}
          </div>
        ) : (
          <div className="prose prose-zinc prose-sm max-w-none [&_h2]:text-[15px] [&_h2]:mt-4 [&_h2]:mb-1 [&_h3]:text-[13.5px] [&_table]:text-[12px] [&_th]:border [&_th]:border-zinc-200 [&_th]:px-2 [&_th]:py-1 [&_th]:bg-zinc-50 [&_td]:border [&_td]:border-zinc-200 [&_td]:px-2 [&_td]:py-1 [&_code]:bg-zinc-100 [&_code]:px-1 [&_code]:rounded [&_code]:text-[11.5px] [&_li]:text-[12.5px] [&_p]:text-[12.5px] [&_p]:leading-relaxed">
            <Markdown>{doc.markdown}</Markdown>
          </div>
        )}
      </article>

      <div className="pst-card rounded-md p-4 max-w-3xl">
        <SectionLabel>Reference deployment notes</SectionLabel>
        <Note>
          This build is the functional reference implementation of the specification: Next.js 16 with App Router API
          routes standing in for the FastAPI service, SQLite via Prisma standing in for PostgreSQL, and an in-process
          store standing in for Redis (revocation, rate limits). Domain logic — odds mathematics, the Hurdle Router,
          the append-only ledger, grading, the bootstrap, and the preregistered gate — is shared verbatim with the
          production design. All simulated providers are labelled as simulated data on every surface.
        </Note>
      </div>
    </div>
  );
}
