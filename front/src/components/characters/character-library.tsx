'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  CharacterImageStudio,
  type CharacterGender,
} from '@/components/characters/character-image-studio';
import { CharacterVoiceStudio } from '@/components/characters/character-voice-studio';
import { AccessPriceField } from '@/components/marketplace/access-price-field';
import { VideoFirstFrame } from '@/components/media/video-first-frame';
import { OptionGroup } from '@/components/studio/option-group';
import { Button, IconButton } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog } from '@/components/ui/dialog';
import { Field, Select, TextInput } from '@/components/ui/field';
import {
  IconGrid,
  IconMic,
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
import { cardCompleteness } from '@/features/asset-workspace/completeness';
import { withStyleSkill } from '@/features/asset-workspace/style-skill';
import { AGE_STAGES, type AgeStage, keysOf } from '@/features/image-assets/vocabulary';
import { useRouter } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Character } from '@/lib/api/types';
import { characterHeroUrl, characterManageHref } from '@/lib/characters';
import { cn } from '@/lib/cn';
import {
  CREATION_SKILL_STATUS_LABEL_KEY,
  CREATION_SKILL_STATUS_TONE,
} from '@/lib/creation-skill-status';
import { useMinWidth } from '@/lib/use-media-query';

const GENDER_KEYS: readonly CharacterGender[] = ['male', 'female', 'other'] as const;
const PERSONALITY_PRESETS = [
  'cold',
  'gentle',
  'tsundere',
  'calm',
  'lively',
  'scheming',
  'passionate',
  'mysterious',
] as const;

interface CharacterBasicForm {
  name: string;
  gender: CharacterGender | null;
  age: AgeStage | null;
  personality: string;
}

const EMPTY_FORM: CharacterBasicForm = {
  name: '',
  gender: null,
  age: null,
  personality: '',
};

type ActiveStudioView =
  | { kind: 'image-create' }
  | { kind: 'image-edit'; character: Character }
  | { kind: 'voice'; character: Character }
  | null;

/**
 * Card list of the creator's reusable cast (`source='library'`).
 *
 * - Script-created characters are managed centrally within the script module
 *   (`source='script'`), so "从剧本导入" and "根据剧本 AI 生成" are not shown here.
 * - Creating a new character or editing a character's image opens
 *   `CharacterImageStudio` (restricted to character images).
 * - Editing a character maintains only 4 user fields (`角色名`, `性别`, `年龄`,
 *   `性格`), while `description` (角色图提示词) and `voice_description`
 *   (音色提示词) are read-only and updated only when confirming a generated
 *   character image or voice in their respective studios.
 */
export function CharacterLibrary({
  initial,
  styleSkillId = null,
}: {
  initial: Character[];
  /** A plaza style skill (`?skillId=`) every card link carries on. */
  styleSkillId?: string | null;
}) {
  const t = useTranslations('characters');
  const tPreset = useTranslations('remixPage.presets');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');
  const tMedia = useTranslations('media');
  const tWorkspace = useTranslations('assetWorkspace');
  const tSkills = useTranslations('skillLibrary');
  const { notify } = useToast();
  const router = useRouter();
  const go = (href: string) => router.push(withStyleSkill(href, styleSkillId));

  const [characters, setCharacters] = useState(initial);
  const [studioView, setStudioView] = useState<ActiveStudioView>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Character | null>(null);
  const [form, setForm] = useState<CharacterBasicForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Character | null>(null);
  const isDesktop = useMinWidth('lg');

  const [publishTarget, setPublishTarget] = useState<Character | null>(null);
  const [publishAccessCredits, setPublishAccessCredits] = useState(0);
  const [portraitConsent, setPortraitConsent] = useState(false);
  const [publishBusy, setPublishBusy] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null);

  const upsertCharacterInList = (saved: Character) => {
    setCharacters((current) => {
      const exists = current.some((item) => item.id === saved.id);
      return exists
        ? current.map((item) => (item.id === saved.id ? saved : item))
        : [saved, ...current];
    });
  };

  const openCreateStudio = () => {
    setStudioView({ kind: 'image-create' });
  };

  const openImageEditStudio = async (character: Character) => {
    setSheetOpen(false);
    try {
      const full = await api.get<Character>(`/v1/characters/${character.id}`);
      upsertCharacterInList(full);
      setStudioView({ kind: 'image-edit', character: full });
    } catch {
      setStudioView({ kind: 'image-edit', character });
    }
  };

  const openVoiceStudio = async (character: Character) => {
    setSheetOpen(false);
    try {
      const full = await api.get<Character>(`/v1/characters/${character.id}`);
      upsertCharacterInList(full);
      setStudioView({ kind: 'voice', character: full });
    } catch {
      setStudioView({ kind: 'voice', character });
    }
  };

  const openEdit = (character: Character) => {
    setEditing(character);
    setForm({
      name: character.name,
      gender: (character.gender as CharacterGender | null) ?? null,
      age: (character.age as AgeStage | null) ?? null,
      personality: character.personality ?? '',
    });
    setFormError(null);
    setNameError(null);
    setSheetOpen(true);
  };

  const closeSheet = () => {
    if (saving) return;
    setSheetOpen(false);
  };

  const togglePersonalityPreset = (presetKey: (typeof PERSONALITY_PRESETS)[number]) => {
    const label = t(`personalityPresets.${presetKey}`);
    const tokens = form.personality
      .split(/[、，,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const next = tokens.includes(label)
      ? tokens.filter((item) => item !== label)
      : [...tokens, label];
    setForm((curr) => ({ ...curr, personality: next.join('、') }));
  };

  const submitBasicProfile = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing) return;
    const name = form.name.trim();
    if (!name) return;
    const duplicate = characters.some(
      (item) => item.id !== editing.id && item.name.trim() === name,
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
      const saved = await api.patch<Character>(`/v1/characters/${editing.id}`, {
        name,
        gender: form.gender,
        age: form.age,
        personality: form.personality.trim() || null,
      });
      upsertCharacterInList(saved);
      setEditing(saved);
      setSheetOpen(false);
      notify(t('updated'), 'success');
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
      upsertCharacterInList(saved);
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
      upsertCharacterInList(saved);
      notify(tSkills('withdrawDone'), 'success');
    } catch {
      notify(tSkills('saveFailed'), 'error');
    } finally {
      setWithdrawingId(null);
    }
  };

  // ---- Studio Views (Create Character Image Studio / Edit Image Studio / Voice Studio)
  if (studioView?.kind === 'image-create') {
    return (
      <CharacterImageStudio
        initialStyleSkillId={styleSkillId}
        onConfirmed={(created) => {
          upsertCharacterInList(created);
          setStudioView(null);
        }}
        onCancel={() => setStudioView(null)}
      />
    );
  }

  if (studioView?.kind === 'image-edit') {
    return (
      <CharacterImageStudio
        character={studioView.character}
        initialStyleSkillId={styleSkillId}
        onConfirmed={(updated) => {
          upsertCharacterInList(updated);
          setStudioView({ kind: 'image-edit', character: updated });
        }}
        onCancel={() => setStudioView(null)}
      />
    );
  }

  if (studioView?.kind === 'voice') {
    return (
      <CharacterVoiceStudio
        character={studioView.character}
        onCharacterUpdated={(updated) => {
          upsertCharacterInList(updated);
          setStudioView({ kind: 'voice', character: updated });
        }}
        onClose={() => setStudioView(null)}
      />
    );
  }

  const characterEditForm = editing ? (
    <form
      id="character-form"
      onSubmit={(event) => void submitBasicProfile(event)}
      className="flex flex-col gap-4"
    >
      {/* 4 User-maintained fields */}
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

      <OptionGroup
        label={t('genderLabel')}
        value={form.gender ?? ''}
        onChange={(val) =>
          setForm((curr) => ({ ...curr, gender: (val || null) as CharacterGender | null }))
        }
        columns={3}
        options={GENDER_KEYS.map((key) => ({
          value: key,
          label: t(`genderOptions.${key}`),
        }))}
      />

      <Select
        label={t('ageLabel')}
        value={form.age ?? ''}
        onChange={(e) =>
          setForm((curr) => ({ ...curr, age: (e.target.value || null) as AgeStage | null }))
        }
        options={[
          { value: '', label: t('ageUnset') },
          ...keysOf(AGE_STAGES).map((stage) => ({
            value: stage,
            label: tPreset(AGE_STAGES[stage].labelKey),
          })),
        ]}
      />

      <Field label={t('personalityLabel')} hint={t('personalityHint')}>
        {({ controlId, describedBy }) => (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-1.5">
              {PERSONALITY_PRESETS.map((presetKey) => {
                const label = t(`personalityPresets.${presetKey}`);
                const selected = form.personality
                  .split(/[、，,\s]+/)
                  .map((s) => s.trim())
                  .includes(label);
                return (
                  <button
                    key={presetKey}
                    type="button"
                    onClick={() => togglePersonalityPreset(presetKey)}
                    className={cn(
                      'rounded-full border px-2.5 py-0.5 text-xs transition-colors',
                      selected
                        ? 'border-primary bg-primary/15 font-medium text-primary'
                        : 'border-border bg-surface-soft text-muted hover:text-text',
                    )}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            <input
              id={controlId}
              aria-describedby={describedBy}
              className="w-full rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2 text-sm text-text placeholder:text-muted/70 transition-colors"
              value={form.personality}
              maxLength={200}
              placeholder={t('personalityPlaceholder')}
              onChange={(event) =>
                setForm((current) => ({ ...current, personality: event.target.value }))
              }
            />
          </div>
        )}
      </Field>

      {/* Read-only Character Image Base Prompt */}
      <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface-soft p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-text">{t('readOnlyImagePromptLabel')}</span>
            <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-muted">
              {t('readOnlyBadge')}
            </span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            icon={<IconSparkle className="size-3.5" />}
            onClick={() => void openImageEditStudio(editing)}
          >
            {t('openImageStudioAction')}
          </Button>
        </div>
        <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted">
          {editing.description || t('readOnlyImagePromptEmpty')}
        </p>
        <p className="text-[11px] text-muted">{t('readOnlyPromptExplain')}</p>
      </div>

      {/* Read-only Voice Base Prompt & Voice Studio entry */}
      <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface-soft p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-text">{t('readOnlyVoicePromptLabel')}</span>
            <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-muted">
              {t('readOnlyBadge')}
            </span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            icon={<IconMic className="size-3.5" />}
            onClick={() => void openVoiceStudio(editing)}
          >
            {t('openVoiceStudioAction')}
          </Button>
        </div>
        <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted">
          {editing.voice_description || t('readOnlyVoicePromptEmpty')}
        </p>
        <p className="text-[11px] text-muted">{t('readOnlyVoicePromptExplain')}</p>
      </div>
    </form>
  ) : null;

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
        {tActions('save')}
      </Button>
    </div>
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap justify-end gap-2">
        <Button onClick={openCreateStudio} icon={<IconPlus className="size-4" />}>
          {t('newCharacter')}
        </Button>
      </div>

      {characters.length === 0 ? (
        <EmptyState
          title={t('emptyTitle')}
          description={t('emptyHint')}
          action={<Button onClick={openCreateStudio}>{t('newCharacter')}</Button>}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {characters.map((character) => {
            const hero = characterHeroUrl(character);
            const ageKey = character.age as AgeStage | null | undefined;
            const ageLabel =
              ageKey && ageKey in AGE_STAGES ? tPreset(AGE_STAGES[ageKey].labelKey) : null;
            const genderLabel = character.gender ? t(`genderOptions.${character.gender}`) : null;

            return (
              <li key={character.id}>
                <Card className="flex h-full flex-col gap-3 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="truncate text-sm font-semibold">{character.name}</h3>
                    <div className="flex flex-wrap items-center gap-1">
                      {genderLabel ? <Badge tone="neutral">{genderLabel}</Badge> : null}
                      {ageLabel ? <Badge tone="neutral">{ageLabel}</Badge> : null}
                    </div>
                  </div>

                  {character.personality ? (
                    <p className="truncate text-xs text-primary">{character.personality}</p>
                  ) : null}

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
                        onClick={() => void openImageEditStudio(character)}
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
                      <p className="line-clamp-2 text-xs text-muted" title={character.description}>
                        {character.description}
                      </p>
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

                  <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-3">
                    <IconButton
                      size="sm"
                      label={tActions('edit')}
                      onClick={() => openEdit(character)}
                    >
                      <IconPencil className="size-4" />
                    </IconButton>
                    <IconButton
                      size="sm"
                      label={t('openImageStudioAction')}
                      onClick={() => void openImageEditStudio(character)}
                    >
                      <IconSparkle className="size-4" />
                    </IconButton>
                    <IconButton
                      size="sm"
                      label={t('openVoiceStudioAction')}
                      onClick={() => void openVoiceStudio(character)}
                    >
                      <IconMic className="size-4" />
                    </IconButton>
                    <IconButton
                      size="sm"
                      label={t('manageLooks')}
                      onClick={() => go(characterManageHref(character.id))}
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
          title={t('editCharacter')}
          size="lg"
          footer={formFooter}
        >
          <div className="flex flex-col gap-4">
            {formError ? <ErrorNotice title={formError} /> : null}
            {characterEditForm}
          </div>
        </Dialog>
      ) : (
        <Sheet
          open={sheetOpen}
          onClose={closeSheet}
          title={t('editCharacter')}
          loading={saving}
          error={formError}
          footer={formFooter}
        >
          {characterEditForm}
        </Sheet>
      )}

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
