'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Button, IconButton } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import { IconPlus, IconTrash } from '@/components/ui/icons';
import { Badge, EmptyState, ErrorNotice, PageHeading } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { Link, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { isApiError } from '@/lib/api/errors';
import { formatRelative } from '@/lib/format';

import * as scriptApi from './api';
import type { ScriptExtractResult, ScriptSummary } from './api';
import { resetPendingCreate, startCreate, useCreateStreamSnapshot } from './create-stream-store';
import { composeScriptIdea, ScriptSourceField } from './script-source-field';

const IDEA_MAX_LENGTH = 2000;

export function ScriptLanding({
  seriesId,
  initialIdea,
}: { seriesId?: string; initialIdea?: string } = {}) {
  const t = useTranslations('scriptStudio');
  const tActions = useTranslations('actions');
  const { status: sessionStatus } = useSession();
  const router = useRouter();
  const { notify } = useToast();
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
  const [extracted, setExtracted] = useState<ScriptExtractResult | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [scripts, setScripts] = useState<ScriptSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [deletingScript, setDeletingScript] = useState<ScriptSummary | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [autoOpenedForSeriesId, setAutoOpenedForSeriesId] = useState<string | undefined>(undefined);
  // The "用于文案创作" jump from a settled `video_analysis` job's result — a
  // separate flag from `autoOpenedForSeriesId` above because the two deep
  // links never carry both params at once, but each has to compare against
  // its own remembered value so a re-render with the same query string
  // doesn't reopen a dialog the user already closed.
  const [autoOpenedForIdea, setAutoOpenedForIdea] = useState<string | undefined>(undefined);

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

  // Arriving from a series' "新增一集" link — jump straight to the create
  // dialog instead of making the user find the button again. Adjusted during
  // render (rather than in an effect) so it happens once per seriesId without
  // an extra render/commit round trip.
  if (sessionStatus === 'authenticated' && seriesId && autoOpenedForSeriesId !== seriesId) {
    setAutoOpenedForSeriesId(seriesId);
    resetPendingCreate();
    setExtracted(null);
    setDialogOpen(true);
  } else if (
    sessionStatus === 'authenticated' &&
    initialIdea &&
    autoOpenedForIdea !== initialIdea
  ) {
    setAutoOpenedForIdea(initialIdea);
    resetPendingCreate();
    setTitle('');
    setIdea(initialIdea);
    setExtracted(null);
    setDialogOpen(true);
  }

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
    setExtracted(null);
    setDialogOpen(true);
  };

  const closeDialog = () => {
    if (pending) return;
    setDialogOpen(false);
  };

  const closeDeleteDialog = () => {
    if (deleteBusy) return;
    setDeletingScript(null);
    setDeleteError(null);
  };

  const confirmDelete = async () => {
    if (!deletingScript) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await scriptApi.deleteScript(deletingScript.episode_id);
      setScripts((prev) => prev.filter((s) => s.episode_id !== deletingScript.episode_id));
      notify(t('deleteScriptDone'), 'success');
      setDeletingScript(null);
    } catch (error: unknown) {
      setDeleteError(isApiError(error) ? error.message : t('deleteScriptFailed'));
    } finally {
      setDeleteBusy(false);
    }
  };

  const submit = () => {
    const mergedIdea = composeScriptIdea(idea, extracted?.text ?? '');
    if (!mergedIdea || pending) return;
    // Navigates the instant the backend names the new episode (the `start`
    // frame, sent before any LLM token — see `create-stream-store.ts`)
    // instead of waiting for the whole first draft to finish streaming, so
    // the user lands on the real script-writing workspace to watch it
    // generate rather than being stuck in this dialog.
    startCreate(
      { title: title.trim(), idea: mergedIdea, referencedSkillIds: [], seriesId },
      { onEpisodeReady: (episodeId) => router.push(`/create/script/${episodeId}`) },
    );
  };

  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        title={t('title')}
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
              <li key={script.episode_id} className="relative">
                <Link
                  href={`/create/script/${script.episode_id}`}
                  className="flex flex-col gap-1 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3 pr-14 transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  <div className="flex items-center gap-2 pr-2">
                    <p className="truncate font-medium">{script.title || t('untitled')}</p>
                    {script.turn_count === 0 ? (
                      <Badge tone="amber">{t('scriptPending')}</Badge>
                    ) : null}
                  </div>
                  {script.turn_count === 0 ? (
                    <p className="line-clamp-1 text-xs text-muted">{t('scriptPendingHint')}</p>
                  ) : script.logline ? (
                    <p className="line-clamp-1 text-xs text-muted">{script.logline}</p>
                  ) : null}
                  <p className="text-xs text-muted">
                    {t('turnCount', { count: script.turn_count })} ·{' '}
                    {formatRelative(script.updated_at, locale)}
                  </p>
                </Link>
                <IconButton
                  label={t('deleteScript')}
                  variant="ghost"
                  size="sm"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-danger"
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setDeletingScript(script);
                  }}
                >
                  <IconTrash className="size-4" />
                </IconButton>
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
            <Button
              loading={pending}
              disabled={composeScriptIdea(idea, extracted?.text ?? '').length === 0}
              onClick={submit}
            >
              {t('generate')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {seriesId ? <p className="text-xs text-muted">{t('newScriptForSeriesHint')}</p> : null}
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
            hint={t('ideaHint')}
            placeholder={t('ideaPlaceholder')}
            value={idea}
            maxLength={IDEA_MAX_LENGTH}
            disabled={pending}
            className="min-h-28"
            onChange={(event) => setIdea(event.target.value)}
          />
          <ScriptSourceField extracted={extracted} onChange={setExtracted} disabled={pending} />
        </div>
      </Dialog>

      <Dialog
        open={deletingScript !== null}
        onClose={closeDeleteDialog}
        title={t('deleteScriptConfirmTitle')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={closeDeleteDialog} disabled={deleteBusy}>
              {tActions('cancel')}
            </Button>
            <Button variant="danger" loading={deleteBusy} onClick={() => void confirmDelete()}>
              {tActions('confirm')}
            </Button>
          </>
        }
      >
        {deleteError ? <ErrorNotice title={deleteError} /> : null}
        <p className="text-sm text-muted">{t('deleteScriptConfirmBody')}</p>
      </Dialog>
    </div>
  );
}
