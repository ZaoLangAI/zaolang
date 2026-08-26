'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { BackLink } from '@/components/ui/back-link';
import { Button, IconButton } from '@/components/ui/button';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { IconTrash } from '@/components/ui/icons';
import { Badge, EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import * as editorApi from '@/features/editor/api';
import { Link } from '@/i18n/navigation';
import { isApiError } from '@/lib/api/errors';

import { AttachContentPicker } from './attach-content-picker';
import { pascalCase } from './format';

const EPISODE_KINDS = ['main', 'trailer', 'teaser', 'bts', 'recap', 'other'] as const;
const STATUSES = ['draft', 'production', 'published', 'archived'] as const;
const ROLE_ORDER = ['candidate', 'reference', 'behind_the_scenes', 'final'] as const;

/**
 * `/create/short/episodes/{episodeId}`: one episode's metadata, its content
 * links (grouped by role), its canonical work, and the cuts already made
 * from it. Cuts themselves are only ever created from a finished video job's
 * "enter editor" button — this page just lists what already exists.
 */
export function EpisodePanel({ episodeId }: { episodeId: string }) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');
  const { status } = useSession();
  const { notify } = useToast();

  const [episode, setEpisode] = useState<editorApi.DramaEpisode | null>(null);
  const [links, setLinks] = useState<editorApi.EpisodeContentLink[]>([]);
  const [cuts, setCuts] = useState<editorApi.EpisodeCut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const [title, setTitle] = useState('');
  const [synopsis, setSynopsis] = useState('');
  const [kind, setKind] = useState('main');
  const [episodeStatus, setEpisodeStatus] = useState('draft');
  const [savingMeta, setSavingMeta] = useState(false);

  const [workIdInput, setWorkIdInput] = useState('');
  const [settingWork, setSettingWork] = useState(false);

  const load = useCallback(() => {
    if (status !== 'authenticated') return;
    void Promise.all([
      editorApi.getEpisode(episodeId),
      editorApi.listContentLinks(episodeId),
      editorApi.listEpisodeCuts(episodeId),
    ])
      .then(([episodeRow, linkRows, cutRows]) => {
        setEpisode(episodeRow);
        setTitle(episodeRow.title);
        setSynopsis(episodeRow.synopsis ?? '');
        setKind(episodeRow.episode_kind);
        setEpisodeStatus(episodeRow.status);
        setLinks(linkRows);
        setCuts(cutRows);
        setLoaded(true);
      })
      .catch((error: unknown) => {
        if (isApiError(error) && error.isNotFound) setNotFound(true);
        else notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
        setLoaded(true);
      });
  }, [episodeId, notify, status, t]);

  useEffect(() => {
    load();
  }, [load]);

  const refreshLinks = useCallback(() => {
    void editorApi
      .listContentLinks(episodeId)
      .then(setLinks)
      .catch(() => undefined);
  }, [episodeId]);

  if (status === 'anonymous') return <SignInPrompt description={t('signInHint')} />;
  if (status === 'loading' || !loaded) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('dashboardLoading')} />
      </div>
    );
  }
  if (notFound || !episode) {
    return (
      <EmptyState title={t('dashboardUnavailable')} description={t('dashboardUnavailableHint')} />
    );
  }

  const saveMeta = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;
    setSavingMeta(true);
    void editorApi
      .updateEpisode(episodeId, {
        title: trimmedTitle,
        synopsis: synopsis.trim() ? synopsis.trim() : undefined,
        episode_kind: kind,
        status: episodeStatus,
      })
      .then((updated) => {
        setEpisode(updated);
        notify(t('episodeSaveSuccess'), 'success');
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setSavingMeta(false));
  };

  const removeLink = (linkId: string) => {
    void editorApi
      .deleteContentLink(episodeId, linkId)
      .then(() => {
        setLinks((current) => current.filter((link) => link.id !== linkId));
        notify(t('linkDeleted'), 'success');
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      });
  };

  const submitCanonicalWork = (event: React.FormEvent) => {
    event.preventDefault();
    const workId = workIdInput.trim();
    if (!workId) return;
    setSettingWork(true);
    void editorApi
      .setCanonicalWork(episodeId, workId)
      .then((updated) => {
        setEpisode(updated);
        setWorkIdInput('');
        notify(t('canonicalWorkSet'), 'success');
        refreshLinks();
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setSettingWork(false));
  };

  const clearCanonicalWork = () => {
    setSettingWork(true);
    void editorApi
      .setCanonicalWork(episodeId, null)
      .then((updated) => {
        setEpisode(updated);
        notify(t('canonicalWorkCleared'), 'success');
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setSettingWork(false));
  };

  const groupedLinks = new Map<string, editorApi.EpisodeContentLink[]>();
  for (const link of links) {
    const list = groupedLinks.get(link.role) ?? [];
    list.push(link);
    groupedLinks.set(link.role, list);
  }

  const trimmedTitle = title.trim();

  return (
    <div className="flex flex-col gap-8">
      <BackLink href={`/create/short/series/${episode.series_id}`}>{t('backToSeries')}</BackLink>

      <section>
        <SectionHeading title={t('episodeMetaTitle')} />
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={saveMeta}>
          <TextInput
            label={t('episodeTitleFieldLabel')}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            disabled={savingMeta}
          />
          <Select
            label={t('episodeKindFieldLabel')}
            value={kind}
            onChange={(event) => setKind(event.target.value)}
            options={EPISODE_KINDS.map((value) => ({
              value,
              label: t(`episodeKind${pascalCase(value)}`),
            }))}
            disabled={savingMeta}
          />
          <Select
            label={t('episodeStatusFieldLabel')}
            value={episodeStatus}
            onChange={(event) => setEpisodeStatus(event.target.value)}
            options={STATUSES.map((value) => ({ value, label: t(`status${pascalCase(value)}`) }))}
            disabled={savingMeta}
          />
          <div className="sm:col-span-2">
            <TextArea
              label={t('episodeSynopsisFieldLabel')}
              value={synopsis}
              onChange={(event) => setSynopsis(event.target.value)}
              disabled={savingMeta}
            />
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" loading={savingMeta} disabled={!trimmedTitle}>
              {tActions('save')}
            </Button>
          </div>
        </form>
      </section>

      <section>
        <SectionHeading title={t('contentLinksTitle')} description={t('contentLinksHint')} />
        {links.length === 0 ? (
          <EmptyState title={t('contentLinksEmpty')} />
        ) : (
          <div className="flex flex-col gap-4">
            {ROLE_ORDER.filter((role) => groupedLinks.has(role)).map((role) => (
              <div key={role}>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                  {t(`role${pascalCase(role)}`)}
                </p>
                <ul className="flex flex-col gap-2">
                  {groupedLinks.get(role)!.map((link) => (
                    <li
                      key={link.id}
                      className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3"
                    >
                      <span className="min-w-0 truncate text-sm">
                        {t(`contentType${pascalCase(link.content_type)}`)} · {link.content_ref_id}
                      </span>
                      <IconButton label={t('deleteLinkAction')} onClick={() => removeLink(link.id)}>
                        <IconTrash className="size-4" />
                      </IconButton>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
        <div className="mt-4">
          <AttachContentPicker episodeId={episodeId} onLinked={refreshLinks} />
        </div>
      </section>

      <section>
        <SectionHeading title={t('canonicalWorkTitle')} description={t('canonicalWorkHint')} />
        {episode.canonical_work_id ? (
          <div className="flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3">
            <Link
              href={`/work/${episode.canonical_work_id}`}
              className="min-w-0 truncate text-sm text-primary hover:underline"
            >
              {episode.canonical_work_id}
            </Link>
            <Button size="sm" variant="secondary" loading={settingWork} onClick={clearCanonicalWork}>
              {t('canonicalWorkClear')}
            </Button>
          </div>
        ) : null}
        {episode.canonical_work_id ? null : (
          <>
            <p className="mb-3 text-sm text-muted">{t('canonicalWorkEmpty')}</p>
            <form
              className="flex flex-col gap-3 sm:flex-row sm:items-end"
              onSubmit={submitCanonicalWork}
            >
              <TextInput
                label={t('canonicalWorkInputLabel')}
                value={workIdInput}
                onChange={(event) => setWorkIdInput(event.target.value)}
                disabled={settingWork}
              />
              <Button type="submit" loading={settingWork} disabled={!workIdInput.trim()}>
                {t('canonicalWorkSubmit')}
              </Button>
            </form>
          </>
        )}
      </section>

      <section>
        <SectionHeading title={t('cutsTitle')} />
        {cuts.length === 0 ? (
          <p className="text-sm text-muted">{t('cutsEmptyHint')}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {cuts.map((cut) => (
              <li key={cut.id}>
                <Link
                  href={`/create/short/${cut.id}`}
                  className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  <span className="truncate text-sm font-medium">{cut.name}</span>
                  <Badge tone="neutral">{cut.status}</Badge>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
