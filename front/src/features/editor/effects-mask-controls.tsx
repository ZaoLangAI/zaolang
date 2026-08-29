'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';

import type { ClipEffect, ClipMask, EditCommand, EffectType, MaskShape } from './engine/ports';

const EFFECT_TYPES: EffectType[] = ['blur', 'brightness', 'contrast', 'saturate', 'grayscale'];

function defaultParamsFor(type: EffectType): Record<string, number> {
  return type === 'blur' ? { intensity: 15 } : { amount: 100 };
}

function paramKeyFor(type: EffectType): string {
  return type === 'blur' ? 'intensity' : 'amount';
}

function paramRangeFor(type: EffectType): { min: number; max: number; step: number } {
  if (type === 'blur' || type === 'grayscale') return { min: 0, max: 100, step: 1 };
  return { min: 0, max: 200, step: 5 };
}

const MILLI_PER_PERCENT = 10;

function percentToMilli(percent: number): number {
  return Math.round(percent * MILLI_PER_PERCENT);
}

function milliToPercent(milli: number): number {
  return Math.round(milli / MILLI_PER_PERCENT);
}

function defaultMask(shape: MaskShape): ClipMask {
  return {
    shape,
    x_milli: 200,
    y_milli: 200,
    width_milli: 600,
    height_milli: 600,
    feather_millipercent: 5_000,
  };
}

/**
 * Effects list + mask geometry for the selected clip. `blur` alone gets a
 * real GPU pass through the vendored WASM shader when available; every
 * other effect (and masks) always run as a Canvas2D `ctx.filter` — see
 * `engine/effects.ts`. Adapted from OpenCut's effects/mask panels in
 * layout only: this app's server-validated closed effect allowlist and
 * `onCommit`-per-change model replace their local-store editing.
 */
export function EffectsMaskControls({
  elementId,
  initialEffects,
  initialMask,
  disabled,
  onCommit,
}: {
  elementId: string;
  initialEffects: ClipEffect[];
  initialMask: ClipMask | null;
  disabled: boolean;
  onCommit: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const effectLabel: Record<EffectType, string> = {
    blur: t('effectType.blur'),
    brightness: t('effectType.brightness'),
    contrast: t('effectType.contrast'),
    saturate: t('effectType.saturate'),
    grayscale: t('effectType.grayscale'),
  };
  const maskFieldLabel = {
    x_milli: t('maskX'),
    y_milli: t('maskY'),
    width_milli: t('maskWidth'),
    height_milli: t('maskHeight'),
    feather_millipercent: t('maskFeather'),
  } as const;
  const [effects, setEffects] = useState(initialEffects);
  const [mask, setMask] = useState(initialMask);

  const addEffect = (type: EffectType) => {
    const effect: ClipEffect = { type, params: defaultParamsFor(type) };
    setEffects((current) => [...current, effect]);
    onCommit([{ type: 'add_effect', element_id: elementId, effect }]);
  };

  const removeEffect = (index: number) => {
    setEffects((current) => current.filter((_, item) => item !== index));
    onCommit([{ type: 'remove_effect', element_id: elementId, effect_index: index }]);
  };

  const updateEffectParam = (index: number, value: number) => {
    const key = paramKeyFor(effects[index]!.type);
    setEffects((current) =>
      current.map((effect, item) =>
        item === index ? { ...effect, params: { ...effect.params, [key]: value } } : effect,
      ),
    );
  };

  const commitEffectParam = (index: number) => {
    const effect = effects[index];
    if (!effect) return;
    onCommit([
      { type: 'update_effect_params', element_id: elementId, effect_index: index, params: effect.params },
    ]);
  };

  const setMaskShape = (shape: MaskShape | 'none') => {
    const next = shape === 'none' ? null : defaultMask(shape);
    setMask(next);
    onCommit([{ type: 'set_clip_mask', element_id: elementId, mask: next }]);
  };

  const updateMaskField = (field: keyof ClipMask, percent: number) => {
    setMask((current) => (current ? { ...current, [field]: percentToMilli(percent) } : current));
  };

  const commitMask = () => {
    if (mask) onCommit([{ type: 'set_clip_mask', element_id: elementId, mask }]);
  };

  return (
    <div className="flex flex-col gap-4 text-xs text-muted">
      <div className="flex flex-col gap-2">
        <p className="text-sm font-semibold text-fg">{t('effectsTitle')}</p>
        <div className="flex flex-wrap gap-2">
          {EFFECT_TYPES.map((type) => (
            <Button key={type} size="sm" variant="secondary" disabled={disabled} onClick={() => addEffect(type)}>
              {effectLabel[type]}
            </Button>
          ))}
        </div>
        {effects.length === 0 ? (
          <p className="text-xs text-muted">{t('effectsEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {effects.map((effect, index) => {
              const range = paramRangeFor(effect.type);
              const key = paramKeyFor(effect.type);
              const value = effect.params[key] ?? range.min;
              return (
                <li key={`${effect.type}-${index}`} className="flex items-center gap-2">
                  <label className="flex flex-1 flex-col gap-1">
                    {effectLabel[effect.type]} {Math.round(value)}
                    <input
                      type="range"
                      min={range.min}
                      max={range.max}
                      step={range.step}
                      value={value}
                      disabled={disabled}
                      onChange={(event) => updateEffectParam(index, Number(event.target.value))}
                      onPointerUp={() => commitEffectParam(index)}
                      onBlur={() => commitEffectParam(index)}
                      className="w-full accent-primary"
                    />
                  </label>
                  <Button size="sm" variant="ghost" disabled={disabled} onClick={() => removeEffect(index)}>
                    {t('effectRemove')}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-2 border-t border-border pt-3">
        <p className="text-sm font-semibold text-fg">{t('maskTitle')}</p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant={mask === null ? 'primary' : 'secondary'}
            disabled={disabled}
            onClick={() => setMaskShape('none')}
          >
            {t('maskNone')}
          </Button>
          <Button
            size="sm"
            variant={mask?.shape === 'rect' ? 'primary' : 'secondary'}
            disabled={disabled}
            onClick={() => setMaskShape('rect')}
          >
            {t('maskRect')}
          </Button>
          <Button
            size="sm"
            variant={mask?.shape === 'ellipse' ? 'primary' : 'secondary'}
            disabled={disabled}
            onClick={() => setMaskShape('ellipse')}
          >
            {t('maskEllipse')}
          </Button>
        </div>
        {mask ? (
          <div className="grid grid-cols-2 gap-2">
            {(
              [
                'x_milli',
                'y_milli',
                'width_milli',
                'height_milli',
                'feather_millipercent',
              ] as const
            ).map((field) => (
              <label key={field} className="flex flex-col gap-1">
                {maskFieldLabel[field]}
                <input
                  type="number"
                  min={0}
                  max={100}
                  disabled={disabled}
                  value={
                    field === 'feather_millipercent'
                      ? Math.round(mask.feather_millipercent / 1_000)
                      : milliToPercent(mask[field])
                  }
                  onChange={(event) =>
                    updateMaskField(
                      field,
                      field === 'feather_millipercent'
                        ? Number(event.target.value) * 100
                        : Number(event.target.value),
                    )
                  }
                  onBlur={commitMask}
                  className="rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2 py-1 text-fg"
                />
              </label>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
