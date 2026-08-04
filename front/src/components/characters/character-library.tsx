'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { TextArea, TextInput } from '@/components/ui/field';
import { IconClose, IconPlus, IconUpload } from '@/components/ui/icons';
import { Card, EmptyState } from '@/components/ui/primitives';
import { Sheet } from '@/components/ui/sheet';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Character } from '@/lib/api/types';
import { uploadFile } from '@/lib/upload';

const MAX_REFERENCE_ASSETS = 4;

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
}

const EMPTY_FORM: CharacterForm = {
  name: '',
  description: '',
  voiceDescription: '',
  referenceAssets: [],
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
      referenceAssets: (character.reference_asset_ids ?? []).map((id, index) => ({
        id,
        url: character.reference_asset_urls?.[index] ?? '',
      })),
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
      const saved = editing
        ? await api.patch<Character>(`/v1/characters/${editing.id}`, payload)
        : await api.post<Character>('/v1/characters', payload);
      setCharacters((current) =>
        editing ? current.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...current],
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
                  {character.reference_asset_urls && character.reference_asset_urls.length > 0 ? (
                    character.reference_asset_urls.map((url) => (
                      <div
                        key={url}
                        className="relative size-16 shrink-0 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft"
                      >
                        <Image src={url} alt="" fill sizes="64px" className="object-cover" />
                      </div>
                    ))
                  ) : (
                    <div className="grid size-16 shrink-0 place-items-center rounded-[var(--radius-sm)] bg-surface-soft text-[10px] text-muted">
                      {t('noReference')}
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-sm font-semibold">{character.name}</h3>
                  {character.description ? (
                    <p className="mt-1 line-clamp-2 text-xs text-muted">{character.description}</p>
                  ) : null}
                  {character.voice_description ? (
                    <p className="mt-1 line-clamp-1 text-[11px] text-muted">
                      {t('voiceLabel')}: {character.voice_description}
                    </p>
                  ) : null}
                </div>
                <div className="mt-auto flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => openEdit(character)}>
                    {tActions('edit')}
                  </Button>
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
        <form id="character-form" onSubmit={(event) => void submit(event)} className="flex flex-col gap-4">
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
        </form>
      </Sheet>
    </div>
  );
}
