'use client';

import { useTranslations } from 'next-intl';
import { useId } from 'react';

import { OptionGroup } from '@/components/studio/option-group';
import {
  CHARACTER_EXPRESSIONS,
  type CharacterExpression,
  keysOf,
  MAX_CHARACTER_EXPRESSIONS,
  MAX_OUTFIT_LABEL_LENGTH,
  MAX_SCENE_VARIANTS,
  MIN_SCENE_VARIANTS,
  SCENE_LIGHTINGS,
  SCENE_PERIODS,
  SCENE_STATES,
  SCENE_WEATHERS,
  type ScenePresetCombo,
  type ScenePresets,
} from '@/features/image-assets/vocabulary';
import { cn } from '@/lib/cn';

type Axis = keyof ScenePresets;

const AXES: { axis: Axis; table: Record<string, { labelKey: string }>; labelKey: string }[] = [
  { axis: 'lighting', table: SCENE_LIGHTINGS, labelKey: 'presets.axisLighting' },
  { axis: 'weather', table: SCENE_WEATHERS, labelKey: 'presets.axisWeather' },
  { axis: 'state', table: SCENE_STATES, labelKey: 'presets.axisState' },
  { axis: 'period', table: SCENE_PERIODS, labelKey: 'presets.axisPeriod' },
];

/** Multi-select chips — a checkbox group styled like `OptionGroup`. */
export function ChipGroup<T extends string>({
  label,
  options,
  selected,
  onToggle,
  max,
}: {
  label: string;
  options: { value: T; label: string }[];
  selected: T[];
  onToggle: (value: T) => void;
  max: number;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-xs text-muted">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => {
          const checked = selected.includes(option.value);
          const disabled = !checked && selected.length >= max;
          return (
            <label
              key={option.value}
              className={cn(
                'cursor-pointer rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-xs transition-colors',
                'focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--focus)]',
                checked
                  ? 'border-primary bg-primary/10 text-text'
                  : 'border-border text-muted hover:border-border-strong hover:text-text',
                disabled && 'cursor-not-allowed opacity-50',
              )}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={checked}
                disabled={disabled}
                onChange={() => onToggle(option.value)}
              />
              {option.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/**
 * Character-image extras: the identity portrait (定妆照 — one clean
 * head-and-shoulders face that becomes the card's anchor), a composite
 * expression image (pick 1–9 expressions → one grid) or a named outfit for
 * a new sheet. All three are mutually exclusive (`GenerationParams`):
 * turning one on clears and disables the others.
 */
export function CharacterPresetFields({
  portrait,
  onPortraitChange,
  expressions,
  onExpressionsChange,
  outfitLabel,
  onOutfitLabelChange,
  outfitDisabled = false,
}: {
  portrait: boolean;
  onPortraitChange: (next: boolean) => void;
  expressions: CharacterExpression[];
  onExpressionsChange: (next: CharacterExpression[]) => void;
  outfitLabel: string;
  onOutfitLabelChange: (next: string) => void;
  /** A target look is picked — the output already has a home. */
  outfitDisabled?: boolean;
}) {
  const t = useTranslations('remixPage');
  const outfitId = useId();
  const portraitId = useId();
  const toggle = (value: CharacterExpression) => {
    const next = expressions.includes(value)
      ? expressions.filter((item) => item !== value)
      : [...expressions, value];
    onExpressionsChange(next);
    if (next.length > 0) onOutfitLabelChange('');
  };
  return (
    <div className="flex flex-col gap-2 border-t border-border pt-3">
      <label htmlFor={portraitId} className="flex items-center gap-2 text-sm text-text">
        <input
          id={portraitId}
          type="checkbox"
          checked={portrait}
          onChange={(event) => {
            onPortraitChange(event.target.checked);
            if (event.target.checked) {
              onExpressionsChange([]);
              onOutfitLabelChange('');
            }
          }}
        />
        {t('presets.portraitLabel')}
      </label>
      <p className="text-[11px] text-muted">{t('presets.portraitHint')}</p>
      {portrait ? null : (
        <>
          <ChipGroup
            label={t('presets.expressionsLabel')}
            options={keysOf(CHARACTER_EXPRESSIONS).map((key) => ({
              value: key,
              label: t(`presets.${CHARACTER_EXPRESSIONS[key].labelKey}`),
            }))}
            selected={expressions}
            onToggle={toggle}
            max={MAX_CHARACTER_EXPRESSIONS}
          />
          <p className="text-[11px] text-muted">
            {expressions.length > 0
              ? t('presets.expressionsActiveHint', { count: expressions.length })
              : t('presets.expressionsHint')}
          </p>
          <label htmlFor={outfitId} className="text-xs text-muted">
            {t('presets.outfitLabel')}
          </label>
          <input
            id={outfitId}
            type="text"
            value={outfitLabel}
            maxLength={MAX_OUTFIT_LABEL_LENGTH}
            disabled={expressions.length > 0 || outfitDisabled}
            onChange={(event) => onOutfitLabelChange(event.target.value)}
            placeholder={t('presets.outfitPlaceholder')}
            className="h-9 rounded-[var(--radius-sm)] border border-border bg-transparent px-3 text-sm text-text placeholder:text-muted disabled:opacity-50"
          />
          <p className="text-[11px] text-muted">{t('presets.outfitHint')}</p>
        </>
      )}
    </div>
  );
}

/**
 * Scene-image presets: one value per axis for a single image, or a variant
 * set that varies one axis across 2–4 values — one image per variant,
 * generated one after another in the same job.
 */
export function ScenePresetFields({
  presets,
  onPresetsChange,
  groupAxis,
  onGroupAxisChange,
  groupValues,
  onGroupValuesChange,
}: {
  presets: ScenePresets;
  onPresetsChange: (next: ScenePresets) => void;
  groupAxis: Axis | null;
  onGroupAxisChange: (axis: Axis | null) => void;
  groupValues: string[];
  onGroupValuesChange: (next: string[]) => void;
}) {
  const t = useTranslations('remixPage');
  return (
    <details className="group flex flex-col gap-3 border-t border-border pt-3" open>
      <summary className="cursor-pointer text-xs text-muted">{t('presets.sceneSection')}</summary>
      <div className="mt-2 flex flex-col gap-3">
        {AXES.map(({ axis, table, labelKey }) =>
          groupAxis === axis ? (
            <ChipGroup
              key={axis}
              label={t('presets.groupAxisValues', { axis: t(labelKey) })}
              options={Object.entries(table).map(([key, entry]) => ({
                value: key,
                label: t(`presets.${entry.labelKey}`),
              }))}
              selected={groupValues}
              onToggle={(value) =>
                onGroupValuesChange(
                  groupValues.includes(value)
                    ? groupValues.filter((item) => item !== value)
                    : [...groupValues, value],
                )
              }
              max={MAX_SCENE_VARIANTS}
            />
          ) : (
            <OptionGroup
              key={axis}
              label={t(labelKey)}
              columns={3}
              value={presets[axis] ?? ''}
              onChange={(value) => onPresetsChange({ ...presets, [axis]: value || undefined })}
              options={[
                { value: '', label: t('presets.none') },
                ...Object.entries(table).map(([key, entry]) => ({
                  value: key,
                  label: t(`presets.${entry.labelKey}`),
                })),
              ]}
            />
          ),
        )}
        <p className="text-[11px] text-muted">{t('presets.sceneHint')}</p>
        <div className="flex flex-col gap-2">
          <OptionGroup
            label={t('presets.groupLabel')}
            columns={3}
            value={groupAxis ?? ''}
            onChange={(value) => {
              onGroupAxisChange((value || null) as Axis | null);
              onGroupValuesChange([]);
            }}
            options={[
              { value: '', label: t('presets.groupOff') },
              ...AXES.map(({ axis, labelKey }) => ({ value: axis, label: t(labelKey) })),
            ]}
          />
          <p className="text-[11px] text-muted">
            {groupAxis
              ? t('presets.groupActiveHint', {
                  min: MIN_SCENE_VARIANTS,
                  max: MAX_SCENE_VARIANTS,
                })
              : t('presets.groupHint')}
          </p>
        </div>
      </div>
    </details>
  );
}

/**
 * The `scene_variants` a group submit sends: one combo per picked value on
 * the varied axis, each carrying the fixed values of the other axes. `null`
 * until the group is complete enough to submit.
 */
export function sceneVariantCombos(
  presets: ScenePresets,
  groupAxis: Axis | null,
  groupValues: string[],
): ScenePresetCombo[] | null {
  if (!groupAxis || groupValues.length < MIN_SCENE_VARIANTS) return null;
  const fixed: ScenePresetCombo = {
    lighting: presets.lighting ?? null,
    weather: presets.weather ?? null,
    state: presets.state ?? null,
    period: presets.period ?? null,
  };
  return groupValues
    .slice(0, MAX_SCENE_VARIANTS)
    .map((value) => ({ ...fixed, [groupAxis]: value }) as ScenePresetCombo);
}
