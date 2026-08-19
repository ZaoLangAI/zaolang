'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { AccessPriceField } from '@/components/marketplace/access-price-field';
import { VideoFirstFrame } from '@/components/media/video-first-frame';
import { Button, IconButton } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import {
  IconClose,
  IconPlus,
  IconTrash,
  IconUpload,
  IconVideo,
} from '@/components/ui/icons';
import { Badge, type BadgeTone, Card, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Sheet } from '@/components/ui/sheet';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { CreationSkillStatus, Scene } from '@/lib/api/types';
import { useMinWidth } from '@/lib/use-media-query';
import { uploadFile } from '@/lib/upload';

const MAX_REFERENCE_ASSETS = 4;

// Reuses `skillLibrary`'s own status vocabulary — a scene is a
// `CreationSkillCategory.SCENE_ASSET` skill under the hood (see
// `app.domain.scenes.service.SceneView`), so "draft / pending review /
// published / rejected" means exactly the same thing here. Unlike a
// character, a scene carries no portrait-consent gate, so publishing is a
// direct action rather than a confirmation dialog.
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

/** Unlike a character's reference images, a scene's reference can be a
 * generated still *or* a generated clip — `kind` picks how the thumbnail
 * renders, since `next/image` cannot preview a video source. */
interface ReferenceAsset {
  id: string;
  url: string;
  kind: 'image' | 'video';
}

interface SceneForm {
  name: string;
  description: string;
  referenceAssets: ReferenceAsset[];
  accessCredits: number;
}

const EMPTY_FORM: SceneForm = {
  name: '',
  description: '',
  referenceAssets: [],
  accessCredits: 0,
};

/**
 * Card list of the creator's reusable settings, with a drawer to create or
 * edit one. A scene only stores up to four reference stills/clips and a
 * description — no location model, no generation itself — so what is
 * offered here is a profile a future generation call (or a linked script
 * scene heading) can be pointed at.
 */
export function SceneLibrary({ initial }: { initial: Scene[] }) {
  const t = useTranslations('scenes');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');
  const tSkills = useTranslations('skillLibrary');
  const { notify } = useToast();

  const [scenes, setScenes] = useState(initial);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Scene | null>(null);
  const [form, setForm] = useState<SceneForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Scene | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null);
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
    setEditing(scene);
    setForm({
      name: scene.name,
      description: scene.description ?? '',
      // The list endpoint doesn't carry per-asset media type — an existing
      // reference is shown generically until it's re-picked. This mirrors
      // `CharacterLibrary`'s own simplification for edit-time thumbnails.
      referenceAssets: (scene.reference_assets ?? []).map((asset) => ({
        id: asset.asset_id,
        url: asset.url ?? '',
        kind: 'image' as const,
      })),
      accessCredits: scene.access_credits,
    });
    setFormError(null);
    setSheetOpen(true);
  };

  const closeSheet = () => {
    if (saving) return;
    setSheetOpen(false);
  };

  const pickReferenceAsset = async (file: File | undefined) => {
    if (!file || form.referenceAssets.length >= MAX_REFERENCE_ASSETS) return;
    setUploading(true);
    try {
      const asset = await uploadFile(file, 'generation_reference');
      setForm((current) => ({
        ...current,
        referenceAssets: [
          ...current.referenceAssets,
          {
            id: asset.id,
            url: asset.url ?? '',
            kind: file.type.startsWith('video/') ? 'video' : 'image',
          },
        ],
      }));
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setUploading(false);
    }
  };

  const removeReferenceAsset = (assetId: string) => {
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
      };
      let saved = editing
        ? await api.patch<Scene>(`/v1/scenes/${editing.id}`, payload)
        : await api.post<Scene>('/v1/scenes', payload);
      // Pricing goes through the generic skill endpoint (a scene is a
      // `CreationSkill` under the hood and shares its id), which responds
      // with a `CreationSkillDetail`, not a `SceneResponse` — refetch the
      // scene shape rather than trust that response. Only called when the
      // price actually changed, since `update_pricing` never unpublishes
      // (unlike the content patch above) and a plain content edit
      // shouldn't touch it.
      if (form.accessCredits !== (editing?.access_credits ?? 0)) {
        await api.patch(`/v1/skills/${saved.id}/pricing`, {
          access_credits: form.accessCredits,
        });
        saved = await api.get<Scene>(`/v1/scenes/${saved.id}`);
      }
      setScenes((current) =>
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

  // No portrait-consent gate to clear first (unlike a character), so
  // sharing/withdrawing a scene is a direct one-click action — see
  // `scenes.service.publish_scene`.
  const publish = async (scene: Scene) => {
    setPublishingId(scene.id);
    try {
      const saved = await api.post<Scene>(`/v1/scenes/${scene.id}/publish`);
      setScenes((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      notify(tSkills('publishDone'), 'success');
    } catch {
      notify(tSkills('saveFailed'), 'error');
    } finally {
      setPublishingId(null);
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

  // Shared between the `Dialog` (desktop) and `Sheet` (mobile) containers
  // below — the two differ only in how they present the same form.
  const sceneForm = (
    <form id="scene-form" onSubmit={(event) => void submit(event)} className="flex flex-col gap-4">
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
      <div>
        <p className="text-sm font-medium text-text">{t('referenceLabel')}</p>
        <p className="mt-1 text-xs text-muted">{t('referenceHint')}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {form.referenceAssets.map((asset) => (
            <div key={asset.id} className="relative size-20">
              {asset.kind === 'video' ? (
                <div className="grid size-20 place-items-center rounded-[var(--radius-sm)] bg-surface-soft text-muted">
                  <IconVideo className="size-6" />
                </div>
              ) : (
                <Image
                  src={asset.url}
                  alt=""
                  fill
                  sizes="80px"
                  className="rounded-[var(--radius-sm)] object-cover"
                />
              )}
              <button
                type="button"
                aria-label={tActions('delete')}
                onClick={() => removeReferenceAsset(asset.id)}
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
                accept="image/*,video/mp4,video/webm"
                className="sr-only"
                onChange={(event) => void pickReferenceAsset(event.target.files?.[0])}
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
  );

  const formFooter = (
    <>
      <Button variant="ghost" onClick={closeSheet} disabled={saving}>
        {tActions('cancel')}
      </Button>
      <Button type="submit" form="scene-form" loading={saving} fullWidth>
        {tActions('save')}
      </Button>
    </>
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
          {scenes.map((scene) => (
            <li key={scene.id}>
              <Card className="flex h-full flex-col gap-3 p-4">
                <div className="flex gap-2 overflow-x-auto">
                  {scene.reference_assets && scene.reference_assets.length > 0 ? (
                    scene.reference_assets.map((asset) => (
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
                    <Badge tone={STATUS_TONE[scene.status]}>
                      {tSkills(STATUS_LABEL_KEY[scene.status])}
                    </Badge>
                    {scene.access_credits > 0 ? (
                      <Badge tone="primary">
                        {tSkills('priceCredits', { credits: scene.access_credits })}
                      </Badge>
                    ) : null}
                  </div>
                  <h3 className="mt-1.5 truncate text-sm font-semibold">{scene.name}</h3>
                  {scene.description ? (
                    <p className="mt-1 line-clamp-2 text-xs text-muted">{scene.description}</p>
                  ) : null}
                  {scene.clips && scene.clips.length > 0 ? (
                    <div className="mt-2">
                      <p className="text-[11px] text-muted">{t('clipsLabel')}</p>
                      <div className="mt-1 flex gap-2 overflow-x-auto">
                        {scene.clips.map((clip) => (
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
                  <Link
                    href={`/create/new?mode=video_creation&videoAssetKind=scene_video&targetSceneId=${scene.id}`}
                    className="mt-2 inline-block text-[11px] text-muted hover:text-text"
                  >
                    {t('generateSceneVideo')}
                  </Link>
                </div>
                {/* Fixed 3-slot row (Edit | Publish-or-Withdraw | Delete),
                    same layout as `character-library.tsx` — status always
                    yields exactly one of Publish/Withdraw, so the grid never
                    has a hole. */}
                <div className="mt-auto grid grid-cols-[1fr_1fr_auto] gap-2">
                  <Button size="sm" variant="secondary" onClick={() => openEdit(scene)}>
                    {tActions('edit')}
                  </Button>
                  {scene.status === 'draft' || scene.status === 'rejected' ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={publishingId === scene.id}
                      onClick={() => void publish(scene)}
                    >
                      {t('publishScene')}
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={withdrawingId === scene.id}
                      onClick={() => void withdraw(scene)}
                    >
                      {tSkills('withdraw')}
                    </Button>
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
          ))}
        </ul>
      )}

      {isDesktop ? (
        <Dialog
          open={sheetOpen}
          onClose={closeSheet}
          title={editing ? t('editScene') : t('newScene')}
          size="md"
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
    </div>
  );
}
