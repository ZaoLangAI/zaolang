'use client';

import { useTranslations } from 'next-intl';
import { useId } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/cn';

import { usePlayerClock } from './blocking-viewport';
import type { BlockingEdit } from './edits';
import type { BlockingPlayer } from './engine/player';
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
  'h-8 min-w-0 rounded-[calc(var(--radius-sm)-2px)] border border-border bg-surface px-2 text-xs text-text focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-60';

function Compact({
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
    <div className={cn('flex min-w-0 items-center gap-1.5', className)}>
      <label htmlFor={id} className="shrink-0 text-xs text-muted">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

/**
 * The camera-move preset library as direct controls for the segment on
 * screen: the same vocabulary the model writes, so a pick here and "改成缓慢
 * 推镜头" in the chat produce the same document. No model call — the edit
 * applies at once and saves like a drag. Kept to one or two compact rows so
 * the viewport above keeps its height.
 */
export function ShotPicker({
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
  const segmentKey = frame?.segment.key;
  const segment = document?.segments?.find((item) => item.key === segmentKey);
  if (!segment || !document) return null;

  const shot = segment.shot;
  const onSet = (segment.start ?? []).map((entry) => entry.cast_id);
  const castName = (id: string) => document.cast?.find((member) => member.id === id)?.name ?? id;
  const update = (patch: Partial<BlockingShot>) => {
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
    onEdit({ kind: 'shot', segmentKey: segment.key, shot: next });
  };
  const vocab = (key: string) => t(`vocab.${key}`);
  const lensOptions = Array.from(new Set([...LENS_PRESETS_MM, shot.lens_mm])).sort((a, b) => a - b);

  return (
    <fieldset
      disabled={disabled}
      className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2"
    >
      <legend className="sr-only">{t('shotPicker')}</legend>
      <Compact label={t('shotSize')}>
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
      </Compact>
      <Compact label={t('shotMove')}>
        {(id) => (
          <select
            id={id}
            className={CONTROL}
            value={shot.move.preset}
            onChange={(event) => {
              const preset = event.target.value as BlockingShot['move']['preset'];
              update({
                move: { ...shot.move, preset, intensity: CAMERA_MOVES[preset].defaultIntensity },
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
      </Compact>
      <Compact label={t('shotIntensity')}>
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
            className="h-8 w-20 accent-primary disabled:opacity-50"
            onChange={(event) =>
              update({ move: { ...shot.move, intensity: Number(event.target.value) } })
            }
          />
        )}
      </Compact>
      <Compact label={t('shotEase')}>
        {(id) => (
          <select
            id={id}
            className={CONTROL}
            value={shot.move.ease}
            onChange={(event) =>
              update({
                move: { ...shot.move, ease: event.target.value as BlockingShot['move']['ease'] },
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
      </Compact>
      <Compact label={t('shotLens')}>
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
      </Compact>
      <Compact label={t('shotHeight')}>
        {(id) => (
          <select
            id={id}
            className={CONTROL}
            value={shot.height}
            onChange={(event) => update({ height: event.target.value as BlockingShot['height'] })}
          >
            {keysOf(CAMERA_HEIGHTS).map((value) => (
              <option key={value} value={value}>
                {vocab(CAMERA_HEIGHTS[value].labelKey)}
              </option>
            ))}
          </select>
        )}
      </Compact>
      <Compact label={t('shotSide')}>
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
      </Compact>
      <Compact label={t('shotSubject')}>
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
      </Compact>
      {segment.camera_override ? (
        <Button
          size="sm"
          variant="secondary"
          className="ml-auto"
          onClick={() =>
            onEdit({ kind: 'camera-override', segmentKey: segment.key, override: null })
          }
        >
          {t('clearManualCamera')}
        </Button>
      ) : null}
    </fieldset>
  );
}
