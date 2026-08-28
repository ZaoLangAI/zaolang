'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';

import * as editorApi from './api';
import { TICKS_PER_SECOND } from './engine/ports';

/**
 * The editor's own version history — replaces the old episode-page "剪辑
 * 历史" cuts list. Lists every immutable `CutRevision` for this cut
 * (newest first); restoring an older one goes through the same lease/CAS
 * path as any other edit (`onRestore`, wired to `DramaEditor.restore` —
 * see that component for the actual API call and state update), it just
 * copies a past revision's document instead of diffing commands.
 */
export function HistoryPanel({
  cutId,
  headRevisionId,
  disabled,
  onRestore,
}: {
  cutId: string;
  headRevisionId: string | null;
  disabled: boolean;
  onRestore: (revisionId: string) => void;
}) {
  const t = useTranslations('editor');
  const [revisions, setRevisions] = useState<editorApi.CutRevisionSummary[]>([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(() => {
    void editorApi
      .listCutRevisions(cutId)
      .then((rows) => {
        setRevisions(rows);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [cutId]);

  useEffect(() => {
    // Re-fetch whenever the head moves (a normal edit or a restore both
    // change it) so the "current" badge and the row list stay in sync.
    load();
  }, [load, headRevisionId]);

  if (!loaded) return null;

  return (
    <section className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold">{t('historyPanelTitle')}</h2>
      {revisions.length === 0 ? (
        <p className="text-xs text-muted">{t('historyEmpty')}</p>
      ) : (
        <ul className="flex max-h-60 flex-col gap-2 overflow-y-auto">
          {revisions.map((revision) => (
            <li
              key={revision.id}
              className="flex items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2 text-xs"
            >
              <span className="min-w-0 truncate">
                #{revision.revision_no} · {new Date(revision.created_at).toLocaleString()} ·{' '}
                {(revision.duration_ticks / TICKS_PER_SECOND).toFixed(1)}s
              </span>
              {revision.is_head ? (
                <Badge tone="success">{t('historyCurrentBadge')}</Badge>
              ) : (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={disabled}
                  onClick={() => onRestore(revision.id)}
                >
                  {t('historyRestoreAction')}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
