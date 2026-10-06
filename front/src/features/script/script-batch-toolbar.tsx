'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { IconImage, IconMic, IconUser, IconVideo, IconWand } from '@/components/ui/icons';

import type { BatchKind } from './use-script-batch';

export function ScriptBatchToolbar({
  characterCount,
  characterPendingCount,
  sceneCount,
  videoCount,
  videoDisabled,
  audioCount,
  disabled,
  running,
  paused,
  progress,
  onOpen,
  onResume,
  onBreakdown,
}: {
  characterCount: number;
  /** Unlinked characters, including library same-name rows the dialog will auto-link. */
  characterPendingCount: number;
  sceneCount: number;
  videoCount: number;
  videoDisabled: boolean;
  /** Dialogue lines with no dubbed `audio_generation` draft yet — see `pendingDialogueLines`. */
  audioCount: number;
  disabled: boolean;
  running: boolean;
  paused: boolean;
  progress: { done: number; total: number } | null;
  onOpen: (kind: BatchKind) => void;
  /** Resumes whichever queue (`videos` or `audio`) was last paused. */
  onResume: () => void;
  /** 拆解建卡 — `AssetBreakdownDialog`. */
  onBreakdown?: () => void;
}) {
  const t = useTranslations('scriptStudio');
  const busy = disabled || running;

  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2.5">
      <p className="text-[11px] font-medium text-muted">{t('batchPipeline')}</p>
      <div className="flex flex-wrap items-center gap-2">
        {onBreakdown ? (
          <Button
            size="sm"
            variant="secondary"
            icon={<IconWand className="size-3.5" />}
            disabled={busy}
            onClick={onBreakdown}
          >
            {t('breakdownAction')}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="secondary"
          icon={<IconUser className="size-3.5" />}
          disabled={busy || characterPendingCount === 0}
          title={characterPendingCount === 0 ? t('batchNothingPending') : undefined}
          onClick={() => onOpen('characters')}
        >
          {t('batchGenerateCharacters', { count: characterCount })}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          icon={<IconImage className="size-3.5" />}
          disabled={busy || sceneCount === 0}
          title={sceneCount === 0 ? t('batchNothingPending') : undefined}
          onClick={() => onOpen('scenes')}
        >
          {t('batchGenerateScenes', { count: sceneCount })}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          icon={<IconVideo className="size-3.5" />}
          disabled={busy || videoDisabled || videoCount === 0}
          title={
            videoDisabled
              ? t('batchVideoDisabledHint')
              : videoCount === 0
                ? t('batchNothingPending')
                : undefined
          }
          onClick={() => onOpen('videos')}
        >
          {t('batchGenerateVideos', { count: videoCount })}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          icon={<IconMic className="size-3.5" />}
          disabled={busy || audioCount === 0}
          title={audioCount === 0 ? t('batchNothingPending') : undefined}
          onClick={() => onOpen('audio')}
        >
          {t('batchGenerateAudio', { count: audioCount })}
        </Button>
        {paused && !running ? (
          <Button size="sm" onClick={onResume}>
            {t('batchRetryAndContinue')}
          </Button>
        ) : null}
      </div>
      {progress && progress.total > 0 ? (
        <p className="text-[11px] text-muted">
          {running || paused
            ? t('batchProgress', { done: progress.done, total: progress.total })
            : null}
          {paused ? ` · ${t('batchPaused')}` : null}
        </p>
      ) : null}
    </div>
  );
}
