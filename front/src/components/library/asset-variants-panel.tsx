'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { LookFillDialog } from '@/components/characters/look-fill-dialog';
import { matchesPresetFilter } from '@/features/image-assets/matrix';
import {
  CHARACTER_ENTRY_TYPES,
  EntryCard,
  SCENE_ENTRY_TYPES,
  type CardKind,
} from '@/components/library/entry-actions';
import { candidateCount, groupEntries } from '@/components/library/entry-groups';
import { SceneMatrixDialog } from '@/components/scenes/scene-matrix-dialog';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { IconPlus, IconSparkle, IconUpload } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import {
  AGE_STAGES,
  keysOf,
  SCENE_LIGHTINGS,
  SCENE_PERIODS,
  SCENE_STATES,
  SCENE_WEATHERS,
  type ScenePresets,
} from '@/features/image-assets/vocabulary';
import { useRouter } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { AssetEntry, AssetEntryType, AssetVariant } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { uploadFile } from '@/lib/upload';

export type { CardKind };

const VARIANT_FILTER_THRESHOLD = 8;
const PRESET_AXES = [
  { axis: 'lighting', table: SCENE_LIGHTINGS },
  { axis: 'weather', table: SCENE_WEATHERS },
  { axis: 'state', table: SCENE_STATES },
  { axis: 'period', table: SCENE_PERIODS },
] as const;

/**
 * A character's looks (造型) or a scene's variants (变体) and the images
 * filed under each — `/v1/{characters|scenes}/{id}/{looks|variants}…`.
 * Every change refetches the card and hands it back via `onCardChange`, so
 * the page holding it (`/create/{characters|scenes}/[id]`) stays in step.
 *
 * Images are grouped by role (`groupEntries`). A generated image whose slot
 * already had an approved one arrives as a candidate (P2-1): it is shown
 * after the approved image so the two can be compared, and 定稿 swaps them.
 * Candidates are never removed automatically — only from here.
 */
export function AssetVariantsPanel<TCard extends { id: string; name: string }>({
  kind,
  card,
  variants,
  anchorEntryId,
  initialVariantId,
  onCardChange,
  generateHref,
  portraitHref,
}: {
  kind: CardKind;
  card: TCard;
  variants: AssetVariant[];
  anchorEntryId: string | null | undefined;
  /** Opens on this look / variant (`?look=`), else the first. */
  initialVariantId?: string | null;
  onCardChange: (card: TCard) => void;
  /** Image-studio deep link that files its output under `variant`. */
  generateHref: (variant: AssetVariant) => string;
  /** Characters: image-studio deep link for the identity portrait (定妆照). */
  portraitHref?: string;
}) {
  const t = useTranslations('assetVariants');
  const tPresetLabels = useTranslations('remixPage');
  const { notify } = useToast();
  const router = useRouter();
  const base = `/v1/${kind === 'character' ? 'characters' : 'scenes'}/${card.id}`;
  const segment = kind === 'character' ? 'looks' : 'variants';
  const [activeId, setActiveId] = useState<string | null>(initialVariantId ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftName, setDraftName] = useState('');
  // A new look's outfit description — what a 换装 sheet is drawn to (P2-3).
  const [draftDescription, setDraftDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [matrixOpen, setMatrixOpen] = useState(false);
  const [fillOpen, setFillOpen] = useState(false);
  // Scene cards have no variant cap (P2-5): past a handful, the tabs get a
  // filter — per preset axis for scenes (§9.3), by name for looks.
  const [filter, setFilter] = useState('');
  const [presetFilter, setPresetFilter] = useState<ScenePresets>({});
  const filtering = variants.length > VARIANT_FILTER_THRESHOLD;
  const visibleVariants = !filtering
    ? variants
    : kind === 'scene'
      ? variants.filter((variant) =>
          matchesPresetFilter(variant.presets, presetFilter as Record<string, string>),
        )
      : filter.trim()
        ? variants.filter((variant) => variant.name.includes(filter.trim()))
        : variants;

  const active = variants.find((v) => v.id === activeId) ?? variants[0];
  // The card's face every look is drawn from (P2-2); offered until one is approved.
  const hasPortrait = variants.some((variant) =>
    (variant.entries ?? []).some(
      (entry) => entry.entry_type === 'identity_portrait' && entry.status !== 'candidate',
    ),
  );
  const entryTypes = kind === 'character' ? CHARACTER_ENTRY_TYPES : SCENE_ENTRY_TYPES;

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      onCardChange(await api.get<TCard>(base));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('genericError'));
    } finally {
      setBusy(false);
    }
  };

  const createVariant = () =>
    run(async () => {
      const created = await api.post<AssetVariant>(`${base}/${segment}`, {
        name: draftName.trim(),
        description: draftDescription.trim() || null,
      });
      setActiveId(created.id);
      setDraftName('');
      setDraftDescription('');
      setCreating(false);
    });

  const updateVariant = (variant: AssetVariant, body: Record<string, unknown>) =>
    run(() => api.patch(`${base}/${segment}/${variant.id}`, body));

  const deleteVariant = (variant: AssetVariant) =>
    run(async () => {
      await api.delete(`${base}/${segment}/${variant.id}`);
      setActiveId(null);
    });

  const updateEntry = (entry: AssetEntry, body: Record<string, unknown>) =>
    run(() => api.patch(`${base}/entries/${entry.id}`, body));

  const upload = (variant: AssetVariant, file: File, entryType?: AssetEntryType) =>
    run(async () => {
      const asset = await uploadFile(file, 'generation_reference');
      await api.post(`${base}/${segment}/${variant.id}/entries`, {
        asset_id: asset.id,
        entry_type:
          entryType ??
          (kind === 'character' ? 'other' : (variant.entries ?? []).length ? 'shot' : 'master'),
      });
      notify(t('uploaded'), 'success');
    });

  return (
    <section aria-busy={busy} className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-muted">
          {t(kind === 'character' ? 'hintLooks' : 'hintVariants')}
        </p>
        {busy ? <Spinner className="size-4 shrink-0" /> : null}
      </div>
      {error ? <ErrorNotice title={error} /> : null}
      <div className="flex flex-col gap-4">
        {kind === 'character' && portraitHref && !hasPortrait ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-dashed border-border p-3">
            <p className="text-xs text-muted">{t('portraitFirst')}</p>
            <Button
              size="sm"
              variant="secondary"
              icon={<IconSparkle className="size-3.5" />}
              onClick={() => router.push(portraitHref)}
            >
              {t('generatePortrait')}
            </Button>
          </div>
        ) : null}
        {filtering && kind === 'scene' ? (
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1 text-xs font-medium text-muted">{t('filterVariants')}</legend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PRESET_AXES.map(({ axis, table }) => {
                const present = new Set(
                  variants.map((variant) => (variant.presets as ScenePresets | undefined)?.[axis]),
                );
                return (
                  <Select
                    key={axis}
                    label={tPresetLabels(`presets.axis${axis[0]?.toUpperCase()}${axis.slice(1)}`)}
                    value={presetFilter[axis] ?? ''}
                    onChange={(event) =>
                      setPresetFilter((current) => ({
                        ...current,
                        [axis]: event.target.value || undefined,
                      }))
                    }
                    options={[
                      { value: '', label: t('filterAll') },
                      ...Object.entries(table)
                        .filter(([key]) => present.has(key as never))
                        .map(([key, entry]) => ({
                          value: key,
                          label: tPresetLabels(`presets.${entry.labelKey}`),
                        })),
                    ]}
                  />
                );
              })}
            </div>
          </fieldset>
        ) : filtering ? (
          <TextInput
            label={t('filterVariants')}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder={t('filterVariantsPlaceholder')}
          />
        ) : null}
        <div role="tablist" className="flex flex-wrap gap-1.5">
          {visibleVariants.map((variant) => (
            <button
              key={variant.id}
              type="button"
              role="tab"
              aria-selected={variant.id === active?.id}
              onClick={() => setActiveId(variant.id)}
              className={cn(
                'rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-xs transition-colors',
                variant.id === active?.id
                  ? 'border-primary bg-primary/10 text-text'
                  : 'border-border text-muted hover:text-text',
              )}
            >
              {variant.name}
              {variant.is_default ? ` · ${t('default')}` : ''}
              <span className="ml-1 text-muted">
                ({(variant.entries ?? []).length - candidateCount(variant.entries ?? [])}
                {candidateCount(variant.entries ?? [])
                  ? ` · ${t('candidateCount', { count: candidateCount(variant.entries ?? []) })}`
                  : ''}
                )
              </span>
            </button>
          ))}
          <Button
            size="sm"
            variant="secondary"
            icon={<IconPlus className="size-3.5" />}
            onClick={() => setCreating((v) => !v)}
          >
            {t(kind === 'character' ? 'newLook' : 'newVariant')}
          </Button>
          {kind === 'scene' ? (
            <Button
              size="sm"
              variant="secondary"
              icon={<IconSparkle className="size-3.5" />}
              onClick={() => setMatrixOpen(true)}
            >
              {t('matrixOpen')}
            </Button>
          ) : null}
        </div>

        {creating ? (
          <form
            className="flex flex-col gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (draftName.trim()) void createVariant();
            }}
          >
            <TextInput
              label={t('name')}
              value={draftName}
              maxLength={40}
              onChange={(event) => setDraftName(event.target.value)}
              placeholder={t(kind === 'character' ? 'lookPlaceholder' : 'variantPlaceholder')}
            />
            {kind === 'character' ? (
              <TextArea
                label={t('lookDescription')}
                value={draftDescription}
                maxLength={2000}
                onChange={(event) => setDraftDescription(event.target.value)}
                placeholder={t('lookDescriptionPlaceholder')}
                className="min-h-16"
              />
            ) : null}
            <Button type="submit" disabled={!draftName.trim()} className="self-end">
              {t('create')}
            </Button>
          </form>
        ) : null}

        {active ? (
          <VariantPanel
            key={active.id}
            kind={kind}
            variant={active}
            variants={variants}
            anchorEntryId={anchorEntryId}
            entryTypes={entryTypes}
            onUpdate={(body) => void updateVariant(active, body)}
            onDelete={() => void deleteVariant(active)}
            onUpload={(file, entryType) => void upload(active, file, entryType)}
            onEntryUpdate={(entry, body) => void updateEntry(entry, body)}
            onEntryDelete={(entry) => void run(() => api.delete(`${base}/entries/${entry.id}`))}
            onAnchor={(entry) => void run(() => api.post(`${base}/entries/${entry.id}:anchor`))}
            onApprove={(entry) => void run(() => api.post(`${base}/entries/${entry.id}:approve`))}
            onClearCandidates={(entries) =>
              void run(async () => {
                for (const entry of entries) await api.delete(`${base}/entries/${entry.id}`);
              })
            }
            onGenerate={() => router.push(generateHref(active))}
            onFill={kind === 'character' ? () => setFillOpen(true) : undefined}
          />
        ) : null}
      </div>
      {kind === 'character' && active && fillOpen ? (
        <LookFillDialog
          characterId={card.id}
          look={active}
          open={fillOpen}
          onClose={() => setFillOpen(false)}
          onProgress={() => void run(() => Promise.resolve())}
        />
      ) : null}
      {kind === 'scene' ? (
        <SceneMatrixDialog
          sceneId={card.id}
          open={matrixOpen}
          onClose={() => setMatrixOpen(false)}
          onProgress={() => void run(() => Promise.resolve())}
        />
      ) : null}
    </section>
  );
}

function VariantPanel({
  kind,
  variant,
  variants,
  anchorEntryId,
  entryTypes,
  onUpdate,
  onDelete,
  onUpload,
  onEntryUpdate,
  onEntryDelete,
  onAnchor,
  onApprove,
  onClearCandidates,
  onGenerate,
  onFill,
}: {
  kind: CardKind;
  variant: AssetVariant;
  variants: AssetVariant[];
  anchorEntryId: string | null | undefined;
  entryTypes: AssetEntryType[];
  onUpdate: (body: Record<string, unknown>) => void;
  onDelete: () => void;
  onUpload: (file: File, entryType?: AssetEntryType) => void;
  onEntryUpdate: (entry: AssetEntry, body: Record<string, unknown>) => void;
  onEntryDelete: (entry: AssetEntry) => void;
  onAnchor: (entry: AssetEntry) => void;
  onApprove: (entry: AssetEntry) => void;
  onClearCandidates: (entries: AssetEntry[]) => void;
  onGenerate: () => void;
  /** Characters: open 补齐缺失 for this look. */
  onFill?: () => void;
}) {
  const t = useTranslations('assetVariants');
  const tPresets = useTranslations('remixPage');
  const [clearing, setClearing] = useState<AssetEntry[] | null>(null);
  const groups = groupEntries(kind, variant.entries ?? []);
  const [name, setName] = useState(variant.name);
  const [description, setDescription] = useState(variant.description ?? '');
  const presets = (variant.presets ?? {}) as ScenePresets;
  const dirty = name.trim() !== variant.name || description !== (variant.description ?? '');

  return (
    <div className="flex flex-col gap-3">
      <TextInput
        label={t('name')}
        value={name}
        maxLength={40}
        onChange={(event) => setName(event.target.value)}
      />
      <TextArea
        label={t(kind === 'character' ? 'lookDescription' : 'variantDescription')}
        value={description}
        maxLength={2000}
        onChange={(event) => setDescription(event.target.value)}
        className="min-h-20"
      />
      {kind === 'character' ? (
        <Select
          label={t('ageStageLabel')}
          hint={t('ageStageHint')}
          value={(variant.presets as { age_stage?: string } | undefined)?.age_stage ?? ''}
          onChange={(event) => onUpdate({ presets: { age_stage: event.target.value || null } })}
          options={[
            { value: '', label: t('ageStageNone') },
            ...keysOf(AGE_STAGES).map((key) => ({
              value: key,
              label: t(AGE_STAGES[key].labelKey),
            })),
          ]}
        />
      ) : null}
      {kind === 'scene' ? (
        <div className="grid grid-cols-2 gap-2">
          {PRESET_AXES.map(({ axis, table }) => (
            <Select
              key={axis}
              label={tPresets(`presets.axis${axis[0]?.toUpperCase()}${axis.slice(1)}`)}
              value={presets[axis] ?? ''}
              onChange={(event) =>
                onUpdate({ presets: { ...presets, [axis]: event.target.value || null } })
              }
              options={[
                { value: '', label: tPresets('presets.none') },
                ...Object.entries(table).map(([key, entry]) => ({
                  value: key,
                  label: tPresets(`presets.${entry.labelKey}`),
                })),
              ]}
            />
          ))}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={!dirty || !name.trim()}
          onClick={() => onUpdate({ name: name.trim(), description })}
        >
          {t('save')}
        </Button>
        {!variant.is_default ? (
          <>
            <Button size="sm" variant="secondary" onClick={() => onUpdate({ make_default: true })}>
              {t('makeDefault')}
            </Button>
            <Button size="sm" variant="danger" onClick={onDelete}>
              {t(kind === 'character' ? 'deleteLook' : 'deleteVariant')}
            </Button>
          </>
        ) : null}
        <Button
          size="sm"
          variant="secondary"
          icon={<IconSparkle className="size-3.5" />}
          onClick={onGenerate}
        >
          {t('generateHere')}
        </Button>
        {onFill ? (
          <Button
            size="sm"
            variant="secondary"
            icon={<IconSparkle className="size-3.5" />}
            onClick={onFill}
          >
            {t('fillOpen')}
          </Button>
        ) : null}
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-[var(--radius-sm)] border border-border px-2.5 py-1.5 text-xs text-muted hover:text-text">
          <IconUpload className="size-3.5" />
          {t('upload')}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onUpload(file);
              event.target.value = '';
            }}
          />
        </label>
        {kind === 'character' && !variant.is_default ? (
          <label
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-[var(--radius-sm)] border border-border px-2.5 py-1.5 text-xs text-muted hover:text-text"
            title={t('uploadOutfitHint')}
          >
            <IconUpload className="size-3.5" />
            {t('uploadOutfit')}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onUpload(file, 'outfit_detail');
                event.target.value = '';
              }}
            />
          </label>
        ) : null}
      </div>

      {groups.length === 0 ? (
        <p className="text-xs text-muted">{t('emptyVariant')}</p>
      ) : (
        groups.map((group) => (
          <section key={group.key} className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-xs font-semibold text-muted">{t(`group.${group.key}`)}</h3>
              {group.candidates ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setClearing(group.entries.filter((entry) => entry.status === 'candidate'))
                  }
                >
                  {t('clearCandidates', { count: group.candidates })}
                </Button>
              ) : null}
            </div>
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {group.entries.map((entry) => (
                <EntryCard
                  key={entry.id}
                  entry={entry}
                  variant={variant}
                  variants={variants}
                  isAnchor={entry.id === anchorEntryId}
                  entryTypes={entryTypes}
                  onUpdate={(body) => onEntryUpdate(entry, body)}
                  onDelete={() => onEntryDelete(entry)}
                  onAnchor={() => onAnchor(entry)}
                  onApprove={() => onApprove(entry)}
                />
              ))}
            </ul>
          </section>
        ))
      )}

      <ConfirmDialog
        open={clearing !== null}
        onClose={() => setClearing(null)}
        title={t('clearCandidatesTitle', { count: clearing?.length ?? 0 })}
        description={t('clearCandidatesHint')}
        confirmLabel={t('clearCandidatesConfirm')}
        cancelLabel={t('cancel')}
        onConfirm={() => {
          if (clearing) onClearCandidates(clearing);
          setClearing(null);
        }}
      />
    </div>
  );
}
