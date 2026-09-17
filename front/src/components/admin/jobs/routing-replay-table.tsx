'use client';

import { useTranslations } from 'next-intl';

import { Badge } from '@/components/ui/primitives';
import { cn } from '@/lib/cn';

/**
 * One row per candidate the router considered, including the ones it rejected.
 *
 * Showing only the winner would make the decision unexplainable — the rejects
 * and their filter reasons *are* the explanation. The winner is no longer
 * picked by a score, though: `reason` is the LLM's own rationale for the
 * candidate it chose, shown once above the table rather than repeated per row.
 */
export function RoutingReplayTable({
  candidates,
  chosen,
  reason,
}: {
  candidates: Array<Record<string, unknown>>;
  chosen: string | null;
  reason?: string | null;
}) {
  const t = useTranslations('adminJobs');
  const tAdmin = useTranslations('admin');

  if (candidates.length === 0) {
    return <p className="text-xs text-muted">{tAdmin('timelineEmpty')}</p>;
  }

  const maxCost = Math.max(...candidates.map((c) => Number(c.effective_cost ?? 0)), 1);

  return (
    <div className="flex flex-col gap-2">
      {reason ? (
        <p className="text-xs text-muted">
          <span className="font-medium text-text">{t('rationale')}</span>
          {': '}
          {reason}
        </p>
      ) : null}
      <div className="overflow-x-auto rounded-[var(--radius-sm)] border border-border">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-soft text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('candidate')}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('eligible')}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('successRate')}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('avgLatency')}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('effectiveCost')}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {candidates.map((candidate, index) => {
              const provider = String(candidate.provider ?? `#${index}`);
              const eligible = Boolean(candidate.eligible);
              const filterReason = candidate.filter_reason ? String(candidate.filter_reason) : null;
              const successRate = Number(candidate.success_rate ?? 0);
              const avgLatencyMs = Number(candidate.avg_latency_ms ?? 0);
              const cost = Number(candidate.effective_cost ?? 0);
              const isChosen = provider === chosen;

              return (
                <tr key={provider} className={cn(isChosen && 'bg-success/8')}>
                  <th scope="row" className="px-3 py-2 text-left font-mono font-normal">
                    {provider}
                    {isChosen ? (
                      <Badge tone="success" className="ml-2">
                        {t('colProvider')}
                      </Badge>
                    ) : null}
                  </th>
                  <td className="px-3 py-2">
                    {eligible ? (
                      <span className="text-success">{t('eligible')}</span>
                    ) : (
                      <span className="text-muted">
                        {t('filtered')}
                        {filterReason ? ` · ${filterReason}` : ''}
                      </span>
                    )}
                  </td>
                  <td className="tabular px-3 py-2">{(successRate * 100).toFixed(1)}%</td>
                  <td className="tabular px-3 py-2 text-muted">
                    {avgLatencyMs ? `${avgLatencyMs}ms` : '—'}
                  </td>
                  <td className="px-3 py-2">
                    <ScoreBar value={cost} max={maxCost} tone="neutral" display={String(cost)} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Inline bar so relative magnitude is visible without cross-referencing rows. */
function ScoreBar({
  value,
  max,
  tone,
  display,
}: {
  value: number;
  max: number;
  tone: 'success' | 'primary' | 'neutral';
  display: string;
}) {
  const width = Math.min(Math.max((value / max) * 100, value > 0 ? 3 : 0), 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-soft">
        <div
          className={cn(
            'h-full rounded-full',
            tone === 'success' ? 'bg-success' : tone === 'primary' ? 'bg-primary' : 'bg-muted/60',
          )}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="tabular text-muted">{display}</span>
    </div>
  );
}
