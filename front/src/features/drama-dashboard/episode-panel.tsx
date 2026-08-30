'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Poster } from '@/components/media/poster';
import { BackLink } from '@/components/ui/back-link';
import { Button } from '@/components/ui/button';
import { Select, TextInput } from '@/components/ui/field';
import {
  IconClock,
  IconImage,
  IconMessage,
  IconTrash,
  IconUser,
  IconWand,
} from '@/components/ui/icons';
import { Badge, EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import * as editorApi from '@/features/editor/api';
import * as scriptApi from '@/features/script/api';
import { Link, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { Draft, WorkDetail } from '@/lib/api/types';
import { formatRelative } from '@/lib/format';

import { AnalyticsPanel } from './analytics-panel';
import { DeleteEpisodeDialog } from './delete-episode-dialog';
import { pascalCase } from './format';
import { generatedVideoDetailHref, isGeneratedVideoCard } from './generated-video-href';
import { PublishPanel } from './publish-panel';

const EPISODE_KINDS = ['main', 'trailer', 'teaser', 'bts', 'recap', 'other'] as const;
const STATUSES = ['draft', 'production', 'published', 'archived'] as const;
const VIDEO_CONTENT_TYPES = new Set(['draft', 'work']);
const META_SAVE_DEBOUNCE_MS = 500;

function draftCardLabel(draft: Draft | undefined, fallback: string): string {
  const prompt = draft?.params?.prompt;
  if (typeof prompt === 'string' && prompt.trim()) {
    const firstLine = prompt.trim().split('\n')[0] ?? '';
    return firstLine || fallback;
  }
  return draft?.title?.trim() || fallback;
}

/**
 * `/create/short/episodes/{episodeId}`: the episode's own workspace.
 *
 * Layout is main content + a right-hand "剧集信息" sidebar (title/kind/
 * status, saved automatically on change — no submit button). Cut/version
 * history no longer lists here at all; it lives inside the editor itself
 * (`HistoryPanel`) and always resumes at the cut's current head.
 * "关联已有素材" (manual attach-by-id) is gone — the only content this
 * page still surfaces is the "生成的视频" candidates (auto-linked via
 * `linkEpisodeId`, shown only once a draft has an output) and the "最终成片" list, which is populated purely by
 * what the editor has actually exported. Connect/publish/analytics only
 * ever render for the one export promoted to `episode.canonical_work_id`.
 * The old standalone "打开文案" button is gone too — its destination is
 * now a clickable script-summary card (prompt/character/scene counts,
 * timestamps) fetched on its own and rendered ahead of "生成的视频".
 * Each generated-video poster links to that clip's detail (`/work/{id}`
 * once published, otherwise `/jobs/{latest_job_id}`); "进入剪辑" stays
 * a separate action and must not ride the same navigation.
 */
export function EpisodePanel({ episodeId }: { episodeId: string }) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');
  const locale = useLocale() as Locale;
  const { status } = useSession();
  const { notify } = useToast();
  const router = useRouter();

  const [episode, setEpisode] = useState<editorApi.DramaEpisode | null>(null);
  const [links, setLinks] = useState<editorApi.EpisodeContentLink[]>([]);
  const [cuts, setCuts] = useState<editorApi.EpisodeCut[]>([]);
  const [exports, setExports] = useState<editorApi.EpisodeExport[]>([]);
  const [script, setScript] = useState<scriptApi.ScriptDetail | null>(null);
  const [draftDetails, setDraftDetails] = useState<Record<string, Draft>>({});
  const [workDetails, setWorkDetails] = useState<Record<string, WorkDetail>>({});
  const [loaded, setLoaded] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [enteringEditorFor, setEnteringEditorFor] = useState<string | null>(null);
  const [settingCanonicalId, setSettingCanonicalId] = useState<string | null>(null);
  const [clearingCanonical, setClearingCanonical] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const [title, setTitle] = useState('');
  const [kind, setKind] = useState('main');
  const [episodeStatus, setEpisodeStatus] = useState('draft');
  const skipNextAutoSaveRef = useRef(true);
  const [justSaved, setJustSaved] = useState(false);
  const savedIndicatorTimeoutRef = useRef<number | null>(null);

  const load = useCallback(() => {
    if (status !== 'authenticated') return;
    void Promise.all([
      editorApi.getEpisode(episodeId),
      editorApi.listContentLinks(episodeId),
      editorApi.listEpisodeCuts(episodeId),
    ])
      .then(([episodeRow, linkRows, cutRows]) => {
        setEpisode(episodeRow);
        skipNextAutoSaveRef.current = true;
        setTitle(episodeRow.title);
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

  const refreshExports = useCallback(() => {
    void editorApi
      .listEpisodeExports(episodeId)
      .then(setExports)
      .catch(() => undefined);
  }, [episodeId]);

  useEffect(() => {
    if (status !== 'authenticated') return;
    refreshExports();
  }, [refreshExports, status]);

  // Fetched independently from `load()`: a missing/flag-gated script must
  // not block the rest of the episode workspace, it just hides the card.
  useEffect(() => {
    if (status !== 'authenticated') return;
    void scriptApi
      .getScript(episodeId)
      .then(setScript)
      .catch(() => setScript(null));
  }, [episodeId, status]);

  // Video links only carry a bare `content_ref_id`; `draft`-typed ones need
  // their own record fetched to know the underlying asset (for "进入剪辑").
  useEffect(() => {
    const draftIds = links
      .filter((link) => link.content_type === 'draft')
      .map((link) => link.content_ref_id)
      .filter((id) => !(id in draftDetails));
    if (draftIds.length === 0) return;
    void Promise.all(
      draftIds.map((id) =>
        api
          .get<Draft>(`/v1/drafts/${id}`)
          .then((draft) => [id, draft] as const)
          .catch(() => null),
      ),
    ).then((results) => {
      setDraftDetails((current) => {
        const next = { ...current };
        for (const entry of results) {
          if (entry) next[entry[0]] = entry[1];
        }
        return next;
      });
    });
    // Only re-runs when a not-yet-fetched draft id shows up.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [links]);

  useEffect(() => {
    const workIds = links
      .filter((link) => link.content_type === 'work')
      .map((link) => link.content_ref_id)
      .filter((id) => !(id in workDetails));
    if (workIds.length === 0) return;
    void Promise.all(
      workIds.map((id) =>
        api
          .get<WorkDetail>(`/v1/works/${id}`)
          .then((work) => [id, work] as const)
          .catch(() => null),
      ),
    ).then((results) => {
      setWorkDetails((current) => {
        const next = { ...current };
        for (const entry of results) {
          if (entry) next[entry[0]] = entry[1];
        }
        return next;
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [links]);

  // Debounced auto-save: fires ~500ms after title/kind/status settle, and
  // never on the values a fresh load just seeded (guarded by the ref reset
  // inside `load`'s `.then`).
  useEffect(() => {
    if (skipNextAutoSaveRef.current) {
      skipNextAutoSaveRef.current = false;
      return;
    }
    // A fresh edit invalidates any "已保存" left over from the previous
    // cycle — it shouldn't linger next to fields the user is changing again.
    setJustSaved(false);
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;
    const handle = window.setTimeout(() => {
      void editorApi
        .updateEpisode(episodeId, {
          title: trimmedTitle,
          episode_kind: kind,
          status: episodeStatus,
        })
        .then((updated) => {
          setEpisode(updated);
          setJustSaved(true);
          if (savedIndicatorTimeoutRef.current) window.clearTimeout(savedIndicatorTimeoutRef.current);
          savedIndicatorTimeoutRef.current = window.setTimeout(() => setJustSaved(false), 2000);
        })
        .catch((error: unknown) => {
          notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
        });
    }, META_SAVE_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, kind, episodeStatus]);

  useEffect(() => {
    return () => {
      if (savedIndicatorTimeoutRef.current) window.clearTimeout(savedIndicatorTimeoutRef.current);
    };
  }, []);

  const enterEditor = (link: editorApi.EpisodeContentLink) => {
    const draftIdParam = link.content_type === 'draft' ? link.content_ref_id : null;
    const suffix = draftIdParam ? `?draftId=${encodeURIComponent(draftIdParam)}` : '';
    const existingCut = cuts[0];
    if (existingCut) {
      router.push(`/studio-editor/${existingCut.id}${suffix}`);
      return;
    }
    const assetId =
      link.content_type === 'draft' ? (draftDetails[link.content_ref_id]?.output_asset_id ?? null) : null;
    if (!assetId) {
      notify(t('enterEditorNoAsset'), 'error');
      return;
    }
    setEnteringEditorFor(link.id);
    void editorApi
      .createCutFromAsset(episodeId, { asset_id: assetId })
      .then((cut) => {
        router.push(`/studio-editor/${cut.id}${suffix}`);
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setEnteringEditorFor(null));
  };

  const setFinalCut = (workId: string) => {
    setSettingCanonicalId(workId);
    void editorApi
      .setCanonicalWork(episodeId, workId)
      .then((updated) => {
        setEpisode(updated);
        notify(t('canonicalWorkSet'), 'success');
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setSettingCanonicalId(null));
  };

  const clearFinalCut = () => {
    setClearingCanonical(true);
    void editorApi
      .setCanonicalWork(episodeId, null)
      .then((updated) => {
        setEpisode(updated);
        notify(t('canonicalWorkCleared'), 'success');
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setClearingCanonical(false));
  };

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

  const videoLinks = links.filter((link) => {
    if (!VIDEO_CONTENT_TYPES.has(link.content_type)) return false;
    const draft = link.content_type === 'draft' ? draftDetails[link.content_ref_id] : undefined;
    return isGeneratedVideoCard({ contentType: link.content_type, draft });
  });
  const scriptDoc = script?.script;
  const mainPrompt = script?.turns[0]?.user_message ?? '';
  const hasScriptContent = Boolean(
    scriptDoc &&
      ((script?.turns.length ?? 0) > 0 ||
        scriptDoc.title ||
        scriptDoc.logline ||
        scriptDoc.characters.length > 0 ||
        scriptDoc.scenes.length > 0),
  );
  // `script` fetched fine but has no turns yet: either its first draft is
  // still streaming (in this tab or another) or failed outright — either
  // way there's something to click into and continue/retry, unlike a
  // script studio that's flag-gated off entirely (`script === null`),
  // which keeps the generic `scriptSummaryEmpty` copy below.
  const scriptPending = script !== null && !hasScriptContent;

  return (
    <div className="flex flex-col gap-6">
      <BackLink href={`/create/short/series/${episode.series_id}`}>{t('backToSeries')}</BackLink>

      <div className="grid gap-8 lg:grid-cols-[1fr_280px]">
        <aside className="order-1 flex flex-col gap-4 lg:order-2 lg:sticky lg:top-6 lg:self-start">
          <section className="flex flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
            <SectionHeading
              title={t('episodeMetaTitle')}
              action={justSaved ? <span className="text-xs text-muted">{tActions('saved')}</span> : null}
            />
            <TextInput
              label={t('episodeTitleFieldLabel')}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
            <Select
              label={t('episodeKindFieldLabel')}
              value={kind}
              onChange={(event) => setKind(event.target.value)}
              options={EPISODE_KINDS.map((value) => ({
                value,
                label: t(`episodeKind${pascalCase(value)}`),
              }))}
            />
            <Select
              label={t('episodeStatusFieldLabel')}
              value={episodeStatus}
              onChange={(event) => setEpisodeStatus(event.target.value)}
              options={STATUSES.map((value) => ({ value, label: t(`status${pascalCase(value)}`) }))}
            />
            <Button
              size="sm"
              variant="danger"
              icon={<IconTrash className="size-3.5" />}
              disabled={cuts.length > 0}
              title={cuts.length > 0 ? t('deleteEpisodeBlockedHasCuts') : undefined}
              onClick={() => setDeleteOpen(true)}
            >
              {t('deleteEpisodeAction')}
            </Button>
          </section>
        </aside>

        <div className="order-2 flex flex-col gap-8 lg:order-1">
          <Link
            href={`/create/script/${episode.id}`}
            className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4 transition-colors hover:border-border-strong hover:bg-surface-soft"
          >
            {hasScriptContent && script && scriptDoc ? (
              <>
                <div className="flex items-center gap-2 text-sm font-medium">
                  <IconMessage className="size-4 text-muted" />
                  <span className="truncate">{scriptDoc.title || episode.title}</span>
                </div>
                {mainPrompt ? (
                  <p className="line-clamp-2 text-sm text-muted">
                    {t('scriptSummaryPromptLabel')}：{mainPrompt}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-4 text-xs text-muted">
                  <span className="inline-flex items-center gap-1.5">
                    <IconUser className="size-3.5" />
                    {t('scriptSummaryCharacterCount', { count: scriptDoc.characters.length })}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <IconImage className="size-3.5" />
                    {t('scriptSummarySceneCount', { count: scriptDoc.scenes.length })}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <IconClock className="size-3.5" />
                    {t('scriptSummaryCreatedAt', { time: formatRelative(script.created_at, locale) })}
                    {' · '}
                    {t('scriptSummaryUpdatedAt', { time: formatRelative(script.updated_at, locale) })}
                  </span>
                </div>
              </>
            ) : scriptPending ? (
              <div className="flex items-center gap-2 text-sm text-muted">
                <IconMessage className="size-4" />
                {t('scriptSummaryPending')}
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm text-muted">
                <IconMessage className="size-4" />
                {t('scriptSummaryEmpty')}
              </div>
            )}
          </Link>

          <section>
            <SectionHeading title={t('generatedVideosTitle')} description={t('generatedVideosHint')} />
            {videoLinks.length === 0 ? (
              <p className="text-sm text-muted">{t('generatedVideosEmpty')}</p>
            ) : (
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {videoLinks.map((link) => {
                  const typeLabel = t(`contentType${pascalCase(link.content_type)}`);
                  const draft =
                    link.content_type === 'draft' ? draftDetails[link.content_ref_id] : undefined;
                  const work =
                    link.content_type === 'work' ? workDetails[link.content_ref_id] : undefined;
                  const label =
                    link.content_type === 'draft'
                      ? draftCardLabel(draft, typeLabel)
                      : (work?.title ?? typeLabel);
                  const detailHref = generatedVideoDetailHref({
                    contentType: link.content_type,
                    contentRefId: link.content_ref_id,
                    draft,
                  });
                  const poster = (
                    <>
                      {draft ? (
                        <Poster
                          src={draft.output_media_type === 'audio' ? null : draft.output_url}
                          alt={label}
                          mediaType={draft.output_media_type}
                          aspect="video"
                          className="rounded-none transition-transform duration-300 group-hover:scale-[1.01]"
                          lazy
                        />
                      ) : (
                        <Poster
                          src={work?.cover_url ?? work?.current_version?.media_url}
                          alt={label}
                          mediaType={
                            work?.cover_url
                              ? undefined
                              : (work?.current_version?.media_type ?? work?.media_type)
                          }
                          aspect="video"
                          className="rounded-none transition-transform duration-300 group-hover:scale-[1.01]"
                          lazy
                        />
                      )}
                      <div className="absolute inset-x-0 bottom-0 flex items-center gap-3 bg-gradient-to-t from-surface/95 via-surface/55 to-transparent px-3 py-3 pt-10">
                        <p className="min-w-0 flex-1 truncate text-xs text-text">{label}</p>
                        <Button
                          size="sm"
                          variant="secondary"
                          className="shrink-0 whitespace-nowrap"
                          icon={<IconWand className="size-3.5" />}
                          loading={enteringEditorFor === link.id}
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            enterEditor(link);
                          }}
                        >
                          {t('enterEditorAction')}
                        </Button>
                      </div>
                    </>
                  );
                  return (
                    <li
                      key={link.id}
                      className="group overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface transition-colors hover:border-border-strong"
                    >
                      {detailHref ? (
                        <Link
                          href={detailHref}
                          aria-label={t('generatedVideoOpenDetail')}
                          className="relative block focus-visible:outline-2"
                        >
                          {poster}
                        </Link>
                      ) : (
                        <div className="relative">{poster}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section>
            <SectionHeading title={t('finalCutsTitle')} description={t('finalCutsHint')} />
            {exports.length === 0 ? (
              <p className="text-sm text-muted">{t('finalCutsEmpty')}</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {exports.map((item) => (
                  <li
                    key={item.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3"
                  >
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <span className="truncate text-sm">
                        {item.profile_key} · {item.width}×{item.height} · {item.format}
                      </span>
                      <Badge tone={item.status === 'succeeded' ? 'success' : item.status === 'failed' ? 'danger' : 'neutral'}>
                        {t(`exportStatus${pascalCase(item.status)}`)}
                      </Badge>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {item.output_url ? (
                        <a
                          href={item.output_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-border px-3 py-1.5 text-xs transition-colors hover:border-border-strong hover:bg-surface-soft"
                        >
                          {t('finalCutDownloadAction')}
                        </a>
                      ) : null}
                      {item.is_canonical ? (
                        <>
                          <Badge tone="success">{t('finalCutCurrentBadge')}</Badge>
                          <Button size="sm" variant="ghost" loading={clearingCanonical} onClick={clearFinalCut}>
                            {t('canonicalWorkClear')}
                          </Button>
                        </>
                      ) : item.published_work_id ? (
                        <Button
                          size="sm"
                          loading={settingCanonicalId === item.published_work_id}
                          onClick={() => setFinalCut(item.published_work_id!)}
                        >
                          {t('finalCutSetAction')}
                        </Button>
                      ) : item.bound_draft_id ? (
                        <Link
                          href={`/publish/${item.bound_draft_id}`}
                          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-border px-3 py-1.5 text-xs transition-colors hover:border-border-strong hover:bg-surface-soft"
                        >
                          {t('finalCutPublishFirstAction')}
                        </Link>
                      ) : (
                        <span className="text-xs text-muted">{t('finalCutDownloadOnlyHint')}</span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {episode.canonical_work_id ? (
            <section>
              <SectionHeading title={t('connectPublishTitle')} description={t('connectPublishHint')} />
              <p className="mb-3 text-xs text-muted">
                {t('connectPublishSettingsHint')}{' '}
                <Link
                  href={{ pathname: '/profile/settings', query: { section: 'platforms' } }}
                  className="text-primary underline"
                >
                  {t('connectPublishSettingsLink')}
                </Link>
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <PublishPanel workId={episode.canonical_work_id} />
                <AnalyticsPanel workId={episode.canonical_work_id} />
              </div>
            </section>
          ) : null}
        </div>
      </div>

      <DeleteEpisodeDialog
        episodeId={episode.id}
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onDeleted={() => {
          setDeleteOpen(false);
          router.push(`/create/short/series/${episode.series_id}`);
        }}
      />
    </div>
  );
}
