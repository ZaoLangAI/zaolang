'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  ExistingAssetPickerDialog,
  type ExistingAssetPick,
} from '@/components/library/existing-asset-picker-dialog';
import { AccessPriceField } from '@/components/marketplace/access-price-field';
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
import { cardCompleteness } from '@/features/asset-workspace/completeness';
import { workspaceHref } from '@/features/asset-workspace/new-card';
import { withStyleSkill } from '@/features/asset-workspace/style-skill';
import { useRouter } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Prop } from '@/lib/api/types';
import {
  CREATION_SKILL_STATUS_LABEL_KEY,
  CREATION_SKILL_STATUS_TONE,
} from '@/lib/creation-skill-status';
import { propHeroAsset, propManageHref } from '@/lib/props';
import { uploadFile } from '@/lib/upload';
import { useMinWidth } from '@/lib/use-media-query';

// A prop is a `CreationSkillCategory.PROP_ASSET` skill (`props.service.
// PropView`); like a scene it publishes without a portrait-consent gate.

interface PropForm {
  name: string;
  description: string;
  /** 从图片新建: filed as the new card's approved hero plate. */
  reference: ExistingAssetPick | null;
}

const EMPTY_FORM: PropForm = { name: '', description: '', reference: null };

/** The prop's 创作 board, on its hero plate. */
function heroHref(prop: Pick<Prop, 'id'>): string {
  return workspaceHref(propManageHref(prop.id), 'master');
}

/**
 * The creator's reusable objects (信物、武器、道具…) — the 道具创作 start
 * page. A new card opens its workspace; editing here is text-only (the
 * images live in the workspace, and a flat `reference_asset_ids` replace
 * would drop the ones it does not list).
 */
export function PropLibrary({
  initial,
  styleSkillId = null,
}: {
  initial: Prop[];
  /** A plaza style skill (`?skillId=`) every card link carries on. */
  styleSkillId?: string | null;
}) {
  const t = useTranslations('props');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');
  const tSkills = useTranslations('skillLibrary');
  const tMedia = useTranslations('media');
  const tWorkspace = useTranslations('assetWorkspace');
  const { notify } = useToast();
  const router = useRouter();
  const go = (href: string) => router.push(withStyleSkill(href, styleSkillId));

  const [props, setProps] = useState(initial);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<Prop | null>(null);
  const [form, setForm] = useState<PropForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Prop | null>(null);
  const [publishTarget, setPublishTarget] = useState<Prop | null>(null);
  const [publishAccessCredits, setPublishAccessCredits] = useState(0);
  const [publishBusy, setPublishBusy] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [withdrawingId, setWithdrawingId] = useState<string | null>(null);
  // `Sheet` below `lg`, `Dialog` at/above it — as the scene library.
  const isDesktop = useMinWidth('lg');

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setSheetOpen(true);
  };

  const openEdit = (prop: Prop) => {
    setEditing(prop);
    setForm({ name: prop.name, description: prop.description ?? '', reference: null });
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
    setSaving(true);
    setFormError(null);
    try {
      const description = form.description.trim() || null;
      // A create's first image becomes the hero plate (`props.service.
      // _promote_master`); an edit never sends the list.
      const saved = editing
        ? await api.patch<Prop>(`/v1/props/${editing.id}`, { name, description })
        : await api.post<Prop>('/v1/props', {
            name,
            description,
            reference_asset_ids: form.reference ? [form.reference.id] : [],
          });
      setProps((current) =>
        editing
          ? current.map((item) => (item.id === saved.id ? saved : item))
          : [saved, ...current],
      );
      setSheetOpen(false);
      // A new card opens on its 创作 board — on the hero plate, or with one
      // already filed, on the first turntable angle drawn from it.
      if (!editing) {
        go(workspaceHref(propManageHref(saved.id), form.reference ? 'side' : 'master'));
      }
    } catch (caught) {
      setFormError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
    } finally {
      setSaving(false);
    }
  };

  const closeDeleteConfirm = () => {
    if (deletingId) return;
    setDeleteTarget(null);
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setDeletingId(deleteTarget.id);
    try {
      await api.delete(`/v1/props/${deleteTarget.id}`);
      setProps((current) => current.filter((item) => item.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const openPublish = (prop: Prop) => {
    setPublishTarget(prop);
    setPublishAccessCredits(prop.access_credits ?? 0);
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
      const saved = await api.post<Prop>(`/v1/props/${publishTarget.id}/publish`);
      setProps((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      notify(tSkills('publishDone'), 'success');
      setPublishTarget(null);
    } catch (caught) {
      setPublishError(caught instanceof ApiError ? caught.message : tSkills('saveFailed'));
    } finally {
      setPublishBusy(false);
    }
  };

  const withdraw = async (prop: Prop) => {
    setWithdrawingId(prop.id);
    try {
      const saved = await api.post<Prop>(`/v1/props/${prop.id}/withdraw`);
      setProps((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      notify(tSkills('withdrawDone'), 'success');
    } catch {
      notify(tSkills('saveFailed'), 'error');
    } finally {
      setWithdrawingId(null);
    }
  };

  const propForm = (
    <form id="prop-form" onSubmit={(event) => void submit(event)} className="flex flex-col gap-4">
      <TextInput
        label={t('nameLabel')}
        value={form.name}
        maxLength={80}
        required
        placeholder={t('namePlaceholder')}
        onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
      />
      <TextArea
        label={t('descriptionLabel')}
        hint={t('descriptionHint')}
        value={form.description}
        maxLength={2000}
        onChange={(event) =>
          setForm((current) => ({ ...current, description: event.target.value }))
        }
      />
      {editing ? null : (
        <div>
          <p className="text-sm font-medium text-text">{t('heroLabel')}</p>
          <p className="mt-1 text-xs text-muted">{t('heroHint')}</p>
          <div className="mt-2 max-w-48">
            {form.reference ? (
              <div className="relative aspect-square overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
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
                    sizes="192px"
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
              <div className="flex aspect-square flex-col overflow-hidden rounded-[var(--radius-sm)] border border-dashed border-border">
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
      )}
    </form>
  );

  const formFooter = (
    <div className="flex w-full flex-wrap justify-end gap-3">
      <Button variant="ghost" onClick={closeSheet} disabled={saving}>
        {tActions('cancel')}
      </Button>
      <Button type="submit" form="prop-form" loading={saving} disabled={saving || uploading}>
        {editing ? tActions('save') : t('createAndOpen')}
      </Button>
    </div>
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex justify-end">
        <Button onClick={openCreate} icon={<IconPlus className="size-4" />}>
          {t('newProp')}
        </Button>
      </div>

      {props.length === 0 ? (
        <EmptyState
          title={t('emptyTitle')}
          description={t('emptyHint')}
          action={<Button onClick={openCreate}>{t('newProp')}</Button>}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {props.map((prop) => {
            const hero = propHeroAsset(prop);
            const score = cardCompleteness('prop', prop.variants ?? []);
            const status = prop.status ?? 'draft';
            const credits = prop.access_credits ?? 0;
            return (
              <li key={prop.id}>
                <Card className="flex h-full flex-col gap-3 p-4">
                  <h3 className="truncate text-sm font-semibold">{prop.name}</h3>
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
                        onClick={() => go(heroHref(prop))}
                        className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-muted transition-colors hover:text-text"
                      >
                        <IconSparkle className="size-4" />
                        <span className="text-[10px]">{t('generateHero')}</span>
                      </button>
                    )}
                  </div>
                  {score || status !== 'draft' || credits > 0 ? (
                    <div className="flex flex-wrap items-center gap-1.5">
                      {score ? (
                        <Badge tone={score.done === score.total ? 'success' : 'neutral'}>
                          {tWorkspace('completeness', score)}
                        </Badge>
                      ) : null}
                      {status !== 'draft' ? (
                        <Badge tone={CREATION_SKILL_STATUS_TONE[status]}>
                          {tSkills(CREATION_SKILL_STATUS_LABEL_KEY[status])}
                        </Badge>
                      ) : null}
                      {credits > 0 ? (
                        <Badge tone="primary">{tSkills('priceCredits', { credits })}</Badge>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="min-w-0 flex-1">
                    {prop.description ? (
                      <p className="line-clamp-2 text-xs text-muted">{prop.description}</p>
                    ) : null}
                  </div>
                  <div className="mt-auto flex items-center justify-center gap-6 border-t border-border pt-3">
                    <IconButton
                      size="sm"
                      label={hero ? t('generateAgain') : t('generateHero')}
                      onClick={() => go(heroHref(prop))}
                    >
                      <IconSparkle className="size-4" />
                    </IconButton>
                    <IconButton size="sm" label={tActions('edit')} onClick={() => openEdit(prop)}>
                      <IconPencil className="size-4" />
                    </IconButton>
                    <IconButton
                      size="sm"
                      label={t('openWorkspace')}
                      onClick={() => go(propManageHref(prop.id))}
                    >
                      <IconGrid className="size-4" />
                    </IconButton>
                    {status === 'draft' || status === 'rejected' ? (
                      <IconButton
                        size="sm"
                        label={t('publishProp')}
                        onClick={() => openPublish(prop)}
                      >
                        <IconShare className="size-4" />
                      </IconButton>
                    ) : (
                      <IconButton
                        size="sm"
                        label={tSkills('withdraw')}
                        loading={withdrawingId === prop.id}
                        onClick={() => void withdraw(prop)}
                      >
                        <IconShare className="size-4" />
                      </IconButton>
                    )}
                    <IconButton
                      variant="danger"
                      size="sm"
                      label={tActions('delete')}
                      loading={deletingId === prop.id}
                      onClick={() => setDeleteTarget(prop)}
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
          title={editing ? t('editProp') : t('newProp')}
          size="lg"
          footer={formFooter}
        >
          <div className="flex flex-col gap-4">
            {formError ? <ErrorNotice title={formError} /> : null}
            {propForm}
          </div>
        </Dialog>
      ) : (
        <Sheet
          open={sheetOpen}
          onClose={closeSheet}
          title={editing ? t('editProp') : t('newProp')}
          loading={saving}
          error={formError}
          footer={formFooter}
        >
          {propForm}
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
        title={t('publishProp')}
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
          <p className="text-xs text-muted">{t('publishPropHint')}</p>
          <AccessPriceField
            value={publishAccessCredits}
            onChange={setPublishAccessCredits}
            label={t('priceLabel')}
            hint={t('priceHint')}
          />
          {publishError ? <ErrorNotice title={publishError} /> : null}
        </div>
      </Dialog>
    </div>
  );
}
