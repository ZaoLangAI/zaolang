'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Badge, type BadgeTone } from '@/components/ui/primitives';

import type { KeyframeBinding } from './script-breakpoint';
import type { BatchItemState } from './use-script-batch';

export interface KeyframeBoardSegment {
  /** Segment key, `{heading}#{ordinal}`. */
  key: string;
  heading: string;
}

type KeyframeStatus = 'confirmed' | 'pending' | 'generating' | 'missing';

const STATUS_KEYS = {
  confirmed: 'keyframeConfirmed',
  pending: 'keyframePending',
  generating: 'keyframeGenerating',
  missing: 'keyframeMissing',
} as const satisfies Record<KeyframeStatus, string>;

const STATUS_TONES: Record<KeyframeStatus, BadgeTone> = {
  confirmed: 'success',
  pending: 'amber',
  generating: 'primary',
  missing: 'neutral',
};

/**
 * The storyboard: one cheap keyframe per segment that has no video yet.
 * Nothing becomes a video's first frame until the author confirms that
 * exact image here (`POST /v1/drafts/{id}/keyframe-confirmation`);
 * regenerating moves the draft to a new version and so un-confirms it.
 */
export function KeyframeBoardDialog({
  open,
  onClose,
  segments,
  keyframes,
  itemFor,
  pendingCount,
  busyKey,
  running,
  onGenerateAll,
  onConfirm,
  onUnconfirm,
  onRegenerate,
}: {
  open: boolean;
  onClose: () => void;
  segments: KeyframeBoardSegment[];
  keyframes: Record<string, KeyframeBinding>;
  itemFor: (key: string) => BatchItemState | null;
  /** Segments with no keyframe draft yet. */
  pendingCount: number;
  busyKey: string | null;
  running: boolean;
  onGenerateAll: () => void;
  onConfirm: (key: string, binding: KeyframeBinding) => void;
  onUnconfirm: (key: string, binding: KeyframeBinding) => void;
  onRegenerate: (key: string, binding: KeyframeBinding) => void;
}) {
  const t = useTranslations('scriptStudio');

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('keyframeBoardTitle')}
      description={t('keyframeBoardHint')}
      size="xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('batchCancel')}
          </Button>
          <Button disabled={running || pendingCount === 0} onClick={onGenerateAll}>
            {t('keyframeGenerateAll', { count: pendingCount })}
          </Button>
        </>
      }
    >
      {segments.length === 0 ? (
        <p className="text-sm text-muted">{t('keyframeEmpty')}</p>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {segments.map((segment, index) => {
            const binding = keyframes[segment.key];
            const item = itemFor(segment.key);
            const generating =
              item?.status === 'queued' || item?.status === 'submitting' || item?.status === 'running';
            const status: KeyframeStatus = generating
              ? 'generating'
              : binding?.confirmed
                ? 'confirmed'
                : binding?.outputUrl
                  ? 'pending'
                  : 'missing';
            return (
              <li
                key={segment.key}
                className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-border bg-surface p-2"
              >
                <div className="aspect-[9/16] overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                  {binding?.outputUrl ? (
                    // A signed media URL; the keyframe is shown as-is, not optimised.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={binding.outputUrl}
                      alt={segment.heading}
                      className="size-full object-cover"
                      loading="lazy"
                    />
                  ) : null}
                </div>
                <div className="flex items-center justify-between gap-1">
                  <span className="min-w-0 truncate text-xs" title={segment.heading}>
                    {index + 1}. {segment.heading}
                  </span>
                  <Badge tone={STATUS_TONES[status]}>{t(STATUS_KEYS[status])}</Badge>
                </div>
                {binding && !generating ? (
                  <div className="flex flex-wrap gap-1">
                    {binding.outputAssetId ? (
                      binding.confirmed ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={busyKey === segment.key}
                          onClick={() => onUnconfirm(segment.key, binding)}
                        >
                          {t('keyframeUnconfirm')}
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          loading={busyKey === segment.key}
                          onClick={() => onConfirm(segment.key, binding)}
                        >
                          {t('keyframeConfirm')}
                        </Button>
                      )
                    ) : null}
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={running}
                      onClick={() => onRegenerate(segment.key, binding)}
                    >
                      {t('keyframeRegenerate')}
                    </Button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Dialog>
  );
}
