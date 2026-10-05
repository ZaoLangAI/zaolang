'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button, IconButton } from '@/components/ui/button';
import { Select, TextInput } from '@/components/ui/field';
import { IconPlus, IconTrash } from '@/components/ui/icons';
import {
  AGE_STAGES,
  keysOf,
  SCENE_PERIODS,
  type ScenePresets,
} from '@/features/image-assets/vocabulary';
import type { AssetVariant, Scene } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

import type { CardKind } from './entry-actions';

/** `asset_variants.service` limits (P3). */
export const LOOK_ATTRIBUTE_LIMITS = { outfit: 20, state: 40, scene_note: 60 } as const;
export const MAX_CUSTOM_ATTRIBUTES = 8;
export const MAX_CUSTOM_KEY_LENGTH = 12;
export const MAX_CUSTOM_VALUE_LENGTH = 40;

/**
 * A look's attributes — the "class rows" of its graph node: age stage and
 * period (enumerated presets), outfit / state / scene note and custom
 * key-values (free text), and the scene card it is set in. A scene variant
 * only has custom key-values here (its four axes are edited beside it).
 * Saves in one PATCH: `presets` (merged into the variant's own),
 * `attributes` (replaces the set) and the scene link.
 */
export function VariantAttributesForm({
  kind,
  variant,
  busy,
  onSave,
}: {
  kind: CardKind;
  variant: AssetVariant;
  busy?: boolean;
  onSave: (body: Record<string, unknown>) => void;
}) {
  const t = useTranslations('assetVariants');
  const tPresets = useTranslations('remixPage');
  const character = kind === 'character';
  const presets = (variant.presets ?? {}) as ScenePresets & { age_stage?: string };
  const attributes = variant.attributes ?? { custom: [] };
  const [ageStage, setAgeStage] = useState(presets.age_stage ?? '');
  const [period, setPeriod] = useState(presets.period ?? '');
  const [outfit, setOutfit] = useState(attributes.outfit ?? '');
  const [state, setState] = useState(attributes.state ?? '');
  const [sceneNote, setSceneNote] = useState(attributes.scene_note ?? '');
  const [custom, setCustom] = useState<CustomRow[]>(attributes.custom ?? []);
  const [sceneId, setSceneId] = useState(variant.scene_link?.scene_id ?? '');
  const [sceneVariantId, setSceneVariantId] = useState(variant.scene_link?.variant_id ?? '');
  const scenes = useResource<Scene[]>(character ? '/v1/scenes' : null);
  const pickedScene = (scenes.data ?? []).find((scene) => scene.id === sceneId);

  const incomplete = customIncomplete(custom);
  const save = () => {
    const rows = custom
      .map((row) => ({ key: row.key.trim(), value: row.value.trim() }))
      .filter((row) => row.key && row.value);
    const body: Record<string, unknown> = {
      attributes: character
        ? {
            outfit: outfit.trim() || null,
            state: state.trim() || null,
            scene_note: sceneNote.trim() || null,
            custom: rows,
          }
        : { custom: rows },
    };
    if (character) {
      body.presets = { age_stage: ageStage || null, period: period || null };
      if (sceneId) {
        body.scene_id = sceneId;
        body.scene_variant_id = sceneVariantId || null;
      } else if (variant.scene_link) {
        body.clear_scene = true;
      }
    }
    onSave(body);
  };

  return (
    <div className="flex flex-col gap-3">
      {character ? (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Select
              label={t('ageStageLabel')}
              value={ageStage}
              onChange={(event) => setAgeStage(event.target.value)}
              options={[
                { value: '', label: t('ageStageNone') },
                ...keysOf(AGE_STAGES).map((key) => ({
                  value: key,
                  label: t(AGE_STAGES[key].labelKey),
                })),
              ]}
            />
            <Select
              label={t('periodLabel')}
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              options={[
                { value: '', label: tPresets('presets.none') },
                ...keysOf(SCENE_PERIODS).map((key) => ({
                  value: key,
                  label: tPresets(`presets.${SCENE_PERIODS[key].labelKey}`),
                })),
              ]}
            />
          </div>
          <p className="-mt-1 text-xs text-muted">{t('ageStageHint')}</p>
          <TextInput
            label={t('outfitLabel')}
            hint={t('outfitHint')}
            value={outfit}
            maxLength={LOOK_ATTRIBUTE_LIMITS.outfit}
            onChange={(event) => setOutfit(event.target.value)}
          />
          <TextInput
            label={t('stateLabel')}
            hint={t('stateHint')}
            value={state}
            maxLength={LOOK_ATTRIBUTE_LIMITS.state}
            onChange={(event) => setState(event.target.value)}
          />
          <TextInput
            label={t('sceneNoteLabel')}
            value={sceneNote}
            maxLength={LOOK_ATTRIBUTE_LIMITS.scene_note}
            onChange={(event) => setSceneNote(event.target.value)}
          />
          <div className="grid grid-cols-2 gap-2">
            <Select
              label={t('sceneLinkLabel')}
              hint={t('sceneLinkHint')}
              value={sceneId}
              onChange={(event) => {
                setSceneId(event.target.value);
                setSceneVariantId('');
              }}
              options={[
                { value: '', label: t('sceneLinkNone') },
                ...(scenes.data ?? []).map((scene) => ({ value: scene.id, label: scene.name })),
                // Keep a linked scene selectable while the list loads.
                ...(variant.scene_link && !scenes.data
                  ? [{ value: variant.scene_link.scene_id, label: variant.scene_link.scene_name }]
                  : []),
              ]}
            />
            {pickedScene && (pickedScene.variants ?? []).length > 1 ? (
              <Select
                label={t('sceneVariantLabel')}
                value={sceneVariantId}
                onChange={(event) => setSceneVariantId(event.target.value)}
                options={[
                  { value: '', label: t('sceneVariantDefault') },
                  ...(pickedScene.variants ?? []).map((item) => ({
                    value: item.id,
                    label: item.name,
                  })),
                ]}
              />
            ) : null}
          </div>
        </>
      ) : null}

      <CustomAttributesEditor rows={custom} onChange={setCustom} />

      <Button size="sm" className="self-start" loading={busy} disabled={incomplete} onClick={save}>
        {t('saveAttributes')}
      </Button>
    </div>
  );
}

export interface CustomRow {
  key: string;
  value: string;
}

/** A row with only one of its two halves filled. */
export function customIncomplete(rows: CustomRow[]): boolean {
  return rows.some((row) => !row.key.trim() !== !row.value.trim());
}

/** Custom key-value attributes (≤ `MAX_CUSTOM_ATTRIBUTES`) — shared by
 * looks / variants and voices. */
export function CustomAttributesEditor({
  rows,
  onChange,
}: {
  rows: CustomRow[];
  onChange: (rows: CustomRow[]) => void;
}) {
  const t = useTranslations('assetVariants');
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-xs font-medium text-muted">{t('customLabel')}</legend>
      {rows.map((row, index) => (
        <div key={index} className="flex items-end gap-2">
          <div className="w-28 shrink-0">
            <TextInput
              label={t('customKey')}
              value={row.key}
              maxLength={MAX_CUSTOM_KEY_LENGTH}
              onChange={(event) =>
                onChange(
                  rows.map((item, i) =>
                    i === index ? { ...item, key: event.target.value } : item,
                  ),
                )
              }
            />
          </div>
          <div className="min-w-0 flex-1">
            <TextInput
              label={t('customValue')}
              value={row.value}
              maxLength={MAX_CUSTOM_VALUE_LENGTH}
              onChange={(event) =>
                onChange(
                  rows.map((item, i) =>
                    i === index ? { ...item, value: event.target.value } : item,
                  ),
                )
              }
            />
          </div>
          <IconButton
            size="sm"
            variant="danger"
            label={t('customRemove')}
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            <IconTrash className="size-4" />
          </IconButton>
        </div>
      ))}
      {rows.length < MAX_CUSTOM_ATTRIBUTES ? (
        <Button
          size="sm"
          variant="ghost"
          className="self-start"
          icon={<IconPlus className="size-3.5" />}
          onClick={() => onChange([...rows, { key: '', value: '' }])}
        >
          {t('customAdd')}
        </Button>
      ) : null}
      {customIncomplete(rows) ? (
        <p className="text-xs text-danger">{t('customIncomplete')}</p>
      ) : null}
    </fieldset>
  );
}
