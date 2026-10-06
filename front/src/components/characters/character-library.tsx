'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { CharacterDescribeDialog } from '@/components/characters/character-describe-dialog';
import { AccessPriceField } from '@/components/marketplace/access-price-field';
import { VideoFirstFrame } from '@/components/media/video-first-frame';
import { Button, IconButton } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import {
  IconGrid,
  IconPencil,
  IconPlus,
  IconShare,
  IconSparkle,
  IconTrash,
  IconVideo,
} from '@/components/ui/icons';
import { MediaLightbox } from '@/components/ui/media-lightbox';
import { Badge, Card, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Sheet } from '@/components/ui/sheet';
import { useToast } from '@/components/ui/toast';
import { useRouter } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Character, CharacterScriptLink } from '@/lib/api/types';
import { cardCompleteness } from '@/features/asset-workspace/completeness';
import { seedCardImage, workspaceHref } from '@/features/asset-workspace/new-card';
import { characterHeroUrl, characterManageHref } from '@/lib/characters';
import {
  CREATION_SKILL_STATUS_LABEL_KEY,
  CREATION_SKILL_STATUS_TONE,
} from '@/lib/creation-skill-status';
import { useMinWidth } from '@/lib/use-media-query';

// Status badges reuse `CREATION_SKILL_STATUS_*` — a character is a
// `CreationSkillCategory.CHARACTER` skill under the hood.

interface CharacterForm {
  name: string;
  description: string;
  voiceDescription: string;
}

const EMPTY_FORM: CharacterForm = {
  name: '',
  description: '',
  voiceDescription: '',
};

/**
 * Card list of the creator's reusable cast, with a dialog to create or edit
 * one's text profile (name, description, voice description).
 *
 * Images are managed on the card's own page (`/create/characters/[id]`):
 * the form never sends `reference_asset_ids`, which on the backend is a
 * flat replace (`asset_variants.service.set_members`) that would drop every
 * approved image the form did not list.
 */
export function CharacterLibrary({ initial }: { initial: Character[] }) {
  const t = useTranslations('characters');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');
  const tMedia = useTranslations('media');
  const tWorkspace = useTranslations('assetWorkspace');
  const { notify } = useToast();
  const router = useRouter();

  const [characters, setCharacters] = useState(initial);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Character | null>(null);
  const [form, setForm] = useState<CharacterForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  // Scripts linking the card being edited — 「AI 生成」 shows only when one does.
  const [scriptLinks, setScriptLinks] = useState<CharacterScriptLink[]>([]);
  const [describeOpen, setDescribeOpen] = useState(false);
  const linksFor = useRef<string | null>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  // 从图片新建: an optional first image (filed as the identity portrait).
  const [startImage, setStartImage] = useState<File | null>(null);
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

  const openCreate = () => {
    setStartImage(null);
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setNameError(null);
    setSheetOpen(true);
  };

  const openEdit = (character: Character) => {
    setEditing(character);
    setForm({
      name: character.name,
      description: character.description ?? '',
      voiceDescription: character.voice_description ?? '',
    });
    setFormError(null);
    setNameError(null);
    setScriptLinks([]);
    setSheetOpen(true);
    // Only the card still being edited may set the links (a fast reopen
    // on another card must not show the first card's scripts).
    linksFor.current = character.id;
    api
      .get<CharacterScriptLink[]>(`/v1/characters/${character.id}/script-links`)
      .then((rows) => {
        if (linksFor.current === character.id) setScriptLinks(rows);
      })
      .catch(() => undefined);
  };

  const closeSheet = () => {
    if (saving) return;
    setSheetOpen(false);
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = form.name.trim();
    if (!name) return;
    const duplicate = characters.some(
      (item) => item.id !== editing?.id && item.name.trim() === name,
    );
    if (duplicate) {
      setNameError(t('nameTaken'));
      setFormError(t('nameTaken'));
      return;
    }

    setSaving(true);
    setFormError(null);
    setNameError(null);
    try {
      const payload = {
        name,
        description: form.description.trim() || null,
        voice_description: form.voiceDescription.trim() || null,
      };
      const saved = editing
        ? await api.patch<Character>(`/v1/characters/${editing.id}`, payload)
        : await api.post<Character>('/v1/characters', payload);
      setCharacters((current) =>
        editing
          ? current.map((item) => (item.id === saved.id ? saved : item))
          : [saved, ...current],
      );
      setSheetOpen(false);
      // A new card opens on its 创作 board: from an uploaded image the
      // portrait is filed and the sheet is next, else the portrait is.
      if (!editing) {
        let slot = 'portrait';
        if (startImage) {
          try {
            slot = await seedCardImage('character', saved.id, saved.looks ?? [], startImage);
          } catch {
            notify(t('startImageFailed'), 'error');
          }
        }
        router.push(workspaceHref(characterManageHref(saved.id), slot));
      }
    } catch (caught) {
      if (caught instanceof ApiError) {
        const taken = Boolean(caught.fieldErrors.name);
        setNameError(taken ? t('nameTaken') : (caught.fieldErrors.name ?? null));
        setFormError(taken ? t('nameTaken') : caught.message);
      } else {
        setFormError(tStates('errorHint'));
      }
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

  const characterForm = (
    <form
      id="character-form"
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-4"
    >
      <TextInput
        label={t('nameLabel')}
        value={form.name}
        maxLength={80}
        required
        error={nameError ?? undefined}
        onChange={(event) => {
          setNameError(null);
          setForm((current) => ({ ...current, name: event.target.value }));
        }}
      />
      {editing && scriptLinks.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-dashed border-border p-3">
          <p className="text-xs text-muted">{t('describeLinked', { count: scriptLinks.length })}</p>
          <Button
            size="sm"
            variant="secondary"
            icon={<IconSparkle className="size-3.5" />}
            onClick={() => setDescribeOpen(true)}
          >
            {t('describeOpen')}
          </Button>
        </div>
      ) : null}
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
      {!editing ? (
        <label className="flex flex-col gap-1 text-sm">
          <span>{t('startImageLabel')}</span>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => setStartImage(event.target.files?.[0] ?? null)}
            className="text-xs text-muted file:mr-3 file:rounded-[var(--radius-sm)] file:border file:border-border file:bg-surface-soft file:px-3 file:py-1.5 file:text-text"
          />
          <span className="text-xs text-muted">{t('startImageHint')}</span>
        </label>
      ) : null}
    </form>
  );

  const formFooter = (
    <div className="flex w-full flex-wrap justify-end gap-3">
      <Button variant="ghost" onClick={closeSheet} disabled={saving}>
        {tActions('cancel')}
      </Button>
      <Button
        type="submit"
        form="character-form"
        loading={saving}
        disabled={saving}
        className="w-28"
      >
        {editing ? tActions('save') : t('saveAndManage')}
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
            const hero = characterHeroUrl(character);
            return (
              <li key={character.id}>
                <Card className="flex h-full flex-col gap-3 p-4">
                  <h3 className="truncate text-sm font-semibold">{character.name}</h3>
                  <div className="relative aspect-video overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                    {hero ? (
                      <button
                        type="button"
                        aria-label={tMedia('lightboxTitle')}
                        onClick={() => setLightboxUrl(hero)}
                        className="absolute inset-0"
                      >
                        <Image src={hero} alt="" fill sizes="360px" className="object-contain" />
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => router.push(characterManageHref(character.id))}
                        className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-muted transition-colors hover:text-text"
                      >
                        <IconSparkle className="size-4" />
                        <span className="text-[10px]">{t('startLooks')}</span>
                      </button>
                    )}
                  </div>
                  {(() => {
                    const score = cardCompleteness('character', character.looks ?? []);
                    return score ? (
                      <Badge
                        tone={score.done === score.total ? 'success' : 'neutral'}
                        className="self-start"
                      >
                        {tWorkspace('completeness', score)}
                      </Badge>
                    ) : null;
                  })()}
                  {character.status !== 'draft' || character.access_credits > 0 ? (
                    <div className="flex items-center gap-1.5">
                      {character.status !== 'draft' ? (
                        <Badge tone={CREATION_SKILL_STATUS_TONE[character.status]}>
                          {tSkills(CREATION_SKILL_STATUS_LABEL_KEY[character.status])}
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
                              <span className="absolute inset-0 grid place-items-center bg-overlay">
                                <IconVideo className="size-4 text-text" />
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
                    <IconButton
                      size="sm"
                      label={t('manageLooks')}
                      onClick={() => router.push(characterManageHref(character.id))}
                    >
                      <IconGrid className="size-4" />
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

      {editing && describeOpen ? (
        <CharacterDescribeDialog
          open
          onClose={() => setDescribeOpen(false)}
          characterId={editing.id}
          current={{ description: form.description, voiceDescription: form.voiceDescription }}
          onApply={(next) => setForm((current) => ({ ...current, ...next }))}
        />
      ) : null}

      <MediaLightbox
        open={lightboxUrl !== null}
        src={lightboxUrl}
        onClose={() => setLightboxUrl(null)}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={closeDeleteConfirm}
        title={t('deleteConfirmTitle')}
        confirmLabel={tActions('confirm')}
        cancelLabel={tActions('cancel')}
        busy={deletingId !== null}
        onConfirm={() => void remove()}
      >
        <p className="text-sm text-muted">
          {deleteTarget ? t('deleteConfirmBody', { name: deleteTarget.name }) : null}
        </p>
      </ConfirmDialog>

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
