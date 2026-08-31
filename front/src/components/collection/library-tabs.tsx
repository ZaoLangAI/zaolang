'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { CreateCollectionDialog } from '@/components/collection/create-collection-dialog';
import { EditCollectionDialog } from '@/components/collection/edit-collection-dialog';
import { ManageWorkDialog } from '@/components/collection/manage-work-dialog';
import { DraftPoster } from '@/components/media/draft-poster';
import { Poster } from '@/components/media/poster';
import { CreateSkillDialog } from '@/components/skills/create-skill-dialog';
import { ManageSkillDialog } from '@/components/skills/manage-skill-dialog';
import { SkillCard } from '@/components/skills/skill-card';
import { DeleteWorkDialog } from '@/components/work/delete-work-dialog';
import { PurgeWorkDialog } from '@/components/work/purge-work-dialog';
import { WorkCard } from '@/components/work/work-card';
import { IconButton } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { IconPencil, IconPlus, IconRefresh, IconTrash, IconTrashX } from '@/components/ui/icons';
import { EmptyState, ErrorNotice, Skeleton } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { Link, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type {
  Collection,
  CreationSkillSummary,
  Draft,
  Page,
  TrashWorkSummary,
  WorkSummary,
} from '@/lib/api/types';
import { cn, controlPress } from '@/lib/cn';
import { imageCreationStudioHref, isImageCreationOperation } from '@/lib/image-draft';
import { isVideoCreationOperation, videoCreationStudioHref } from '@/lib/video-draft';
import { useResource } from '@/lib/use-resource';

const TABS = [
  'all',
  'published',
  'drafts',
  'private',
  'bookmarks',
  'trash',
  'collections',
  'skills',
] as const;
type Tab = (typeof TABS)[number];

/**
 * An image- or video-creation draft reopens straight into the studio's
 * inline flow (full version history, continue refining — see
 * `ImageGenerationStudio`/`VideoGenerationStudio`) instead of the publish
 * form; a video draft only once it has an `output_asset_id` (a still-
 * generating/failed one has nothing to show yet, same gate
 * `recent-draft-card.tsx` uses). Every other draft (audio/shortform) still
 * has no "resume the studio" concept, so it keeps going to `/publish/{id}`
 * as before.
 */
function draftResumeHref(draft: Draft): string {
  const operation = draft.params?.operation;
  if (isImageCreationOperation(operation)) {
    return imageCreationStudioHref(draft.id);
  }
  if (isVideoCreationOperation(operation) && draft.output_asset_id) {
    return videoCreationStudioHref(draft.id);
  }
  return `/publish/${draft.id}`;
}

/**
 * Tabbed library.
 *
 * Works and drafts arrive from the server (they also feed the page stats).
 * Bookmarks, trash, collections and skills load the first time that tab is
 * selected — or immediately when `?tab=` deep-links there — so the first
 * paint is not waiting on four unused lists.
 */
export function LibraryTabs({
  initialTab,
  works,
  published,
  privateWorks,
  drafts,
}: {
  initialTab?: string;
  works: WorkSummary[];
  published: WorkSummary[];
  privateWorks: WorkSummary[];
  drafts: Draft[];
}) {
  const t = useTranslations('collectionPage');
  const tVisibility = useTranslations('visibility');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { notify } = useToast();
  const [tab, setTab] = useState<Tab>(
    TABS.includes(initialTab as Tab) ? (initialTab as Tab) : 'all',
  );
  const [createOpen, setCreateOpen] = useState(false);
  const [createSkillOpen, setCreateSkillOpen] = useState(false);
  const [managingSkill, setManagingSkill] = useState<CreationSkillSummary | null>(null);
  const [managingWork, setManagingWork] = useState<WorkSummary | null>(null);
  const [editingCollection, setEditingCollection] = useState<Collection | null>(null);
  const [deletingDraft, setDeletingDraft] = useState<Draft | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [trashingWork, setTrashingWork] = useState<WorkSummary | null>(null);
  const [purgingWork, setPurgingWork] = useState<TrashWorkSummary | null>(null);
  const [restoreBusyId, setRestoreBusyId] = useState<string | null>(null);

  const bookmarks = useResource<Page<WorkSummary>>(
    tab === 'bookmarks' ? '/v1/me/bookmarks?limit=60' : null,
  );
  const trash = useResource<Page<TrashWorkSummary>>(tab === 'trash' ? '/v1/me/trash?limit=60' : null);
  const collections = useResource<Page<Collection>>(
    tab === 'collections' ? '/v1/collections' : null,
  );
  const skills = useResource<Page<CreationSkillSummary>>(tab === 'skills' ? '/v1/skills' : null);

  const labels: Record<Tab, string> = {
    all: t('tabAll'),
    published: t('tabPublished'),
    drafts: t('tabDrafts'),
    private: t('tabPrivate'),
    bookmarks: t('tabBookmarks'),
    trash: t('tabTrash'),
    collections: t('tabCollections'),
    skills: t('tabSkills'),
  };

  const shownWorks =
    tab === 'published'
      ? published
      : tab === 'private'
        ? privateWorks
        : tab === 'bookmarks'
          ? (bookmarks.data?.items ?? [])
          : tab === 'trash'
            ? []
            : works;
  const shownDrafts = tab === 'all' || tab === 'drafts' ? drafts : [];
  const shownTrash = tab === 'trash' ? (trash.data?.items ?? []) : [];
  const collectionItems = collections.data?.items ?? [];
  const skillItems = skills.data?.items ?? [];
  const lazyLoading =
    (tab === 'bookmarks' && bookmarks.status === 'loading') ||
    (tab === 'trash' && trash.status === 'loading') ||
    (tab === 'collections' && collections.status === 'loading') ||
    (tab === 'skills' && skills.status === 'loading');
  const lazyFailed =
    (tab === 'bookmarks' && bookmarks.status === 'failed') ||
    (tab === 'trash' && trash.status === 'failed') ||
    (tab === 'collections' && collections.status === 'failed') ||
    (tab === 'skills' && skills.status === 'failed');
  const empty =
    !lazyLoading &&
    (tab === 'trash'
      ? shownTrash.length === 0
      : tab === 'collections'
        ? collectionItems.length === 0
        : tab === 'skills'
          ? skillItems.length === 0
          : shownWorks.length === 0 && shownDrafts.length === 0);

  const canManageWorks = tab !== 'bookmarks' && tab !== 'trash';

  const restoreWork = async (work: TrashWorkSummary) => {
    setRestoreBusyId(work.id);
    try {
      await api.post(`/v1/works/${work.id}/untrash`);
      notify(t('restoreWorkDone'), 'success');
      trash.refetch();
      router.refresh();
    } catch {
      notify(t('restoreWorkFailed'), 'error');
    } finally {
      setRestoreBusyId(null);
    }
  };

  const deleteDraft = async () => {
    if (!deletingDraft) return;
    setDraftBusy(true);
    setDraftError(null);
    try {
      await api.delete(`/v1/drafts/${deletingDraft.id}`);
      notify(t('deleteDraftDone'), 'success');
      setDeletingDraft(null);
      router.refresh();
    } catch {
      setDraftError(t('deleteDraftFailed'));
    } finally {
      setDraftBusy(false);
    }
  };

  return (
    <div>
      <div
        role="tablist"
        aria-label={t('title')}
        className="flex flex-wrap gap-x-6 gap-y-1 border-b border-border"
      >
        {TABS.map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              '-mb-px border-b-2 pb-3 text-sm',
              controlPress,
              tab === id
                ? 'border-primary text-text'
                : 'border-transparent text-muted hover:text-text',
            )}
          >
            {labels[id]}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {lazyFailed ? (
          <ErrorNotice title={tStates('error')} />
        ) : lazyLoading ? (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-busy="true">
            {Array.from({ length: 4 }, (_, index) => (
              <li key={index}>
                <Skeleton className="aspect-video w-full" />
                <Skeleton className="mt-2 h-4 w-2/3" />
              </li>
            ))}
          </ul>
        ) : tab === 'collections' ? (
          <>
            <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {collectionItems.map((collection) => (
                <li key={collection.id}>
                  <CollectionTile
                    collection={collection}
                    label={t('collectionItems', { count: collection.item_count })}
                    editLabel={t('editCollection')}
                    onEdit={() => setEditingCollection(collection)}
                  />
                </li>
              ))}
              <li>
                <button
                  type="button"
                  onClick={() => setCreateOpen(true)}
                  className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-border text-center transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  <IconPlus className="size-5 text-muted" />
                  <span className="text-sm font-medium">{t('newCollection')}</span>
                </button>
              </li>
            </ul>
            {collectionItems.length === 0 ? (
              <p className="mt-4 text-xs text-muted">{t('emptyCollectionsHint')}</p>
            ) : null}
          </>
        ) : tab === 'skills' ? (
          <>
            <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {skillItems.map((skill) => (
                <SkillCard
                  key={skill.id}
                  skill={skill}
                  locale={locale}
                  showStatus
                  onClick={() => setManagingSkill(skill)}
                />
              ))}
              <li>
                <button
                  type="button"
                  onClick={() => setCreateSkillOpen(true)}
                  className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-border text-center transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  <IconPlus className="size-5 text-muted" />
                  <span className="text-sm font-medium">{t('newSkill')}</span>
                </button>
              </li>
            </ul>
            {skillItems.length === 0 ? (
              <p className="mt-4 text-xs text-muted">{t('emptySkillsHint')}</p>
            ) : null}
          </>
        ) : empty ? (
          <EmptyState
            title={t('empty')}
            description={tab === 'trash' ? t('emptyTrashHint') : t('emptyHint')}
          />
        ) : (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {shownDrafts.map((draft) => (
              <li key={draft.id}>
                <Link href={draftResumeHref(draft)} className="block">
                  <DraftPoster
                    draft={draft}
                    alt={draft.title ?? t('tabDrafts')}
                    className="border border-border"
                  >
                    <span
                      className={cn(
                        'absolute right-2 top-2 rounded-md border px-2 py-0.5 text-[11px]',
                        draft.publish_status === 'pending'
                          ? 'border-amber/40 bg-amber/15 text-amber'
                          : draft.publish_status === 'rejected'
                            ? 'border-danger/40 bg-danger/15 text-danger'
                            : 'border-border bg-surface/90',
                      )}
                    >
                      {draft.publish_status === 'pending'
                        ? t('draftStatusPending')
                        : draft.publish_status === 'rejected'
                          ? t('draftStatusRejected')
                          : tVisibility('draft')}
                    </span>
                    <span className="absolute left-2 top-2">
                      <IconButton
                        label={t('deleteDraft')}
                        variant="secondary"
                        size="sm"
                        className="border-border bg-surface/90"
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setDeletingDraft(draft);
                        }}
                      >
                        <IconTrash className="size-4" />
                      </IconButton>
                    </span>
                  </DraftPoster>
                  <p className="mt-2 truncate text-sm font-medium">
                    {draft.title ?? t('tabDrafts')}
                  </p>
                </Link>
              </li>
            ))}

            {shownTrash.map((work) => (
              <li key={work.id}>
                <WorkCard
                  work={work}
                  badge={{ label: t('tabTrash'), tone: 'neutral' }}
                  actions={
                    <>
                      <IconButton
                        label={t('restoreWork')}
                        variant="secondary"
                        size="sm"
                        className="border-border bg-surface/90"
                        disabled={restoreBusyId === work.id}
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          void restoreWork(work);
                        }}
                      >
                        <IconRefresh className="size-4" />
                      </IconButton>
                      <span aria-hidden className="my-1 w-px self-stretch bg-border" />
                      <IconButton
                        label={t('purgeWork')}
                        variant="danger"
                        size="sm"
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setPurgingWork(work);
                        }}
                      >
                        <IconTrashX className="size-4" />
                      </IconButton>
                    </>
                  }
                />
              </li>
            ))}

            {shownWorks.map((work) => (
              <li key={work.id}>
                <WorkCard
                  work={work}
                  badge={{
                    label: tVisibility(work.visibility),
                    tone: work.visibility.startsWith('public') ? 'success' : 'neutral',
                  }}
                  actions={
                    !canManageWorks ||
                    work.lifecycle_status === 'tombstone' ||
                    work.lifecycle_status === 'trashed' ? null : (
                      <>
                        <IconButton
                          label={t('manageWork')}
                          variant="secondary"
                          size="sm"
                          className="border-border bg-surface/90"
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            setManagingWork(work);
                          }}
                        >
                          <IconPencil className="size-4" />
                        </IconButton>
                        <IconButton
                          label={t('deleteWork')}
                          variant="secondary"
                          size="sm"
                          className="border-border bg-surface/90"
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            setTrashingWork(work);
                          }}
                        >
                          <IconTrash className="size-4" />
                        </IconButton>
                      </>
                    )
                  }
                />
              </li>
            ))}

            {tab === 'all' || tab === 'drafts' ? (
              <li>
                <Link
                  href="/create"
                  className="flex aspect-video flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-border text-center transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  <IconPlus className="size-5 text-muted" />
                  <span className="text-sm font-medium">{t('createNew')}</span>
                  <span className="px-4 text-xs text-muted">{t('createNewHint')}</span>
                </Link>
              </li>
            ) : null}
          </ul>
        )}
      </div>

      <CreateCollectionDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          setCreateOpen(false);
          collections.refetch();
        }}
      />

      <CreateSkillDialog
        open={createSkillOpen}
        onClose={() => setCreateSkillOpen(false)}
        onCreated={() => {
          setCreateSkillOpen(false);
          skills.refetch();
        }}
      />

      {managingSkill ? (
        <ManageSkillDialog
          skill={managingSkill}
          onClose={() => setManagingSkill(null)}
          onChanged={() => {
            setManagingSkill(null);
            skills.refetch();
          }}
        />
      ) : null}

      {managingWork ? (
        <ManageWorkDialog
          work={managingWork}
          open
          onClose={() => setManagingWork(null)}
          onChanged={() => {
            setManagingWork(null);
            router.refresh();
          }}
        />
      ) : null}

      {editingCollection ? (
        <EditCollectionDialog
          collection={editingCollection}
          onClose={() => setEditingCollection(null)}
          onChanged={() => {
            setEditingCollection(null);
            collections.refetch();
          }}
        />
      ) : null}

      <ConfirmDialog
        open={deletingDraft !== null}
        onClose={() => setDeletingDraft(null)}
        title={t('deleteDraftConfirmTitle')}
        confirmLabel={tActions('confirm')}
        cancelLabel={tActions('cancel')}
        busy={draftBusy}
        error={draftError}
        onConfirm={() => void deleteDraft()}
      >
        <p className="text-sm text-muted">{t('deleteDraftConfirmBody')}</p>
      </ConfirmDialog>

      {trashingWork ? (
        <DeleteWorkDialog
          workId={trashingWork.id}
          open
          onClose={() => setTrashingWork(null)}
          onDeleted={() => {
            setTrashingWork(null);
            router.refresh();
          }}
        />
      ) : null}

      {purgingWork ? (
        <PurgeWorkDialog
          workId={purgingWork.id}
          referenced={purgingWork.referenced}
          open
          onClose={() => setPurgingWork(null)}
          onPurged={() => {
            setPurgingWork(null);
            trash.refetch();
            router.refresh();
          }}
        />
      ) : null}
    </div>
  );
}

/**
 * A named collection has no items endpoint, so this is a collage of whatever
 * covers the list response already included — never a link to a detail page
 * that cannot exist yet.
 */
function CollectionTile({
  collection,
  label,
  editLabel,
  onEdit,
}: {
  collection: Collection;
  label: string;
  editLabel: string;
  onEdit: () => void;
}) {
  const covers = collection.cover_urls ?? [];

  return (
    <div className="flex flex-col gap-2.5">
      <div className="relative grid aspect-video grid-cols-2 grid-rows-2 gap-0.5 overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface-soft">
        <span className="absolute right-2 top-2 z-10">
          <IconButton
            label={editLabel}
            variant="secondary"
            size="sm"
            className="border-border bg-surface/90"
            onClick={onEdit}
          >
            <IconPencil className="size-4" />
          </IconButton>
        </span>
        {covers.length > 0 ? (
          covers
            .slice(0, 4)
            .map((url, index) => (
              <Poster
                key={`${collection.id}-${index}`}
                src={url}
                alt={collection.name}
                aspect="fill"
                className="h-full w-full rounded-none border-0"
              />
            ))
        ) : (
          <div className="col-span-2 row-span-2 grid place-items-center text-xs text-muted">
            {collection.name}
          </div>
        )}
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{collection.name}</p>
        <p className="mt-0.5 text-xs text-muted">{label}</p>
      </div>
    </div>
  );
}
