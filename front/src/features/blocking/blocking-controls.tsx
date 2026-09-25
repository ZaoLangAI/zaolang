'use client';

import { useTranslations } from 'next-intl';

import { Button, IconButton } from '@/components/ui/button';
import {
  IconEye,
  IconEyeOff,
  IconGear,
  IconPause,
  IconPlay,
  IconRefresh,
} from '@/components/ui/icons';
import { cn } from '@/lib/cn';

import { usePlayerClock } from './blocking-viewport';
import type { Timeline } from './compiler/compile';
import type { BlockingPlayer, ViewMode } from './engine/player';
import { castColor } from './palette';
import type { BlockingDocument, BlockingSegment } from './types';
import type { SaveStatus } from './use-blocking-save';
import { CAMERA_MOVES, SHOT_SIZES } from './vocabulary';

export function formatClock(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, '0')}`;
}

export function TransportBar({
  player,
  duration,
  view,
  onViewChange,
  labelsVisible,
  onLabelsChange,
  onOpenSettings,
  disabled,
  saveStatus = 'idle',
}: {
  player: BlockingPlayer | null;
  duration: number;
  view: ViewMode;
  onViewChange: (view: ViewMode) => void;
  labelsVisible: boolean;
  onLabelsChange: (visible: boolean) => void;
  onOpenSettings: () => void;
  disabled: boolean;
  saveStatus?: SaveStatus;
}) {
  const t = useTranslations('blockingStudio');
  const { time, playing } = usePlayerClock(player);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <IconButton
        variant="secondary"
        size="md"
        label={playing ? t('pause') : t('play')}
        disabled={disabled || !player}
        onClick={() => (playing ? player?.pause() : player?.play())}
      >
        {playing ? <IconPause className="size-4" /> : <IconPlay className="size-4" />}
      </IconButton>
      <span className="min-w-28 font-mono text-sm tabular-nums text-muted" aria-live="off">
        {formatClock(time)} / {formatClock(duration)}
      </span>
      {saveStatus !== 'idle' ? (
        <span
          role="status"
          className={cn('text-xs', saveStatus === 'error' ? 'text-danger' : 'text-muted')}
        >
          {t(`saveStatus.${saveStatus}`)}
        </span>
      ) : null}
      <div
        role="radiogroup"
        aria-label={t('viewLabel')}
        className="ml-auto flex rounded-[var(--radius-sm)] border border-border bg-surface-soft p-0.5"
      >
        {(['director', 'free'] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={view === mode}
            disabled={disabled}
            onClick={() => onViewChange(mode)}
            className={cn(
              'h-8 rounded-[calc(var(--radius-sm)-2px)] px-3 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-60',
              view === mode ? 'bg-primary/15 text-text' : 'text-muted hover:text-text',
            )}
          >
            {mode === 'director' ? t('viewDirector') : t('viewFree')}
          </button>
        ))}
      </div>
      <IconButton
        variant="ghost"
        size="md"
        label={labelsVisible ? t('hideLabels') : t('showLabels')}
        onClick={() => onLabelsChange(!labelsVisible)}
      >
        {labelsVisible ? <IconEye className="size-4" /> : <IconEyeOff className="size-4" />}
      </IconButton>
      <IconButton
        variant="ghost"
        size="md"
        label={t('settings')}
        disabled={disabled}
        onClick={onOpenSettings}
      >
        <IconGear className="size-4" />
      </IconButton>
    </div>
  );
}

export function SegmentScrubber({
  player,
  timeline,
  staleKeys,
  disabled,
}: {
  player: BlockingPlayer | null;
  timeline: Timeline | null;
  staleKeys: ReadonlySet<string>;
  disabled: boolean;
}) {
  const t = useTranslations('blockingStudio');
  const { time } = usePlayerClock(player);
  const duration = timeline?.duration ?? 0;
  if (!timeline || duration <= 0) return null;
  const progress = Math.min(1, time / duration);

  const seekFromPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const u = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
    player?.seek(u * duration);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label={t('scrubberLabel')}
        aria-valuemin={0}
        aria-valuemax={Math.round(duration * 10) / 10}
        aria-valuenow={Math.round(time * 10) / 10}
        aria-valuetext={formatClock(time)}
        aria-disabled={disabled || undefined}
        className="relative flex h-12 w-full cursor-pointer select-none overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface-soft focus-visible:outline-2 focus-visible:outline-focus aria-disabled:cursor-not-allowed"
        onPointerDown={(event) => {
          if (disabled) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          player?.pause();
          seekFromPointer(event);
        }}
        onPointerMove={(event) => {
          if (disabled || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
          seekFromPointer(event);
        }}
        onKeyDown={(event) => {
          if (disabled) return;
          const step = event.shiftKey ? 1 : 0.2;
          if (event.key === 'ArrowRight') player?.seek(time + step);
          else if (event.key === 'ArrowLeft') player?.seek(time - step);
          else if (event.key === 'Home') player?.seek(0);
          else if (event.key === 'End') player?.seek(duration);
          else if (event.key === ' ') {
            event.preventDefault();
            if (player?.playing) player.pause();
            else player?.play();
          } else return;
          event.preventDefault();
        }}
      >
        {timeline.segments.map((segment) => {
          const active = time >= segment.start && time < segment.start + segment.duration;
          const stale = staleKeys.has(segment.key);
          return (
            <div
              key={segment.key}
              className={cn(
                'relative flex min-w-0 flex-col justify-center border-r border-border px-2 text-left last:border-r-0',
                active ? 'bg-primary/10' : '',
              )}
              style={{ flexGrow: segment.duration, flexBasis: 0 }}
              title={segment.key}
            >
              <span className="truncate text-[11px] font-medium text-text">
                {t('segmentShort', { index: segment.index + 1 })} · {segment.duration}s
              </span>
              <span className="truncate text-[10px] text-muted">{segment.heading}</span>
              {stale ? (
                <span
                  className="absolute right-1 top-1 size-1.5 rounded-full bg-amber"
                  aria-label={t('segmentStale')}
                />
              ) : null}
            </div>
          );
        })}
        <div
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-primary"
          style={{ left: `calc(${progress * 100}% - 1px)` }}
          aria-hidden
        />
      </div>
    </div>
  );
}

export function SegmentInspector({
  player,
  document,
}: {
  player: BlockingPlayer | null;
  document: BlockingDocument | null;
}) {
  const t = useTranslations('blockingStudio');
  const { frame } = usePlayerClock(player);
  const segment: BlockingSegment | undefined = frame?.segment.source;
  if (!segment || !document) return null;
  const castById = new Map((document.cast ?? []).map((member) => [member.id, member]));
  const shot = segment.shot;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted">
      <span className="font-medium text-text">
        {t('segmentLong', { index: (frame?.segment.index ?? 0) + 1, heading: segment.heading })}
      </span>
      <span>
        {segment.camera_override
          ? t('manualCamera')
          : t('shotSummary', {
              size: t(`vocab.${SHOT_SIZES[shot.size].labelKey}`),
              move: t(`vocab.${CAMERA_MOVES[shot.move.preset].labelKey}`),
              lens: shot.lens_mm,
            })}
      </span>
      <span className="flex items-center gap-2">
        {(segment.start ?? []).length === 0 ? t('noCast') : null}
        {(segment.start ?? []).map((entry) => {
          const member = castById.get(entry.cast_id);
          if (!member) return null;
          return (
            <span key={entry.cast_id} className="inline-flex items-center gap-1">
              <span
                className="size-2.5 rounded-full"
                style={{ backgroundColor: castColor(member.color_index).css }}
                aria-hidden
              />
              {member.name}
            </span>
          );
        })}
      </span>
    </div>
  );
}

export function StaleBanner({
  count,
  onRebuild,
  disabled,
}: {
  count: number;
  onRebuild: () => void;
  disabled: boolean;
}) {
  const t = useTranslations('blockingStudio');
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-[var(--radius-sm)] border border-amber/40 bg-amber/10 px-3 py-2 text-sm text-text"
    >
      <span className="min-w-0 flex-1">{t('staleTitle', { count })}</span>
      <Button
        size="sm"
        variant="secondary"
        icon={<IconRefresh className="size-4" />}
        disabled={disabled}
        onClick={onRebuild}
      >
        {t('rebuild')}
      </Button>
    </div>
  );
}
