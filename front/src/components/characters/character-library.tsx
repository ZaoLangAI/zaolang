'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { AccessPriceField } from '@/components/marketplace/access-price-field';
import { VideoFirstFrame } from '@/components/media/video-first-frame';
import { Button, IconButton } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import {
  IconClose,
  IconImage,
  IconPencil,
  IconPlus,
  IconShare,
  IconTrash,
  IconUpload,
  IconVideo,
} from '@/components/ui/icons';
import { Badge, type BadgeTone, Card, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Sheet } from '@/components/ui/sheet';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Character, CreationSkillStatus, GenerationJob, Page } from '@/lib/api/types';
import { CHARACTER_COMPLETION_PROMPT, missingReferenceViews, referenceByView } from '@/lib/characters';
import { useMinWidth } from '@/lib/use-media-query';
import { uploadFile } from '@/lib/upload';

/** Terminal `JobStatus` values — anything else means the completion job
 * (see `completeViews` below) is still in flight. */
const TERMINAL_JOB_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'expired']);
const COMPLETION_POLL_INTERVAL_MS = 3000;
const COMPLETION_POLL_MAX_ATTEMPTS = 40;

type ReferenceView = 'front' | 'side' | 'back';
const REFERENCE_VIEWS: ReferenceView[] = ['front', 'side', 'back'];

const VIEW_LABEL_KEY: Record<ReferenceView, 'viewFront' | 'viewSide' | 'viewBack'> = {
  front: 'viewFront',
  side: 'viewSide',
  back: 'viewBack',
};

// Reuses `skillLibrary`'s own status vocabulary rather than duplicating it —
// a character is a `CreationSkillCategory.CHARACTER` skill under the hood
// (see `app.domain.characters.service.CharacterView`), so "draft / pending
// review / published / rejected" means exactly the same thing here.
const STATUS_TONE: Record<CreationSkillStatus, BadgeTone> = {
  draft: 'neutral',
  pending_review: 'amber',
  published: 'success',
  rejected: 'danger',
};

const STATUS_LABEL_KEY: Record<
  CreationSkillStatus,
  'statusDraft' | 'statusPendingReview' | 'statusPublished' | 'statusRejected'
> = {
  draft: 'statusDraft',
  pending_review: 'statusPendingReview',
  published: 'statusPublished',
  rejected: 'statusRejected',
};

/** Only what the form needs to render a thumbnail and send an id back. */
interface ReferenceImage {
  id: string;
  url: string;
}

interface CharacterForm {
  name: string;
  description: string;
  voiceDescription: string;
  references: Record<ReferenceView, ReferenceImage | null>;
}

const EMPTY_FORM: CharacterForm = {
  name: '',
  description: '',
  voiceDescription: '',
  references: { front: null, side: null, back: null },
};

/**
 * Slots a character's reference assets into front/side/back. Characters
 * saved before per-view tagging existed (or edited through the old flow,
 * which reset every asset's view to `general` on save) carry everything as
 * `general` — those are positioned front→side→back in list order as a
 * read-only fallback so old data stays visible instead of appearing empty.
 */
function slotReferences(character: Character): Record<ReferenceView, ReferenceImage | null> {
  const slots: Record<ReferenceView, ReferenceImage | null> = { front: null, side: null, back: null };
  let anyTagged = false;
  for (const view of REFERENCE_VIEWS) {
    const asset = referenceByView(character, view);
    if (asset) {
      slots[view] = { id: asset.asset_id, url: asset.url ?? '' };
      anyTagged = true;
    }
  }
  if (anyTagged) return slots;
  const general = (character.reference_assets ?? []).filter((asset) => asset.view === 'general');
  REFERENCE_VIEWS.forEach((view, index) => {
    const asset = general[index];
    if (asset) slots[view] = { id: asset.asset_id, url: asset.url ?? '' };
  });
  return slots;
}

/** Full-screen preview for a reference thumbnail — closes on backdrop click
 * or Escape; clicking the image itself is a no-op so inspecting it doesn't
 * accidentally dismiss it. Not portalled like `Dialog`: this page has no
 * transformed ancestor that would otherwise clip a `fixed` layer. */
function ReferenceLightbox({ url, onClose }: { url: string | null; onClose: () => void }) {
  useEffect(() => {
    if (!url) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [url, onClose]);

  if (!url) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-6"
      style={{ background: 'var(--overlay)' }}
      onMouseDown={onClose}
    >
      {/* A plain `img` rather than `next/image`: it sizes to its actual
          intrinsic dimensions (unknown here), so the click-to-close backdrop
          only excludes the real pixels of the photo, not a fixed bounding
          box that would swallow clicks on the blank margin around it. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt=""
        onMouseDown={(event) => event.stopPropagation()}
        className="max-h-[85vh] max-w-[90vw] rounded-[var(--radius-md)] object-contain"
      />
    </div>
  );
}

/** Lets the edit form point a reference slot at an asset the user already
 * generated, instead of uploading a new file. There is no general
 * asset-library endpoint, so this reuses the user's own succeeded
 * text-to-image/image-to-image job outputs. */
function ExistingAssetPickerDialog({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (asset: ReferenceImage) => void;
}) {
  const t = useTranslations('characters');
  // Modeled on `use-resource.ts`: "loading" is derived from the absence of a
  // result rather than a `setLoading(true)` at the top of the effect, so the
  // fetch only ever runs once per mount (cached across repeated slot picks)
  // and no setState happens synchronously in the effect body.
  const [result, setResult] = useState<
    { status: 'ready'; assets: ReferenceImage[] } | { status: 'failed' } | null
  >(null);

  useEffect(() => {
    if (!open || result !== null) return;
    let cancelled = false;
    void api
      .get<Page<GenerationJob>>('/v1/generation-jobs?status=succeeded&limit=50')
      .then((page) => {
        if (cancelled) return;
        const items: ReferenceImage[] = [];
        for (const job of page.items) {
          if (job.operation !== 'text_to_image' && job.operation !== 'image_to_image') continue;
          const ids = job.output_asset_ids?.length
            ? job.output_asset_ids
            : job.output_asset_id
              ? [job.output_asset_id]
              : [];
          const urls = job.output_urls?.length
            ? job.output_urls
            : job.output_url
              ? [job.output_url]
              : [];
          ids.forEach((id, index) => {
            const url = urls[index];
            if (url) items.push({ id, url });
          });
        }
        setResult({ status: 'ready', assets: items });
      })
      .catch(() => {
        if (!cancelled) setResult({ status: 'failed' });
      });
    return () => {
      cancelled = true;
    };
  }, [open, result]);

  const loading = open && result === null;
  const error = result?.status === 'failed';
  const assets = result?.status === 'ready' ? result.assets : [];

  return (
    <Dialog open={open} onClose={onClose} title={t('referencePickerTitle')} size="lg">
      {loading ? (
        <div className="flex justify-center py-10">
          <Spinner className="size-5" />
        </div>
      ) : error ? (
        <ErrorNotice title={t('referencePickerError')} />
      ) : assets.length === 0 ? (
        <EmptyState title={t('referencePickerEmpty')} />
      ) : (
        <div className="grid grid-cols-4 gap-2 sm:grid-cols-5">
          {assets.map((asset) => (
            <button
              key={asset.id}
              type="button"
              onClick={() => onSelect(asset)}
              className="relative aspect-square overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft"
            >
              <Image src={asset.url} alt="" fill sizes="120px" className="object-cover" />
            </button>
          ))}
        </div>
      )}
    </Dialog>
  );
}

/**
 * Card list of the creator's reusable cast, with a drawer to create or edit one.
 *
 * A character only stores a text voice hint and up to three reference
 * images (front/side/back) — no sample audio, no face-consistency model —
 * so what is offered here is a profile a future generation call can be
 * pointed at, not a finished likeness.
 */
export function CharacterLibrary({ initial }: { initial: Character[] }) {
  const t = useTranslations('characters');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');
  const { notify } = useToast();

  const [characters, setCharacters] = useState(initial);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Character | null>(null);
  const [form, setForm] = useState<CharacterForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [uploadingView, setUploadingView] = useState<ReferenceView | null>(null);
  const [pickerView, setPickerView] = useState<ReferenceView | null>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Character | null>(null);
  // `Sheet` (bottom drawer) below `lg`, `Dialog` (centred) at/above it — the
  // same breakpoint `generation-studio-shell.tsx` uses to gate its own Sheet
  // to mobile only. Safe pre-hydration: `sheetOpen` only ever flips true from
  // a click, never on mount, so neither container is part of the SSR markup.
  const isDesktop = useMinWidth('lg');

  const tSkills = useTranslations('skillLibrary');
  const [publishTarget, setPublishTarget] = useState<Character | null>(null);
  const [publishAccessCredits, setPublishAccessCredits] = useState(0);
  const [portraitConsent, setPortraitConsent] = useState(false);
  const [publishBusy, setPublishBusy] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null);
  // Keyed by `${character.id}:${view}` rather than just the character id —
  // once completion is per-view (see `completeViews` below), two different
  // cells under the *same* character can each be mid-request, and a cell
  // must only show its own spinner/disable itself for its own request, not
  // whichever one some other cell (or character) happens to be running.
  const [completingKey, setCompletingKey] = useState<string | null>(null);
  const [deletingViewKey, setDeletingViewKey] = useState<string | null>(null);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setSheetOpen(true);
  };

  const openEdit = (character: Character) => {
    setEditing(character);
    setForm({
      name: character.name,
      description: character.description ?? '',
      voiceDescription: character.voice_description ?? '',
      references: slotReferences(character),
    });
    setFormError(null);
    setSheetOpen(true);
  };

  const closeSheet = () => {
    if (saving) return;
    setSheetOpen(false);
  };

  const setSlot = (view: ReferenceView, asset: ReferenceImage | null) => {
    setForm((current) => ({ ...current, references: { ...current.references, [view]: asset } }));
  };

  const uploadToSlot = async (view: ReferenceView, file: File | undefined) => {
    if (!file) return;
    setUploadingView(view);
    try {
      const asset = await uploadFile(file, 'generation_reference');
      setSlot(view, { id: asset.id, url: asset.url ?? '' });
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setUploadingView(null);
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = form.name.trim();
    if (!name) return;

    setSaving(true);
    setFormError(null);
    try {
      const referenceEntries = REFERENCE_VIEWS.map((view) => ({
        view,
        asset: form.references[view],
      })).filter(
        (entry): entry is { view: ReferenceView; asset: ReferenceImage } => entry.asset !== null,
      );
      const payload = {
        name,
        description: form.description.trim() || null,
        reference_asset_ids: referenceEntries.map((entry) => entry.asset.id),
        voice_description: form.voiceDescription.trim() || null,
      };
      let saved = editing
        ? await api.patch<Character>(`/v1/characters/${editing.id}`, payload)
        : await api.post<Character>('/v1/characters', payload);
      // The call above always resets every reference asset's view tag back
      // to `general` server-side (`_entries_from_flat_ids`) — restore each
      // slot's real front/side/back tag through the per-asset endpoint.
      for (const entry of referenceEntries) {
        await api.patch(`/v1/characters/${saved.id}/reference-assets/${entry.asset.id}`, {
          view: entry.view,
        });
      }
      if (referenceEntries.length > 0) {
        saved = await api.get<Character>(`/v1/characters/${saved.id}`);
      }
      setCharacters((current) =>
        editing
          ? current.map((item) => (item.id === saved.id ? saved : item))
          : [saved, ...current],
      );
      setSheetOpen(false);
    } catch (caught) {
      setFormError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
    } finally {
      setSaving(false);
    }
  };

  const openDeleteConfirm = (character: Character) => {
    setDeleteTarget(character);
  };

  const closeDeleteConfirm = () => {
    if (deletingId) return;
    setDeleteTarget(null);
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setDeletingId(deleteTarget.id);
    try {
      await api.delete(`/v1/characters/${deleteTarget.id}`);
      setCharacters((current) => current.filter((item) => item.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const openPublish = (character: Character) => {
    setPublishTarget(character);
    setPublishAccessCredits(character.access_credits);
    setPortraitConsent(false);
    setPublishError(null);
  };

  const closePublish = () => {
    if (publishBusy) return;
    setPublishTarget(null);
  };

  // Requires a fresh, explicit consent flag on every publish — sharing (and
  // potentially selling, via `access_credits`) a character is publishing a
  // depicted persona, so it cannot inherit whatever consent covered the
  // original generation request (see `characters.service.publish_character`).
  const publish = async () => {
    if (!publishTarget || !portraitConsent) return;
    setPublishBusy(true);
    setPublishError(null);
    try {
      if (publishAccessCredits !== publishTarget.access_credits) {
        await api.patch(`/v1/skills/${publishTarget.id}/pricing`, {
          access_credits: publishAccessCredits,
        });
      }
      const saved = await api.post<Character>(`/v1/characters/${publishTarget.id}/publish`, {
        portrait_consent: true,
      });
      setCharacters((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      notify(tSkills('publishDone'), 'success');
      setPublishTarget(null);
    } catch (caught) {
      setPublishError(caught instanceof ApiError ? caught.message : tSkills('saveFailed'));
    } finally {
      setPublishBusy(false);
    }
  };

  const withdraw = async (character: Character) => {
    setWithdrawingId(character.id);
    try {
      const saved = await api.post<Character>(`/v1/characters/${character.id}/withdraw`);
      setCharacters((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      notify(tSkills('withdrawDone'), 'success');
    } catch {
      notify(tSkills('saveFailed'), 'error');
    } finally {
      setWithdrawingId(null);
    }
  };

  const pollCompletionJob = async (jobId: string): Promise<GenerationJob> => {
    for (let attempt = 0; attempt < COMPLETION_POLL_MAX_ATTEMPTS; attempt += 1) {
      const job = await api.get<GenerationJob>(`/v1/generation-jobs/${jobId}`);
      if (TERMINAL_JOB_STATUSES.has(job.status)) return job;
      await new Promise((resolve) => setTimeout(resolve, COMPLETION_POLL_INTERVAL_MS));
    }
    throw new Error('generation job polling timed out');
  };

  // Borrows the front reference and asks the shared image-asset graph for
  // whichever of `views` is passed (usually just the one cell that was
  // clicked, sometimes both at once — see call sites below) in one job
  // (`character_views: views`) — `execute_asset_output_advance` loops once
  // per entry, `execute_asset_output_link` attaches every output back to
  // this same character (see `zaolang-generation-jobs` invariant on
  // multi-output character jobs). The prompt is a fixed reference-only
  // instruction, never the character's own description/name — the backend
  // (`execute_asset_planning`) hard-overrides it for a side/back pass
  // regardless, but sending it here too keeps the request's own intent
  // self-explanatory rather than silently relying on that override.
  const completeViews = async (character: Character, views: Array<'side' | 'back'>) => {
    const front = referenceByView(character, 'front');
    if (!front || views.length === 0) {
      notify(t('completeViewsNeedsFront'), 'error');
      return;
    }
    const key = `${character.id}:${views.join(',')}`;
    setCompletingKey(key);
    try {
      const job = await api.post<GenerationJob>(
        '/v1/generation-jobs',
        {
          operation: 'image_to_image',
          quality_tier: 'standard',
          params: {
            prompt: CHARACTER_COMPLETION_PROMPT,
            aspect_ratio: '3:4',
            reference_asset_ids: [front.asset_id],
            asset_kind: 'character',
            character_views: views,
            target_character_id: character.id,
            auto_attach_asset: true,
          },
        },
        { idempotencyKey: newIdempotencyKey() },
      );
      const finished = await pollCompletionJob(job.id);
      if (finished.status !== 'succeeded') {
        notifyViewCompletion(views, false);
        return;
      }
      const refreshed = await api.get<Character>(`/v1/characters/${character.id}`);
      setCharacters((current) =>
        current.map((item) => (item.id === refreshed.id ? refreshed : item)),
      );
      notifyViewCompletion(views, true);
    } catch {
      notifyViewCompletion(views, false);
    } finally {
      setCompletingKey(null);
    }
  };

  // A single view names it specifically ("补全侧面"/"补全背面"); both at
  // once (the studio's inline result offers this shape, not this page —
  // see `ImageGenerationStudio`'s `completeCharacterViews`) falls back to
  // the older, generic "补全侧面/背面" copy.
  const notifyViewCompletion = (views: Array<'side' | 'back'>, success: boolean) => {
    const [singleView] = views;
    if (views.length === 1 && singleView) {
      const view = t(VIEW_LABEL_KEY[singleView]);
      notify(success ? t('completeViewDone', { view }) : t('completeViewFailed', { view }), success ? 'success' : 'error');
      return;
    }
    notify(success ? t('completeViewsDone') : t('completeViewsFailed'), success ? 'success' : 'error');
  };

  // Deletes just one side/back reference — the view's grid cell goes back
  // to a completable, empty slot immediately after (derived from
  // `missingReferenceViews` once `characters` reflects the response), no
  // separate "completed" flag to reset.
  const deleteReferenceView = async (character: Character, view: 'side' | 'back', assetId: string) => {
    const key = `${character.id}:${view}`;
    setDeletingViewKey(key);
    try {
      const updated = await api.delete<Character>(
        `/v1/characters/${character.id}/reference-assets/${assetId}`,
      );
      setCharacters((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setDeletingViewKey(null);
    }
  };

  // Shared between the `Dialog` (desktop) and `Sheet` (mobile) containers
  // below — the two differ only in how they present the same form.
  const characterForm = (
    <form
      id="character-form"
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-4"
    >
      <TextInput
        label={t('nameLabel')}
        value={form.name}
        maxLength={120}
        required
        onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
      />
      <TextArea
        label={t('descriptionLabel')}
        value={form.description}
        maxLength={2000}
        onChange={(event) =>
          setForm((current) => ({ ...current, description: event.target.value }))
        }
      />
      <TextArea
        label={t('voiceLabel')}
        hint={t('voiceHint')}
        value={form.voiceDescription}
        maxLength={500}
        onChange={(event) =>
          setForm((current) => ({ ...current, voiceDescription: event.target.value }))
        }
      />
      <div>
        <p className="text-sm font-medium text-text">{t('referenceLabel')}</p>
        <p className="mt-1 text-xs text-muted">{t('referenceHint')}</p>
        <div className="mt-2 grid grid-cols-3 gap-3">
          {REFERENCE_VIEWS.map((view) => {
            const asset = form.references[view];
            return (
              <div key={view} className="flex flex-col gap-1.5">
                <span className="text-xs text-muted">{t(VIEW_LABEL_KEY[view])}</span>
                {asset ? (
                  <div className="relative aspect-square overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                    <button
                      type="button"
                      onClick={() => setLightboxUrl(asset.url)}
                      className="absolute inset-0"
                    >
                      <Image src={asset.url} alt="" fill sizes="120px" className="object-cover" />
                    </button>
                    <button
                      type="button"
                      aria-label={tActions('delete')}
                      onClick={() => setSlot(view, null)}
                      className="absolute right-1 top-1 grid size-5 place-items-center rounded-full bg-surface-raised/90 text-muted hover:text-text"
                    >
                      <IconClose className="size-3" />
                    </button>
                  </div>
                ) : (
                  <div className="flex aspect-square flex-col overflow-hidden rounded-[var(--radius-sm)] border border-dashed border-border">
                    <label className="flex flex-1 cursor-pointer flex-col items-center justify-center gap-1 border-b border-dashed border-border text-muted transition-colors hover:border-border-strong hover:text-text">
                      {uploadingView === view ? (
                        <Spinner className="size-4" />
                      ) : (
                        <>
                          <IconUpload className="size-4" />
                          <span className="text-[10px]">{t('referenceUpload')}</span>
                        </>
                      )}
                      <input
                        type="file"
                        accept="image/*"
                        className="sr-only"
                        onChange={(event) => void uploadToSlot(view, event.target.files?.[0])}
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => setPickerView(view)}
                      className="flex flex-1 flex-col items-center justify-center gap-1 text-muted transition-colors hover:text-text"
                    >
                      <IconImage className="size-4" />
                      <span className="text-[10px]">{t('referenceChooseExisting')}</span>
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </form>
  );

  const formFooter = (
    <div className="flex w-full justify-end gap-3">
      <Button variant="ghost" onClick={closeSheet} disabled={saving}>
        {tActions('cancel')}
      </Button>
      <Button type="submit" form="character-form" loading={saving} className="w-28">
        {tActions('save')}
      </Button>
    </div>
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex justify-end">
        <Button onClick={openCreate} icon={<IconPlus className="size-4" />}>
          {t('newCharacter')}
        </Button>
      </div>

      {characters.length === 0 ? (
        <EmptyState
          title={t('emptyTitle')}
          description={t('emptyHint')}
          action={<Button onClick={openCreate}>{t('newCharacter')}</Button>}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {characters.map((character) => {
            const references = slotReferences(character);
            return (
              <li key={character.id}>
                <Card className="flex h-full flex-col gap-3 p-4">
                  <h3 className="truncate text-sm font-semibold">{character.name}</h3>
                  <div className="grid grid-cols-3 gap-2">
                    {REFERENCE_VIEWS.map((view) => {
                      const asset = references[view];
                      const canDeleteView = Boolean(asset) && view !== 'front';
                      const canComplete =
                        !asset &&
                        view !== 'front' &&
                        missingReferenceViews(character).includes(view as 'side' | 'back');
                      const viewKey = `${character.id}:${view}`;
                      const isCompletingThis = completingKey === viewKey;
                      const isDeletingThis = deletingViewKey === viewKey;
                      const busyElsewhere =
                        (completingKey !== null && completingKey !== viewKey) ||
                        (deletingViewKey !== null && deletingViewKey !== viewKey);
                      return (
                        <div
                          key={view}
                          className="relative aspect-square overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft"
                        >
                          {asset ? (
                            <>
                              <button
                                type="button"
                                onClick={() => setLightboxUrl(asset.url)}
                                className="absolute inset-0"
                              >
                                <Image
                                  src={asset.url}
                                  alt=""
                                  fill
                                  sizes="120px"
                                  className="object-cover"
                                />
                              </button>
                              {canDeleteView ? (
                                <button
                                  type="button"
                                  aria-label={t('deleteViewLabel', { view: t(VIEW_LABEL_KEY[view]) })}
                                  disabled={busyElsewhere}
                                  onClick={() =>
                                    void deleteReferenceView(character, view as 'side' | 'back', asset.id)
                                  }
                                  className="absolute right-1 top-1 grid size-5 place-items-center rounded-full bg-surface-raised/90 text-muted transition-colors hover:text-text disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  {isDeletingThis ? (
                                    <Spinner className="size-3" />
                                  ) : (
                                    <IconClose className="size-3" />
                                  )}
                                </button>
                              ) : null}
                            </>
                          ) : canComplete ? (
                            <button
                              type="button"
                              disabled={busyElsewhere}
                              onClick={() => void completeViews(character, [view as 'side' | 'back'])}
                              className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-muted transition-colors hover:text-text disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {isCompletingThis ? (
                                <Spinner className="size-4" />
                              ) : (
                                <IconPlus className="size-4" />
                              )}
                              <span className="text-[10px]">
                                {isCompletingThis
                                  ? t('completingViewButton', { view: t(VIEW_LABEL_KEY[view]) })
                                  : t('completeViewButton', { view: t(VIEW_LABEL_KEY[view]) })}
                              </span>
                            </button>
                          ) : (
                            <div className="absolute inset-0 grid place-items-center px-1 text-center text-[10px] text-muted">
                              {t('noReference')}
                            </div>
                          )}
                          <span className="pointer-events-none absolute bottom-0.5 right-0.5 rounded bg-black/60 px-1 text-[9px] leading-tight text-white">
                            {t(VIEW_LABEL_KEY[view])}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  {character.status !== 'draft' || character.access_credits > 0 ? (
                    <div className="flex items-center gap-1.5">
                      {character.status !== 'draft' ? (
                        <Badge tone={STATUS_TONE[character.status]}>
                          {tSkills(STATUS_LABEL_KEY[character.status])}
                        </Badge>
                      ) : null}
                      {character.access_credits > 0 ? (
                        <Badge tone="primary">
                          {tSkills('priceCredits', { credits: character.access_credits })}
                        </Badge>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="min-w-0 flex-1">
                    {character.description ? (
                      <p className="line-clamp-2 text-xs text-muted">{character.description}</p>
                    ) : null}
                    {character.voice_description ? (
                      <p className="mt-1 line-clamp-1 text-[11px] text-muted">
                        {t('voiceLabel')}: {character.voice_description}
                      </p>
                    ) : null}
                    {character.action_clips && character.action_clips.length > 0 ? (
                      <div className="mt-2">
                        <p className="text-[11px] text-muted">{t('actionClipsLabel')}</p>
                        <div className="mt-1 flex gap-2 overflow-x-auto">
                          {character.action_clips.map((clip) => (
                            <a
                              key={clip.asset_id}
                              href={clip.url ?? undefined}
                              target="_blank"
                              rel="noreferrer"
                              className="relative size-14 shrink-0 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft"
                            >
                              {clip.url ? <VideoFirstFrame src={clip.url} /> : null}
                              <span className="absolute inset-0 grid place-items-center bg-black/20">
                                <IconVideo className="size-4 text-white" />
                              </span>
                            </a>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                  <div className="mt-auto flex items-center justify-center gap-6 border-t border-border pt-3">
                    <IconButton
                      size="sm"
                      label={tActions('edit')}
                      onClick={() => openEdit(character)}
                    >
                      <IconPencil className="size-4" />
                    </IconButton>
                    {character.status === 'draft' || character.status === 'rejected' ? (
                      <IconButton
                        size="sm"
                        label={t('publishCharacter')}
                        onClick={() => openPublish(character)}
                      >
                        <IconShare className="size-4" />
                      </IconButton>
                    ) : (
                      <IconButton
                        size="sm"
                        label={tSkills('withdraw')}
                        loading={withdrawingId === character.id}
                        onClick={() => void withdraw(character)}
                      >
                        <IconShare className="size-4" />
                      </IconButton>
                    )}
                    <IconButton
                      variant="danger"
                      size="sm"
                      label={tActions('delete')}
                      loading={deletingId === character.id}
                      onClick={() => openDeleteConfirm(character)}
                    >
                      <IconTrash className="size-4" />
                    </IconButton>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      {isDesktop ? (
        <Dialog
          open={sheetOpen}
          onClose={closeSheet}
          title={editing ? t('editCharacter') : t('newCharacter')}
          size="lg"
          footer={formFooter}
        >
          <div className="flex flex-col gap-4">
            {formError ? <ErrorNotice title={formError} /> : null}
            {characterForm}
          </div>
        </Dialog>
      ) : (
        <Sheet
          open={sheetOpen}
          onClose={closeSheet}
          title={editing ? t('editCharacter') : t('newCharacter')}
          loading={saving}
          error={formError}
          footer={formFooter}
        >
          {characterForm}
        </Sheet>
      )}

      <ExistingAssetPickerDialog
        open={pickerView !== null}
        onClose={() => setPickerView(null)}
        onSelect={(asset) => {
          if (pickerView) setSlot(pickerView, asset);
          setPickerView(null);
        }}
      />

      <ReferenceLightbox url={lightboxUrl} onClose={() => setLightboxUrl(null)} />

      <Dialog
        open={deleteTarget !== null}
        onClose={closeDeleteConfirm}
        title={t('deleteConfirmTitle')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={closeDeleteConfirm} disabled={deletingId !== null}>
              {tActions('cancel')}
            </Button>
            <Button variant="danger" loading={deletingId !== null} onClick={() => void remove()}>
              {tActions('confirm')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">
          {deleteTarget ? t('deleteConfirmBody', { name: deleteTarget.name }) : null}
        </p>
      </Dialog>

      <Dialog
        open={publishTarget !== null}
        onClose={closePublish}
        title={t('publishCharacter')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={closePublish} disabled={publishBusy}>
              {tActions('cancel')}
            </Button>
            <Button
              loading={publishBusy}
              disabled={!portraitConsent}
              onClick={() => void publish()}
            >
              {tSkills('publish')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted">{t('publishCharacterHint')}</p>
          <AccessPriceField
            value={publishAccessCredits}
            onChange={setPublishAccessCredits}
            label={t('priceLabel')}
            hint={t('priceHint')}
          />
          <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
            <input
              type="checkbox"
              checked={portraitConsent}
              onChange={(event) => setPortraitConsent(event.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
            />
            {t('portraitConsentLabel')}
          </label>
          {publishError ? <ErrorNotice title={publishError} /> : null}
        </div>
      </Dialog>
    </div>
  );
}
