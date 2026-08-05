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

  const maxScore = Math.max(...candidates.map((c) => Number(c.total_score ?? 0)), 0.001);
  const maxCost = Math.max(...candidates.map((c) => Number(c.effective_cost ?? 0)), 1);

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
            <th scope="col" className="px-3 py-2 font-medium">
              {t('totalScore')}
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
            const reason = candidate.filter_reason ? String(candidate.filter_reason) : null;
            const score = Number(candidate.total_score ?? 0);
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
                      {reason ? ` · ${reason}` : ''}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <ScoreBar
                    value={score}
                    max={maxScore}
                    tone={isChosen ? 'success' : eligible ? 'primary' : 'neutral'}
                    display={score.toFixed(3)}
                  />
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
