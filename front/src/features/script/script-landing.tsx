'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import { IconPlus } from '@/components/ui/icons';
import { EmptyState, ErrorNotice, PageHeading } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { Link, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { isApiError } from '@/lib/api/errors';
import { formatRelative } from '@/lib/format';

import * as scriptApi from './api';
import type { ScriptSummary } from './api';
import { resetPendingCreate, startCreate, useCreateStreamSnapshot } from './create-stream-store';

const IDEA_MAX_LENGTH = 2000;

export function ScriptLanding() {
  const t = useTranslations('scriptStudio');
  const tActions = useTranslations('actions');
  const { status: sessionStatus } = useSession();
  const router = useRouter();
  const locale = useLocale() as Locale;
  // Scoped to `episodeId === null`: the brief window between submitting and
  // the `start` frame naming a fresh episode. Once an episode exists, the
  // stream keeps running in the shared store regardless of this page's
  // lifetime — see `create-stream-store.ts` — and `ScriptEditor` picks it up
  // on the destination route instead.
  const createSnapshot = useCreateStreamSnapshot();
  const pending = createSnapshot.episodeId === null && createSnapshot.streaming;
  const pendingError = createSnapshot.episodeId === null ? createSnapshot.error : null;

  const [title, setTitle] = useState('');
  const [idea, setIdea] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [scripts, setScripts] = useState<ScriptSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  useEffect(() => {
    if (sessionStatus !== 'authenticated') return;
    void scriptApi
      .listScripts()
      .then((rows) => setScripts(rows))
      .catch((error: unknown) => {
        setListError(isApiError(error) ? error.message : t('unavailable'));
      })
      .finally(() => setLoaded(true));
  }, [sessionStatus, t]);

  if (sessionStatus === 'anonymous') {
    return <SignInPrompt description={t('signInHint')} />;
  }
  if (sessionStatus === 'loading') {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('loading')} />
      </div>
    );
  }

  const openCreate = () => {
    resetPendingCreate();
    setTitle('');
    setIdea('');
    setDialogOpen(true);
  };

  const closeDialog = () => {
    if (pending) return;
    setDialogOpen(false);
  };

  const submit = () => {
    const trimmedIdea = idea.trim();
    if (!trimmedIdea || pending) return;
    // Navigates the instant the backend names the new episode (the `start`
    // frame, sent before any LLM token — see `create-stream-store.ts`)
    // instead of waiting for the whole first draft to finish streaming, so
    // the user lands on the real script-writing workspace to watch it
    // generate rather than being stuck in this dialog.
    startCreate(
      { title: title.trim(), idea: trimmedIdea, referencedSkillIds: [] },
      { onEpisodeReady: (episodeId) => router.push(`/create/script/${episodeId}`) },
    );
  };

  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        eyebrow={t('eyebrow')}
        title={t('title')}
        description={t('subtitle')}
        actions={
          <Button onClick={openCreate} icon={<IconPlus className="size-4" />}>
            {t('newScript')}
          </Button>
        }
      />

      {!loaded ? (
        <div className="grid min-h-[20vh] place-items-center">
          <Spinner label={t('loading')} />
        </div>
      ) : listError ? (
        <ErrorNotice title={listError} />
      ) : scripts.length === 0 ? (
        <EmptyState
          title={t('emptyScripts')}
          description={t('emptyScriptsHint')}
          action={
            <Button onClick={openCreate} icon={<IconPlus className="size-4" />}>
              {t('newScript')}
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-muted">{t('myScripts')}</h2>
          <ul className="flex flex-col gap-2">
            {scripts.map((script) => (
              <li key={script.episode_id}>
                <Link
                  href={`/create/script/${script.episode_id}`}
                  className="flex flex-col gap-1 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  <p className="font-medium">{script.title || t('untitled')}</p>
                  {script.logline ? (
                    <p className="line-clamp-1 text-xs text-muted">{script.logline}</p>
                  ) : null}
                  <p className="text-xs text-muted">
                    {t('turnCount', { count: script.turn_count })} ·{' '}
                    {formatRelative(script.updated_at, locale)}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Dialog
        open={dialogOpen}
        onClose={closeDialog}
        title={t('newScript')}
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={closeDialog} disabled={pending}>
              {tActions('cancel')}
            </Button>
            <Button loading={pending} disabled={idea.trim().length === 0} onClick={submit}>
              {t('generate')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {pendingError ? <ErrorNotice title={pendingError} /> : null}
          <TextInput
            label={t('scriptTitle')}
            placeholder={t('scriptTitlePlaceholder')}
            value={title}
            maxLength={60}
            disabled={pending}
            onChange={(event) => setTitle(event.target.value)}
          />
          <TextArea
            label={t('ideaLabel')}
            placeholder={t('ideaPlaceholder')}
            value={idea}
            maxLength={IDEA_MAX_LENGTH}
            disabled={pending}
            className="min-h-28"
            onChange={(event) => setIdea(event.target.value)}
          />
        </div>
      </Dialog>
    </div>
  );
}
