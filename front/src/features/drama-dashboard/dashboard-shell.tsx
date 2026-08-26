'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { EmptyState } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import * as editorApi from '@/features/editor/api';
import { Link } from '@/i18n/navigation';
import { isApiError } from '@/lib/api/errors';

/**
 * The `/create/short` landing surface: every drama series the signed-in user
 * owns, plus a form to start a new one. Drilling into a series (episodes,
 * content links, canonical work) happens on `/create/short/series/{id}`.
 */
export function DashboardShell() {
  const t = useTranslations('editor');
  const { status } = useSession();
  const { notify } = useToast();

  const [title, setTitle] = useState('');
  const [items, setItems] = useState<editorApi.DramaSeries[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (status !== 'authenticated') return;
    void editorApi
      .listDramaSeries()
      .then((rows) => {
        setItems(rows);
        setLoaded(true);
      })
      .catch((error: unknown) => {
        if (isApiError(error) && error.isNotFound) setUnavailable(true);
        else notify(isApiError(error) ? error.message : t('dashboardUnavailable'), 'error');
        setLoaded(true);
      });
  }, [notify, status, t]);

  if (status === 'anonymous') {
    return <SignInPrompt description={t('signInHint')} />;
  }
  if (status === 'loading' || !loaded) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('dashboardLoading')} />
      </div>
    );
  }
  if (unavailable) {
    return (
      <EmptyState title={t('dashboardUnavailable')} description={t('dashboardUnavailableHint')} />
    );
  }

  const trimmedTitle = title.trim();

  return (
    <div className="flex flex-col gap-6">
      <form
        className="flex flex-col gap-3 sm:flex-row sm:items-end"
        onSubmit={(event) => {
          event.preventDefault();
          if (!trimmedTitle) return;
          setBusy(true);
          void editorApi
            .createDramaSeries(trimmedTitle)
            .then((series) => {
              setItems((current) => [series, ...current]);
              setTitle('');
              notify(t('seriesCreated'), 'success');
            })
            .catch((error: unknown) => {
              notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
            })
            .finally(() => setBusy(false));
        }}
      >
        <TextInput
          label={t('seriesTitle')}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          disabled={busy}
        />
        <Button type="submit" loading={busy} disabled={!trimmedTitle}>
          {t('createSeries')}
        </Button>
      </form>

      {items.length === 0 ? (
        <EmptyState title={t('emptySeries')} description={t('emptySeriesHint')} />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((series) => (
            <li
              key={series.id}
              className="flex flex-col overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface transition-shadow hover:shadow-raised"
            >
              <Link href={`/create/short/series/${series.id}`} className="flex flex-1 flex-col p-4">
                <h3 className="truncate text-sm font-semibold">{series.title}</h3>
                {series.description ? (
                  <p className="mt-1 line-clamp-2 text-xs text-muted">{series.description}</p>
                ) : null}
                <p className="mt-3 text-xs text-muted">{series.status}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
