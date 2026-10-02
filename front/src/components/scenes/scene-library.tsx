'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  ExistingAssetPickerDialog,
  type ExistingAssetPick,
} from '@/components/library/existing-asset-picker-dialog';
import { AccessPriceField } from '@/components/marketplace/access-price-field';
import { AssetVariantsSheet } from '@/components/library/asset-variants-sheet';
import { Button, IconButton } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import {
  IconClose,
  IconGrid,
  IconImage,
  IconPencil,
  IconPlus,
  IconShare,
  IconSparkle,
  IconTrash,
  IconUpload,
} from '@/components/ui/icons';
import { MediaLightbox } from '@/components/ui/media-lightbox';
import { Badge, Card, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Sheet } from '@/components/ui/sheet';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { useRouter } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Scene } from '@/lib/api/types';
import {
  CREATION_SKILL_STATUS_LABEL_KEY,
  CREATION_SKILL_STATUS_TONE,
} from '@/lib/creation-skill-status';
import { sceneHeroAsset, sceneImageStudioHref } from '@/lib/scenes';
import { useMinWidth } from '@/lib/use-media-query';
import { uploadFile } from '@/lib/upload';

// Mirrors `scenes.service.MAX_REFERENCE_ASSETS` (master plate + variants).
const MAX_REFERENCE_ASSETS = 8;

// Reuses `skillLibrary`'s own status vocabulary — a scene is a
// `CreationSkillCategory.SCENE_ASSET` skill under the hood (see
// `app.domain.scenes.service.SceneView`). Unlike a character, a scene
// carries no portrait-consent gate, so the publish dialog only asks for
// a price.

interface SceneForm {
  name: string;
  description: string;
  reference: ExistingAssetPick | null;
}

const EMPTY_FORM: SceneForm = {
  name: '',
  description: '',
  reference: null,
};

function heroHref(scene: Pick<Scene, 'id' | 'name' | 'description'>): string {
  return sceneImageStudioHref({
    sceneId: scene.id,
    name: scene.name,
    description: scene.description,
  });
}

/** Extra historical refs that stay on the card strip after the hero is
 * chosen — never the establishing (or first) asset the card already shows. */
function extraReferenceAssets(scene: Scene) {
  const hero = sceneHeroAsset(scene);
  return (scene.reference_assets ?? []).filter((asset) => asset.asset_id !== hero?.asset_id);
}

/** When the form only edits the hero, keep the rest of the list so a
 * content PATCH does not wipe extras via `_entries_from_flat_ids`. The
 * previous card hero is dropped (whether tagged establishing or just
 * first) so replacing the main image does not leave the old one behind. */
function referenceIdsForSave(scene: Scene | null, heroId: string | null): string[] {
  const previousHeroId = scene ? sceneHeroAsset(scene)?.asset_id : undefined;
  const extras = (scene?.reference_assets ?? [])
    .filter((asset) => {
      if (heroId && asset.asset_id === heroId) return false;
      if (previousHeroId && asset.asset_id === previousHeroId) return false;
      return true;
    })
    .map((asset) => asset.asset_id);
  const ids = heroId ? [heroId, ...extras] : extras;
  return ids.slice(0, MAX_REFERENCE_ASSETS);
}

/**
 * Card list of the creator's reusable settings, with a drawer to create or
 * edit one. The card and form show a single establishing hero — extra
 * historical stills stay on a read-only strip — so a future generation
 * call (or a linked script scene heading) can be pointed at it.
 */
export function SceneLibrary({ initial }: { initial: Scene[] }) {
  const t = useTranslations('scenes');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');
  const tSkills = useTranslations('skillLibrary');
  const tMedia = useTranslations('media');
  const { notify } = useToast();
  const router = useRouter();

  const [scenes, setScenes] = useState(initial);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Scene | null>(null);
  const [form, setForm] = useState<SceneForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [saveIntent, setSaveIntent] = useState<'save' | 'saveAndGenerate'>('save');
  const [formError, setFormError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Scene | null>(null);
  const [publishTarget, setPublishTarget] = useState<Scene | null>(null);
  const [publishAccessCredits, setPublishAccessCredits] = useState(0);
  const [publishBusy, setPublishBusy] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null);
  const [variantsTarget, setVariantsTarget] = useState<Scene | null>(null);
  // `Sheet` (bottom drawer) below `lg`, `Dialog` (centred) at/above it —
  // mirrors `character-library.tsx` and `generation-studio-shell.tsx`'s own
  // `lg`-gated Sheet. Safe pre-hydration: `sheetOpen` only ever flips true
  // from a click, never on mount.
  const isDesktop = useMinWidth('lg');

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setSheetOpen(true);
  };

  const openEdit = (scene: Scene) => {
    const hero = sceneHeroAsset(scene);
    setEditing(scene);
    setForm({
      name: scene.name,
      description: scene.description ?? '',
      reference: hero ? { id: hero.asset_id, url: hero.url ?? '' } : null,
    });
    setFormError(null);
    setSheetOpen(true);
  };

  const closeSheet = () => {
    if (saving) return;
    setSheetOpen(false);
  };

  const setReference = (asset: ExistingAssetPick | null) => {
    setForm((current) => ({ ...current, reference: asset }));
  };

  const uploadReference = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const asset = await uploadFile(file, 'generation_reference');
      setReference({ id: asset.id, url: asset.url ?? '' });
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setUploading(false);
    }
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = form.name.trim();
    if (!name) return;
    // Read the clicked submitter — `setSaveIntent` in the button's onClick
    // is not flushed before this handler, so `saveIntent` would still be
    // `'save'` and "保存并生成" would only create the card.
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    const intent =
      submitter instanceof HTMLButtonElement && submitter.value === 'saveAndGenerate'
        ? 'saveAndGenerate'
        : 'save';
    setSaveIntent(intent);

    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        name,
        description: form.description.trim() || null,
        reference_asset_ids: referenceIdsForSave(editing, form.reference?.id ?? null),
      };
      let saved = editing
        ? await api.patch<Scene>(`/v1/scenes/${editing.id}`, payload)
        : await api.post<Scene>('/v1/scenes', payload);
      // The call above resets every reference asset's view tag to `general`
      // (`_entries_from_flat_ids`) — tag the hero as `establishing` so the
      // card and a later studio seed both find it.
      if (form.reference) {
        await api.patch(`/v1/scenes/${saved.id}/reference-assets/${form.reference.id}`, {
          view: 'establishing',
        });
        saved = await api.get<Scene>(`/v1/scenes/${saved.id}`);
      }
      setScenes((current) =>
        editing
          ? current.map((item) => (item.id === saved.id ? saved : item))
          : [saved, ...current],
      );
      setSheetOpen(false);
      if (intent === 'saveAndGenerate' && !form.reference) {
        router.push(heroHref(saved));
      }
    } catch (caught) {
      setFormError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
    } finally {
      setSaving(false);
      setSaveIntent('save');
    }
  };

  const openDeleteConfirm = (scene: Scene) => {
    setDeleteTarget(scene);
  };

  const closeDeleteConfirm = () => {
    if (deletingId) return;
    setDeleteTarget(null);
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setDeletingId(deleteTarget.id);
    try {
      await api.delete(`/v1/scenes/${deleteTarget.id}`);
      setScenes((current) => current.filter((item) => item.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const openPublish = (scene: Scene) => {
    setPublishTarget(scene);
    setPublishAccessCredits(scene.access_credits);
    setPublishError(null);
  };

  const closePublish = () => {
    if (publishBusy) return;
    setPublishTarget(null);
  };

  const publish = async () => {
    if (!publishTarget) return;
    setPublishBusy(true);
    setPublishError(null);
    try {
      if (publishAccessCredits !== publishTarget.access_credits) {
        await api.patch(`/v1/skills/${publishTarget.id}/pricing`, {
          access_credits: publishAccessCredits,
        });
      }
      const saved = await api.post<Scene>(`/v1/scenes/${publishTarget.id}/publish`);
      setScenes((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      notify(tSkills('publishDone'), 'success');
      setPublishTarget(null);
    } catch (caught) {
      setPublishError(caught instanceof ApiError ? caught.message : tSkills('saveFailed'));
    } finally {
      setPublishBusy(false);
    }
  };

  const withdraw = async (scene: Scene) => {
    setWithdrawingId(scene.id);
    try {
      const saved = await api.post<Scene>(`/v1/scenes/${scene.id}/withdraw`);
      setScenes((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      notify(tSkills('withdrawDone'), 'success');
    } catch {
      notify(tSkills('saveFailed'), 'error');
    } finally {
      setWithdrawingId(null);
    }
  };

  const sceneForm = (
    <form id="scene-form" onSubmit={(event) => void submit(event)} className="flex flex-col gap-4">
      <TextInput
        label={t('nameLabel')}
        value={form.name}
        maxLength={80}
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
      <div>
        <p className="text-sm font-medium text-text">{t('sheetLabel')}</p>
        <p className="mt-1 text-xs text-muted">{t('sheetHint')}</p>
        <div className="mt-2 max-w-xs">
          {form.reference ? (
            <div className="relative aspect-video overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
              <button
                type="button"
                aria-label={tMedia('lightboxTitle')}
                onClick={() => setLightboxUrl(form.reference?.url ?? null)}
                className="absolute inset-0"
              >
                <Image
                  src={form.reference.url}
                  alt=""
                  fill
                  sizes="320px"
                  className="object-contain"
                />
              </button>
              <button
                type="button"
                aria-label={tActions('delete')}
                onClick={() => setReference(null)}
                className="absolute right-1 top-1 grid size-5 place-items-center rounded-full bg-surface-raised/90 text-muted hover:text-text"
              >
                <IconClose className="size-3" />
              </button>
            </div>
          ) : (
            <div className="flex aspect-video flex-col overflow-hidden rounded-[var(--radius-sm)] border border-dashed border-border">
              <label className="flex flex-1 cursor-pointer flex-col items-center justify-center gap-1 border-b border-dashed border-border text-muted transition-colors hover:border-border-strong hover:text-text">
                {uploading ? (
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
                  onChange={(event) => void uploadReference(event.target.files?.[0])}
                />
              </label>
              <button
                type="button"
                onClick={() => setPickerOpen(true)}
                className="flex flex-1 flex-col items-center justify-center gap-1 text-muted transition-colors hover:text-text"
              >
                <IconImage className="size-4" />
                <span className="text-[10px]">{t('referenceChooseExisting')}</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </form>
  );

  const canSaveAndGenerate = !form.reference;
  const formFooter = (
    <div className="flex w-full flex-wrap justify-end gap-3">
      <Button variant="ghost" onClick={closeSheet} disabled={saving}>
        {tActions('cancel')}
      </Button>
      {canSaveAndGenerate ? (
        <Button
          type="submit"
          form="scene-form"
          name="intent"
          value="saveAndGenerate"
          variant="secondary"
          loading={saving && saveIntent === 'saveAndGenerate'}
          disabled={saving}
        >
          {t('saveAndGenerate')}
        </Button>
      ) : null}
      <Button
        type="submit"
        form="scene-form"
        name="intent"
        value="save"
        loading={saving && saveIntent === 'save'}
        disabled={saving}
        className="w-28"
      >
        {tActions('save')}
      </Button>
    </div>
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex justify-end">
        <Button onClick={openCreate} icon={<IconPlus className="size-4" />}>
          {t('newScene')}
        </Button>
      </div>

      {scenes.length === 0 ? (
        <EmptyState
          title={t('emptyTitle')}
          description={t('emptyHint')}
          action={<Button onClick={openCreate}>{t('newScene')}</Button>}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {scenes.map((scene) => {
            const hero = sceneHeroAsset(scene);
            const extras = extraReferenceAssets(scene);
            return (
              <li key={scene.id}>
                <Card className="flex h-full flex-col gap-3 p-4">
                  <h3 className="truncate text-sm font-semibold">{scene.name}</h3>
                  <div className="relative aspect-video overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                    {hero?.url ? (
                      <button
                        type="button"
                        aria-label={tMedia('lightboxTitle')}
                        onClick={() => setLightboxUrl(hero.url ?? null)}
                        className="absolute inset-0"
                      >
                        <Image
                          src={hero.url}
                          alt=""
                          fill
                          sizes="360px"
                          className="object-contain"
                        />
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => router.push(heroHref(scene))}
                        className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-muted transition-colors hover:text-text"
                      >
                        <IconSparkle className="size-4" />
                        <span className="text-[10px]">{t('generateSheet')}</span>
                      </button>
                    )}
                  </div>
                  {scene.status !== 'draft' || scene.access_credits > 0 ? (
                    <div className="flex items-center gap-1.5">
                      {scene.status !== 'draft' ? (
                        <Badge tone={CREATION_SKILL_STATUS_TONE[scene.status]}>
                          {tSkills(CREATION_SKILL_STATUS_LABEL_KEY[scene.status])}
                        </Badge>
                      ) : null}
                      {scene.access_credits > 0 ? (
                        <Badge tone="primary">
                          {tSkills('priceCredits', { credits: scene.access_credits })}
                        </Badge>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="min-w-0 flex-1">
                    {scene.description ? (
                      <p className="line-clamp-2 text-xs text-muted">{scene.description}</p>
                    ) : null}
                    {extras.length > 0 ? (
                      <div className="mt-2">
                        <p className="text-[11px] text-muted">{t('extraRefsLabel')}</p>
                        <div className="mt-1 flex gap-2 overflow-x-auto">
                          {extras.map((asset) => (
                            <button
                              key={asset.asset_id}
                              type="button"
                              aria-label={tMedia('lightboxTitle')}
                              onClick={() => setLightboxUrl(asset.url ?? null)}
                              className="relative size-14 shrink-0 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft"
                            >
                              {asset.url ? (
                                <Image
                                  src={asset.url}
                                  alt=""
                                  fill
                                  sizes="56px"
                                  className="object-cover"
                                />
                              ) : null}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                  <div className="mt-auto flex items-center justify-center gap-6 border-t border-border pt-3">
                    <IconButton
                      size="sm"
                      label={hero ? t('generateAgain') : t('generateSheet')}
                      onClick={() => router.push(heroHref(scene))}
                    >
                      <IconSparkle className="size-4" />
                    </IconButton>
                    <IconButton size="sm" label={tActions('edit')} onClick={() => openEdit(scene)}>
                      <IconPencil className="size-4" />
                    </IconButton>
                    <IconButton
                      size="sm"
                      label={t('manageVariants')}
                      onClick={() => setVariantsTarget(scene)}
                    >
                      <IconGrid className="size-4" />
                    </IconButton>
                    {scene.status === 'draft' || scene.status === 'rejected' ? (
                      <IconButton
                        size="sm"
                        label={t('publishScene')}
                        onClick={() => openPublish(scene)}
                      >
                        <IconShare className="size-4" />
                      </IconButton>
                    ) : (
                      <IconButton
                        size="sm"
                        label={tSkills('withdraw')}
                        loading={withdrawingId === scene.id}
                        onClick={() => void withdraw(scene)}
                      >
                        <IconShare className="size-4" />
                      </IconButton>
                    )}
                    <IconButton
                      variant="danger"
                      size="sm"
                      label={tActions('delete')}
                      loading={deletingId === scene.id}
                      onClick={() => openDeleteConfirm(scene)}
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
          title={editing ? t('editScene') : t('newScene')}
          size="lg"
          footer={formFooter}
        >
          <div className="flex flex-col gap-4">
            {formError ? <ErrorNotice title={formError} /> : null}
            {sceneForm}
          </div>
        </Dialog>
      ) : (
        <Sheet
          open={sheetOpen}
          onClose={closeSheet}
          title={editing ? t('editScene') : t('newScene')}
          loading={saving}
          error={formError}
          footer={formFooter}
        >
          {sceneForm}
        </Sheet>
      )}

      <ExistingAssetPickerDialog
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={(asset) => {
          setReference(asset);
          setPickerOpen(false);
        }}
        title={t('referencePickerTitle')}
        empty={t('referencePickerEmpty')}
        error={t('referencePickerError')}
      />

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
        title={t('publishScene')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={closePublish} disabled={publishBusy}>
              {tActions('cancel')}
            </Button>
            <Button loading={publishBusy} onClick={() => void publish()}>
              {tSkills('publish')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted">{t('publishSceneHint')}</p>
          <AccessPriceField
            value={publishAccessCredits}
            onChange={setPublishAccessCredits}
            label={t('priceLabel')}
            hint={t('priceHint')}
          />
          {publishError ? <ErrorNotice title={publishError} /> : null}
        </div>
      </Dialog>
      {variantsTarget ? (
        <AssetVariantsSheet
          kind="scene"
          card={variantsTarget}
          variants={variantsTarget.variants ?? []}
          anchorEntryId={variantsTarget.anchor_entry_id}
          open
          onClose={() => setVariantsTarget(null)}
          onCardChange={(updated) => {
            setVariantsTarget(updated);
            setScenes((current) => current.map((c) => (c.id === updated.id ? updated : c)));
          }}
          generateHref={(variant) =>
            sceneImageStudioHref({
              sceneId: variantsTarget.id,
              name: variantsTarget.name,
              description: variantsTarget.description,
              variantId: variant.id,
              presets: variant.presets as { lighting?: string | null; weather?: string | null },
            })
          }
        />
      ) : null}
    </div>
  );
}
