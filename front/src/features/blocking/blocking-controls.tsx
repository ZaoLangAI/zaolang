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
import type { SaveStatus } from './use-blocking-save';

export function formatClock(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, '0')}`;
}

/** One slim row under the viewport: transport, view, tags, settings, save state. */
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
    <div className="flex items-center gap-1.5 sm:gap-2">
      <IconButton
        variant="primary"
        size="md"
        label={playing ? t('pause') : t('play')}
        disabled={disabled || !player}
        onClick={() => (playing ? player?.pause() : player?.play())}
      >
        {playing ? <IconPause className="size-4" /> : <IconPlay className="size-4" />}
      </IconButton>
      <span
        className="min-w-0 truncate font-mono text-xs tabular-nums text-muted sm:text-sm"
        aria-live="off"
      >
        {formatClock(time)} / {formatClock(duration)}
      </span>
      {saveStatus !== 'idle' ? (
        <span
          role="status"
          className={cn(
            'hidden text-xs sm:inline',
            saveStatus === 'error' ? 'text-danger' : 'text-muted',
          )}
        >
          {t(`saveStatus.${saveStatus}`)}
        </span>
      ) : null}
      <div
        role="radiogroup"
        aria-label={t('viewLabel')}
        className="ml-auto flex shrink-0 rounded-[var(--radius-sm)] border border-border bg-surface-soft p-0.5"
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
              'h-9 rounded-[calc(var(--radius-sm)-2px)] px-2.5 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-60 sm:px-3',
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

/** Segments sized by duration, a tick where each shot inside starts, a
 * playhead; click or drag anywhere to scrub, arrow keys to step. */
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
    <div
      role="slider"
      tabIndex={disabled ? -1 : 0}
      aria-label={t('scrubberLabel')}
      aria-valuemin={0}
      aria-valuemax={Math.round(duration * 10) / 10}
      aria-valuenow={Math.round(time * 10) / 10}
      aria-valuetext={formatClock(time)}
      aria-disabled={disabled || undefined}
      className="relative flex h-11 w-full shrink-0 cursor-pointer touch-none select-none overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface-soft focus-visible:outline-2 focus-visible:outline-focus aria-disabled:cursor-not-allowed"
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
              'relative flex min-w-0 flex-col justify-center border-r border-border px-1.5 text-left last:border-r-0 sm:px-2',
              active ? 'bg-primary/10' : '',
            )}
            style={{ flexGrow: segment.duration, flexBasis: 0 }}
            title={`${segment.key} · ${segment.duration}s`}
          >
            <span className="truncate text-[11px] font-medium text-text">
              {t('segmentShort', { index: segment.index + 1 })}
              <span className="hidden text-muted sm:inline"> · {segment.duration}s</span>
            </span>
            <span className="hidden truncate text-[10px] text-muted sm:block">
              {segment.heading}
            </span>
            {segment.shots.slice(1).map((shot) => (
              <span
                key={shot.index}
                aria-hidden
                className="absolute bottom-0 h-2 w-px bg-muted/70"
                style={{ left: `${(shot.start / segment.duration) * 100}%` }}
              />
            ))}
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
      className="flex shrink-0 flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-amber/40 bg-amber/10 px-3 py-1.5 text-xs text-text sm:text-sm"
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
