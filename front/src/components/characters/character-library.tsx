'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { AccessPriceField } from '@/components/marketplace/access-price-field';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import { IconClose, IconPlus, IconUpload } from '@/components/ui/icons';
import { Badge, type BadgeTone, Card, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Sheet } from '@/components/ui/sheet';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Character, CreationSkillStatus, GenerationJob } from '@/lib/api/types';
import { uploadFile } from '@/lib/upload';

const MAX_REFERENCE_ASSETS = 4;

/** Terminal `JobStatus` values — anything else means the completion job
 * (see `completeViews` below) is still in flight. */
const TERMINAL_JOB_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'expired']);
const COMPLETION_POLL_INTERVAL_MS = 3000;
const COMPLETION_POLL_MAX_ATTEMPTS = 40;

const VIEW_LABEL_KEY: Record<string, 'viewFront' | 'viewSide' | 'viewBack'> = {
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
  referenceAssets: ReferenceImage[];
  accessCredits: number;
}

const EMPTY_FORM: CharacterForm = {
  name: '',
  description: '',
  voiceDescription: '',
  referenceAssets: [],
  accessCredits: 0,
};

/**
 * Card list of the creator's reusable cast, with a drawer to create or edit one.
 *
 * A character only stores a text voice hint and up to four reference images —
 * no sample audio, no face-consistency model — so what is offered here is a
 * profile a future generation call can be pointed at, not a finished likeness.
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
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const tSkills = useTranslations('skillLibrary');
  const [publishTarget, setPublishTarget] = useState<Character | null>(null);
  const [portraitConsent, setPortraitConsent] = useState(false);
  const [publishBusy, setPublishBusy] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null);
  const [completingId, setCompletingId] = useState<string | null>(null);

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
      referenceAssets: (character.reference_assets ?? []).map((asset) => ({
        id: asset.asset_id,
        url: asset.url ?? '',
      })),
      accessCredits: character.access_credits,
    });
    setFormError(null);
    setSheetOpen(true);
  };

  const closeSheet = () => {
    if (saving) return;
    setSheetOpen(false);
  };

  const pickReferenceImage = async (file: File | undefined) => {
    if (!file || form.referenceAssets.length >= MAX_REFERENCE_ASSETS) return;
    setUploading(true);
    try {
      const asset = await uploadFile(file, 'generation_reference');
      setForm((current) => ({
        ...current,
        referenceAssets: [...current.referenceAssets, { id: asset.id, url: asset.url ?? '' }],
      }));
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setUploading(false);
    }
  };

  const removeReferenceImage = (assetId: string) => {
    setForm((current) => ({
      ...current,
      referenceAssets: current.referenceAssets.filter((asset) => asset.id !== assetId),
    }));
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = form.name.trim();
    if (!name) return;

    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        name,
        description: form.description.trim() || null,
        reference_asset_ids: form.referenceAssets.map((asset) => asset.id),
        voice_description: form.voiceDescription.trim() || null,
      };
      let saved = editing
        ? await api.patch<Character>(`/v1/characters/${editing.id}`, payload)
        : await api.post<Character>('/v1/characters', payload);
      // Pricing goes through the generic skill endpoint (a character is a
      // `CreationSkill` under the hood and shares its id), which responds
      // with a `CreationSkillDetail`, not a `CharacterResponse` — refetch
      // the character shape rather than trust that response. Only called
      // when the price actually changed, since `update_pricing` never
      // unpublishes (unlike the content patch above) and a plain content
      // edit shouldn't touch it.
      if (form.accessCredits !== (editing?.access_credits ?? 0)) {
        await api.patch(`/v1/skills/${saved.id}/pricing`, {
          access_credits: form.accessCredits,
        });
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

  const remove = async (character: Character) => {
    setDeletingId(character.id);
    try {
      await api.delete(`/v1/characters/${character.id}`);
      setCharacters((current) => current.filter((item) => item.id !== character.id));
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const openPublish = (character: Character) => {
    setPublishTarget(character);
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

  const referenceByView = (character: Character, view: 'front' | 'side' | 'back') =>
    character.reference_assets?.find((asset) => asset.view === view);

  // Step two of the guided flow (`ImageGenerationStudio`'s "角色图" option only
  // ever produces the front view — see its `assetKindCharacterHint`): shown
  // once a front reference exists and either the side or back is still
  // missing, and always asks for both regardless of which one is missing.
  const canCompleteViews = (character: Character) =>
    Boolean(referenceByView(character, 'front')) &&
    (!referenceByView(character, 'side') || !referenceByView(character, 'back'));

  const pollCompletionJob = async (jobId: string): Promise<GenerationJob> => {
    for (let attempt = 0; attempt < COMPLETION_POLL_MAX_ATTEMPTS; attempt += 1) {
      const job = await api.get<GenerationJob>(`/v1/generation-jobs/${jobId}`);
      if (TERMINAL_JOB_STATUSES.has(job.status)) return job;
      await new Promise((resolve) => setTimeout(resolve, COMPLETION_POLL_INTERVAL_MS));
    }
    throw new Error('generation job polling timed out');
  };

  // Borrows the front reference and asks the shared image-asset graph for
  // both remaining views in one job (`character_views: ['side', 'back']`) —
  // `execute_asset_output_advance` loops it twice, `execute_asset_output_link`
  // attaches both outputs back to this same character (see `zaolang-
  // generation-jobs` invariant on multi-output character jobs).
  const completeViews = async (character: Character) => {
    const front = referenceByView(character, 'front');
    if (!front) {
      notify(t('completeViewsNeedsFront'), 'error');
      return;
    }
    setCompletingId(character.id);
    try {
      const job = await api.post<GenerationJob>(
        '/v1/generation-jobs',
        {
          operation: 'image_to_image',
          quality_tier: 'standard',
          params: {
            prompt: character.description?.trim() || character.name,
            aspect_ratio: '3:4',
            reference_asset_ids: [front.asset_id],
            asset_kind: 'character',
            character_views: ['side', 'back'],
            target_character_id: character.id,
            auto_attach_asset: true,
          },
        },
        { idempotencyKey: newIdempotencyKey() },
      );
      const finished = await pollCompletionJob(job.id);
      if (finished.status !== 'succeeded') {
        notify(t('completeViewsFailed'), 'error');
        return;
      }
      const refreshed = await api.get<Character>(`/v1/characters/${character.id}`);
      setCharacters((current) =>
        current.map((item) => (item.id === refreshed.id ? refreshed : item)),
      );
      notify(t('completeViewsDone'), 'success');
    } catch {
      notify(t('completeViewsFailed'), 'error');
    } finally {
      setCompletingId(null);
    }
  };

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
          {characters.map((character) => (
            <li key={character.id}>
              <Card className="flex h-full flex-col gap-3 p-4">
                <div className="flex gap-2 overflow-x-auto">
                  {character.reference_assets && character.reference_assets.length > 0 ? (
                    character.reference_assets.map((asset) => (
                      <div
                        key={asset.asset_id}
                        className="relative size-16 shrink-0 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft"
                      >
                        {asset.url ? (
                          <Image
                            src={asset.url}
                            alt=""
                            fill
                            sizes="64px"
                            className="object-cover"
                          />
                        ) : null}
                        {(() => {
                          const labelKey = VIEW_LABEL_KEY[asset.view];
                          return labelKey ? (
                            <span className="absolute bottom-0.5 right-0.5 rounded bg-black/60 px-1 text-[9px] leading-tight text-white">
                              {t(labelKey)}
                            </span>
                          ) : null;
                        })()}
                      </div>
                    ))
                  ) : (
                    <div className="grid size-16 shrink-0 place-items-center rounded-[var(--radius-sm)] bg-surface-soft text-[10px] text-muted">
                      {t('noReference')}
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <Badge tone={STATUS_TONE[character.status]}>
                      {tSkills(STATUS_LABEL_KEY[character.status])}
                    </Badge>
                    {character.access_credits > 0 ? (
                      <Badge tone="primary">
                        {tSkills('priceCredits', { credits: character.access_credits })}
                      </Badge>
                    ) : null}
                  </div>
                  <h3 className="mt-1.5 truncate text-sm font-semibold">{character.name}</h3>
                  {character.description ? (
                    <p className="mt-1 line-clamp-2 text-xs text-muted">{character.description}</p>
                  ) : null}
                  {character.voice_description ? (
                    <p className="mt-1 line-clamp-1 text-[11px] text-muted">
                      {t('voiceLabel')}: {character.voice_description}
                    </p>
                  ) : null}
                </div>
                <div className="mt-auto flex flex-wrap gap-2">
                  <Button size="sm" variant="secondary" onClick={() => openEdit(character)}>
                    {tActions('edit')}
                  </Button>
                  {canCompleteViews(character) ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={completingId === character.id}
                      disabled={completingId !== null && completingId !== character.id}
                      onClick={() => void completeViews(character)}
                    >
                      {completingId === character.id
                        ? t('completingViews')
                        : t('completeViews')}
                    </Button>
                  ) : null}
                  {character.status === 'draft' || character.status === 'rejected' ? (
                    <Button size="sm" variant="ghost" onClick={() => openPublish(character)}>
                      {t('publishCharacter')}
                    </Button>
                  ) : null}
                  {character.status === 'pending_review' || character.status === 'published' ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={withdrawingId === character.id}
                      onClick={() => void withdraw(character)}
                    >
                      {tSkills('withdraw')}
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={deletingId === character.id}
                    onClick={() => void remove(character)}
                  >
                    {tActions('delete')}
                  </Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}

      <Sheet
        open={sheetOpen}
        onClose={closeSheet}
        title={editing ? t('editCharacter') : t('newCharacter')}
        loading={saving}
        error={formError}
        footer={
          <>
            <Button variant="ghost" onClick={closeSheet} disabled={saving}>
              {tActions('cancel')}
            </Button>
            <Button type="submit" form="character-form" loading={saving} fullWidth>
              {tActions('save')}
            </Button>
          </>
        }
      >
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
            <div className="mt-2 flex flex-wrap gap-2">
              {form.referenceAssets.map((asset) => (
                <div key={asset.id} className="relative size-20">
                  <Image
                    src={asset.url}
                    alt=""
                    fill
                    sizes="80px"
                    className="rounded-[var(--radius-sm)] object-cover"
                  />
                  <button
                    type="button"
                    aria-label={tActions('delete')}
                    onClick={() => removeReferenceImage(asset.id)}
                    className="absolute right-1 top-1 grid size-5 place-items-center rounded-full bg-surface-raised/90 text-muted hover:text-text"
                  >
                    <IconClose className="size-3" />
                  </button>
                </div>
              ))}
              {form.referenceAssets.length < MAX_REFERENCE_ASSETS ? (
                <label className="grid size-20 cursor-pointer place-items-center rounded-[var(--radius-sm)] border border-dashed border-border text-muted transition-colors hover:border-border-strong hover:text-text">
                  {uploading ? <Spinner className="size-4" /> : <IconUpload className="size-4" />}
                  <input
                    type="file"
                    accept="image/*"
                    className="sr-only"
                    onChange={(event) => void pickReferenceImage(event.target.files?.[0])}
                  />
                </label>
              ) : null}
            </div>
          </div>
          <AccessPriceField
            value={form.accessCredits}
            onChange={(value) => setForm((current) => ({ ...current, accessCredits: value }))}
            label={t('priceLabel')}
            hint={t('priceHint')}
          />
        </form>
      </Sheet>

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
