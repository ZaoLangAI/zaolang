'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { EmptyState, PageHeading } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';

import * as editorApi from './api';

export function DramaLanding() {
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
        else notify(isApiError(error) ? error.message : t('unavailable'), 'error');
        setLoaded(true);
      });
  }, [notify, status, t]);

  if (status === 'anonymous') {
    return <SignInPrompt description={t('signInHint')} />;
  }
  if (status === 'loading' || !loaded) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('loading')} />
      </div>
    );
  }
  if (unavailable) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
        <EmptyState title={t('unavailable')} description={t('unavailableHint')} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
      <p className="text-sm text-muted">{t('openFromJobHint')}</p>
      <form
        className="flex flex-col gap-3 sm:flex-row sm:items-end"
        onSubmit={(event) => {
          event.preventDefault();
          setBusy(true);
          void editorApi
            .createDramaSeries(title.trim() || t('title'))
            .then((series) => {
              setItems((current) => [series, ...current]);
              setTitle('');
              notify(t('seriesCreated'), 'success');
            })
            .catch((error: unknown) => {
              if (isApiError(error) && error.isNotFound) setUnavailable(true);
              else notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
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
        <Button type="submit" loading={busy}>
          {t('createSeries')}
        </Button>
      </form>
      {items.length === 0 ? (
        <EmptyState title={t('emptySeries')} description={t('emptySeriesHint')} />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((series) => (
            <li
              key={series.id}
              className="rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3"
            >
              <p className="font-medium">{series.title}</p>
              <p className="text-xs text-muted">{series.status}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
