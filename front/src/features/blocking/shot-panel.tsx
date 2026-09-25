'use client';

import { useTranslations } from 'next-intl';
import { useId } from 'react';

import { Button } from '@/components/ui/button';
import { IconPlus, IconTrash } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

import { usePlayerClock } from './blocking-viewport';
import type { BlockingEdit } from './edits';
import type { BlockingPlayer } from './engine/player';
import { castColor } from './palette';
import type { BlockingDocument, BlockingShot } from './types';
import {
  CAMERA_HEIGHTS,
  CAMERA_MOVES,
  CAMERA_SIDES,
  LENS_PRESETS_MM,
  MOVE_EASES,
  SHOT_SIZES,
  keysOf,
} from './vocabulary';

const CONTROL =
  'h-10 w-full min-w-0 rounded-[var(--radius-sm)] border border-border bg-surface px-2 text-sm text-text focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-60';

function LabeledField({
  label,
  children,
  className,
}: {
  label: string;
  children: (id: string) => React.ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', className)}>
      <label htmlFor={id} className="text-xs text-muted">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

/**
 * The 镜头 tab: the playing segment's cast and its shot list (click a shot
 * to jump to it), adding a shot at the playhead or removing one, and the
 * current shot's grammar — the same preset vocabulary the model writes, so
 * a pick here and "改成缓慢推镜头" in the chat produce the same document. No
 * model call: edits apply at once and save like a drag.
 */
export function ShotPanel({
  player,
  document,
  disabled,
  onEdit,
}: {
  player: BlockingPlayer | null;
  document: BlockingDocument | null;
  disabled: boolean;
  onEdit: (edit: BlockingEdit) => void;
}) {
  const t = useTranslations('blockingStudio');
  const { frame } = usePlayerClock(player);
  const compiled = frame?.segment;
  const segment = document?.segments?.find((item) => item.key === compiled?.key);
  if (!segment || !compiled || !document) {
    return <p className="p-2 text-sm text-muted">{t('shotPanelEmpty')}</p>;
  }

  const shots = segment.shots ?? [];
  const index = Math.min(frame?.shot?.index ?? 0, Math.max(shots.length - 1, 0));
  const shot = shots[index];
  const castById = new Map((document.cast ?? []).map((member) => [member.id, member]));
  const onSet = (segment.start ?? []).map((entry) => entry.cast_id);
  const castName = (id: string) => castById.get(id)?.name ?? id;
  const vocab = (key: string) => t(`vocab.${key}`);
  const localTime = frame?.localTime ?? 0;

  const update = (patch: Partial<BlockingShot>) => {
    if (!shot) return;
    const next: BlockingShot = { ...shot, ...patch };
    // An over-the-shoulder shot needs someone to look at and someone else's
    // shoulder to look past.
    const ots = next.side === 'ots_left' || next.side === 'ots_right';
    if (ots) {
      if (!next.subject) next.subject = onSet[0] ?? null;
      if (!next.over || next.over === next.subject) {
        next.over = onSet.find((id) => id !== next.subject) ?? null;
      }
      if (!next.over) next.side = 'front';
    } else {
      next.over = null;
    }
    onEdit({ kind: 'shot', segmentKey: segment.key, index, shot: next });
  };
  const lensOptions = shot
    ? Array.from(new Set([...LENS_PRESETS_MM, shot.lens_mm])).sort((a, b) => a - b)
    : [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-text">
          {t('segmentLong', { index: compiled.index + 1, heading: segment.heading })}
          <span className="ml-2 text-xs font-normal text-muted">{segment.duration_s}s</span>
        </p>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          {onSet.length === 0 ? t('noCast') : null}
          {onSet.map((id) => {
            const member = castById.get(id);
            return (
              <span key={id} className="inline-flex items-center gap-1">
                <span
                  className="size-2.5 rounded-full"
                  style={{ backgroundColor: castColor(member?.color_index ?? 0).css }}
                  aria-hidden
                />
                {castName(id)}
              </span>
            );
          })}
        </div>
      </div>

      {segment.camera_override ? (
        <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft p-3 text-sm">
          <p className="text-text">{t('manualCamera')}</p>
          <Button
            size="sm"
            variant="secondary"
            disabled={disabled}
            onClick={() =>
              onEdit({ kind: 'camera-override', segmentKey: segment.key, override: null })
            }
          >
            {t('clearManualCamera')}
          </Button>
        </div>
      ) : null}

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-muted">{t('shotList')}</p>
          <div className="flex gap-1">
            <Button
              size="sm"
              variant="ghost"
              icon={<IconPlus className="size-4" />}
              disabled={disabled}
              onClick={() => onEdit({ kind: 'split-shot', segmentKey: segment.key, at: localTime })}
            >
              {t('shotAdd')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={<IconTrash className="size-4" />}
              disabled={disabled || shots.length <= 1}
              onClick={() => onEdit({ kind: 'remove-shot', segmentKey: segment.key, index })}
            >
              {t('shotRemove')}
            </Button>
          </div>
        </div>
        <ol className="flex flex-col gap-1">
          {shots.map((item, position) => (
            <li key={`${position}-${item.t0}`}>
              <button
                type="button"
                aria-current={position === index ? 'true' : undefined}
                onClick={() => player?.seek(compiled.start + item.t0 + 0.01)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-[var(--radius-sm)] border px-3 py-2 text-left text-sm transition-colors focus-visible:outline-2 focus-visible:outline-focus',
                  position === index
                    ? 'border-primary/40 bg-primary/10 text-text'
                    : 'border-border bg-surface-soft text-text hover:border-border-strong',
                )}
              >
                <span className="shrink-0 font-mono text-xs text-muted">{item.t0.toFixed(1)}s</span>
                <span className="min-w-0 flex-1 truncate">
                  {vocab(SHOT_SIZES[item.size].labelKey)} ·{' '}
                  {vocab(CAMERA_MOVES[item.move.preset].labelKey)}
                  {item.subject ? ` · ${castName(item.subject)}` : ''}
                </span>
                {position > 0 ? (
                  <span className="shrink-0 text-[11px] text-muted">
                    {t(`transition.${item.transition ?? 'cut'}`)}
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ol>
      </div>

      {shot ? (
        <fieldset disabled={disabled} className="grid grid-cols-2 gap-3">
          <legend className="sr-only">{t('shotPicker')}</legend>
          <LabeledField label={t('shotSize')}>
            {(id) => (
              <select
                id={id}
                className={CONTROL}
                value={shot.size}
                onChange={(event) => update({ size: event.target.value as BlockingShot['size'] })}
              >
                {keysOf(SHOT_SIZES).map((value) => (
                  <option key={value} value={value}>
                    {vocab(SHOT_SIZES[value].labelKey)}
                  </option>
                ))}
              </select>
            )}
          </LabeledField>
          <LabeledField label={t('shotMove')}>
            {(id) => (
              <select
                id={id}
                className={CONTROL}
                value={shot.move.preset}
                onChange={(event) => {
                  const preset = event.target.value as BlockingShot['move']['preset'];
                  update({
                    move: {
                      ...shot.move,
                      preset,
                      intensity: CAMERA_MOVES[preset].defaultIntensity,
                    },
                  });
                }}
              >
                {keysOf(CAMERA_MOVES).map((value) => (
                  <option key={value} value={value}>
                    {vocab(CAMERA_MOVES[value].labelKey)}
                  </option>
                ))}
              </select>
            )}
          </LabeledField>
          <LabeledField label={`${t('shotIntensity')} · ${shot.move.intensity.toFixed(1)}`}>
            {(id) => (
              <input
                id={id}
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={shot.move.intensity}
                disabled={disabled || shot.move.preset === 'static'}
                aria-valuetext={shot.move.intensity.toFixed(1)}
                className="h-10 w-full accent-primary disabled:opacity-50"
                onChange={(event) =>
                  update({ move: { ...shot.move, intensity: Number(event.target.value) } })
                }
              />
            )}
          </LabeledField>
          <LabeledField label={t('shotEase')}>
            {(id) => (
              <select
                id={id}
                className={CONTROL}
                value={shot.move.ease}
                onChange={(event) =>
                  update({
                    move: {
                      ...shot.move,
                      ease: event.target.value as BlockingShot['move']['ease'],
                    },
                  })
                }
              >
                {keysOf(MOVE_EASES).map((value) => (
                  <option key={value} value={value}>
                    {vocab(MOVE_EASES[value].labelKey)}
                  </option>
                ))}
              </select>
            )}
          </LabeledField>
          <LabeledField label={t('shotSubject')}>
            {(id) => (
              <select
                id={id}
                className={CONTROL}
                value={shot.subject ?? ''}
                onChange={(event) => update({ subject: event.target.value || null })}
              >
                <option value="">{t('shotSubjectGroup')}</option>
                {onSet.map((castId) => (
                  <option key={castId} value={castId}>
                    {castName(castId)}
                  </option>
                ))}
              </select>
            )}
          </LabeledField>
          <LabeledField label={t('shotSide')}>
            {(id) => (
              <select
                id={id}
                className={CONTROL}
                value={shot.side}
                onChange={(event) => update({ side: event.target.value as BlockingShot['side'] })}
              >
                {keysOf(CAMERA_SIDES).map((value) => (
                  <option
                    key={value}
                    value={value}
                    disabled={value.startsWith('ots') && onSet.length < 2}
                  >
                    {vocab(CAMERA_SIDES[value].labelKey)}
                  </option>
                ))}
              </select>
            )}
          </LabeledField>
          <LabeledField label={t('shotHeight')}>
            {(id) => (
              <select
                id={id}
                className={CONTROL}
                value={shot.height}
                onChange={(event) =>
                  update({ height: event.target.value as BlockingShot['height'] })
                }
              >
                {keysOf(CAMERA_HEIGHTS).map((value) => (
                  <option key={value} value={value}>
                    {vocab(CAMERA_HEIGHTS[value].labelKey)}
                  </option>
                ))}
              </select>
            )}
          </LabeledField>
          <LabeledField label={t('shotLens')}>
            {(id) => (
              <select
                id={id}
                className={CONTROL}
                value={String(shot.lens_mm)}
                onChange={(event) => update({ lens_mm: Number(event.target.value) })}
              >
                {lensOptions.map((value) => (
                  <option key={value} value={String(value)}>
                    {value}mm
                  </option>
                ))}
              </select>
            )}
          </LabeledField>
          {index > 0 ? (
            <LabeledField label={t('shotTransition')} className="col-span-2">
              {(id) => (
                <select
                  id={id}
                  className={CONTROL}
                  value={shot.transition ?? 'cut'}
                  onChange={(event) =>
                    update({ transition: event.target.value as BlockingShot['transition'] })
                  }
                >
                  {(['cut', 'continuous'] as const).map((value) => (
                    <option key={value} value={value}>
                      {t(`transition.${value}`)}
                    </option>
                  ))}
                </select>
              )}
            </LabeledField>
          ) : null}
        </fieldset>
      ) : null}
    </div>
  );
}
