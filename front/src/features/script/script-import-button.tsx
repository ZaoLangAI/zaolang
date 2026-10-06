'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { IconWand } from '@/components/ui/icons';
import { EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { formatRelative } from '@/lib/format';
import { useResource } from '@/lib/use-resource';

import type { ScriptSummary } from './api';
import { AssetBreakdownDialog } from './asset-breakdown-dialog';
import type { BreakdownKind } from './asset-breakdown-model';

/**
 * 「从剧本导入」 on a card library (`/create/{characters,scenes,props}`):
 * pick one of the author's scripts, then `AssetBreakdownDialog` limited to
 * this library's kind. Hidden unless the script studio is on — the
 * breakdown routes 404 without it.
 */
export function ScriptImportButton({
  kind,
  onApplied,
}: {
  kind: BreakdownKind;
  /** The library reloads its cards. */
  onApplied: () => void;
}) {
  const t = useTranslations('assetBreakdown');
  const locale = useLocale() as Locale;
  const { user } = useSession();
  const [picking, setPicking] = useState(false);
  const [episodeId, setEpisodeId] = useState<string | null>(null);
  const scripts = useResource<ScriptSummary[]>(picking ? '/v1/scripts' : null);

  if (!user?.features.script_studio) return null;
  const ready = (scripts.data ?? []).filter((script) => script.turn_count > 0);

  return (
    <>
      <Button
        variant="secondary"
        icon={<IconWand className="size-4" />}
        onClick={() => setPicking(true)}
      >
        {t('importFromScript')}
      </Button>
      {picking ? (
        <Dialog
          open
          onClose={() => setPicking(false)}
          title={t('pickEpisodeTitle')}
          description={t('pickEpisodeHint')}
        >
          {scripts.status === 'loading' && !scripts.data ? (
            <p className="flex items-center gap-2 text-sm text-muted" role="status">
              <Spinner />
              {t('pickEpisodeLoading')}
            </p>
          ) : scripts.status === 'failed' ? (
            <ErrorNotice title={t('pickEpisodeFailed')} />
          ) : ready.length === 0 ? (
            <EmptyState
              title={t('pickEpisodeEmpty')}
              action={
                <Link href="/create/script" className="text-sm text-primary hover:underline">
                  {t('pickEpisodeWrite')}
                </Link>
              }
            />
          ) : (
            <ul className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto">
              {ready.map((script) => (
                <li key={script.episode_id}>
                  <button
                    type="button"
                    onClick={() => {
                      setPicking(false);
                      setEpisodeId(script.episode_id);
                    }}
                    className="flex w-full min-w-0 flex-col gap-0.5 rounded-[var(--radius-sm)] border border-border px-3 py-2 text-left transition-colors hover:border-border-strong hover:bg-surface-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus)]"
                  >
                    <span className="truncate text-sm font-medium">
                      {script.title || t('untitledScript')}
                    </span>
                    {script.logline ? (
                      <span className="line-clamp-2 text-xs text-muted">{script.logline}</span>
                    ) : null}
                    <span className="text-[11px] text-muted">
                      {formatRelative(script.updated_at, locale)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Dialog>
      ) : null}
      {episodeId ? (
        <AssetBreakdownDialog
          episodeId={episodeId}
          kinds={[kind]}
          onClose={() => setEpisodeId(null)}
          onApplied={onApplied}
        />
      ) : null}
    </>
  );
}
