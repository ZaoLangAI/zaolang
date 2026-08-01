'use client';

import { useTranslations } from 'next-intl';

import { Badge } from '@/components/ui/primitives';
import { cn } from '@/lib/cn';

/**
 * One row per candidate the router considered, including the ones it rejected.
 *
 * Showing only the winner would make the decision unexplainable — the rejects
 * and their filter reasons *are* the explanation.
 */
export function RoutingReplayTable({
  candidates,
  chosen,
}: {
  candidates: Array<Record<string, unknown>>;
  chosen: string | null;
}) {
  const t = useTranslations('adminJobs');
  const tAdmin = useTranslations('admin');

  if (candidates.length === 0) {
    return <p className="text-xs text-muted">{tAdmin('timelineEmpty')}</p>;
  }

  return (
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
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t('totalScore')}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t('effectiveCost')}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {candidates.map((candidate, index) => {
            const provider = String(candidate.provider ?? `#${index}`);
            const eligible = Boolean(candidate.eligible);
            const reason = candidate.filter_reason ? String(candidate.filter_reason) : null;

            return (
              <tr key={provider} className={cn(provider === chosen && 'bg-success/8')}>
                <th scope="row" className="px-3 py-2 text-left font-mono font-normal">
                  {provider}
                  {provider === chosen ? (
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
                      {reason ? ` · ${reason}` : ''}
                    </span>
                  )}
                </td>
                <td className="tabular px-3 py-2 text-right">
                  {Number(candidate.total_score ?? 0).toFixed(3)}
                </td>
                <td className="tabular px-3 py-2 text-right text-muted">
                  {Number(candidate.effective_cost ?? 0)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
