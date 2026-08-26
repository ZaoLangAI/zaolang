'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';

import * as editorApi from './api';
import { TICKS_PER_SECOND, type EditCommand } from './engine/ports';

const POLL_INTERVAL_MS = 2_000;

function msToTicks(ms: number): number {
  return Math.round((ms / 1000) * TICKS_PER_SECOND);
}

function secondsLabel(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

interface ReviewSegment {
  start_ms: number;
  end_ms: number;
  text: string;
  included: boolean;
}

/**
 * ASR is never fully accurate, so a transcript never auto-becomes captions —
 * this panel is the mandatory review step between `requestTranscription`
 * (which the AI planner can also trigger via the MCP tool of the same name)
 * and the `insert_caption` batch that actually commits anything. Editing or
 * excluding a segment here is the only way any of it reaches the timeline.
 */
export function TranscriptReviewPanel({
  assetId,
  disabled,
  onApply,
  onClose,
}: {
  assetId: string;
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
  onClose: () => void;
}) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const [status, setStatus] = useState<'starting' | 'pending' | 'ready' | 'failed'>('starting');
  const [segments, setSegments] = useState<ReviewSegment[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const settle = (op: editorApi.EditorOperation) => {
      if (cancelled) return true;
      if (op.status === 'succeeded' || op.status === 'degraded') {
        const raw = op.result?.transcript?.segments ?? [];
        setSegments(raw.map((segment) => ({ ...segment, included: true })));
        setStatus('ready');
        return true;
      }
      if (op.status === 'failed') {
        setStatus('failed');
        setErrorMessage(t('transcribeFailed'));
        return true;
      }
      return false;
    };

    const poll = (operationId: string) => {
      timer = setTimeout(async () => {
        try {
          const op = await editorApi.getOperation(operationId);
          setStatus('pending');
          if (!settle(op)) poll(operationId);
        } catch (error) {
          if (!cancelled) {
            setStatus('failed');
            setErrorMessage(isApiError(error) ? error.message : t('commandFailed'));
          }
        }
      }, POLL_INTERVAL_MS);
    };

    void (async () => {
      try {
        const op = await editorApi.requestTranscription(assetId);
        if (!settle(op)) poll(op.id);
      } catch (error) {
        if (!cancelled) {
          setStatus('failed');
          setErrorMessage(isApiError(error) ? error.message : t('commandFailed'));
        }
      }
    })();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [assetId, t]);

  const toggleSegment = (index: number) => {
    setSegments((current) =>
      current.map((segment, item) =>
        item === index ? { ...segment, included: !segment.included } : segment,
      ),
    );
  };

  const updateSegmentText = (index: number, text: string) => {
    setSegments((current) =>
      current.map((segment, item) => (item === index ? { ...segment, text } : segment)),
    );
  };

  const insertSelected = () => {
    const commands: EditCommand[] = segments
      .filter((segment) => segment.included && segment.text.trim())
      .map((segment) => ({
        type: 'insert_caption',
        track_id: 'trk_caption',
        at_ticks: msToTicks(segment.start_ms),
        duration_ticks: Math.max(1, msToTicks(segment.end_ms - segment.start_ms)),
        text: segment.text.trim(),
      }));
    if (commands.length === 0) return;
    onApply(commands);
    notify(t('transcribeInserted'), 'success');
    onClose();
  };

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3 text-xs">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-fg">{t('transcribeTitle')}</p>
        <Button size="sm" variant="ghost" onClick={onClose}>
          {t('transcribeClose')}
        </Button>
      </div>
      {status === 'starting' || status === 'pending' ? (
        <div className="flex items-center gap-2 text-muted">
          <Spinner label={t('transcribeInProgress')} />
          {t('transcribeInProgress')}
        </div>
      ) : status === 'failed' ? (
        <p className="text-danger">{errorMessage}</p>
      ) : (
        <>
          <p className="text-muted">{t('transcribeReviewHint')}</p>
          <ul className="flex max-h-64 flex-col gap-2 overflow-y-auto">
            {segments.map((segment, index) => (
              <li key={`${segment.start_ms}-${index}`} className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={segment.included}
                  disabled={disabled}
                  onChange={() => toggleSegment(index)}
                  className="mt-1"
                  aria-label={t('transcribeIncludeSegment')}
                />
                <div className="flex flex-1 flex-col gap-1">
                  <span className="text-[10px] text-muted">
                    {secondsLabel(segment.start_ms)} – {secondsLabel(segment.end_ms)}
                  </span>
                  <input
                    type="text"
                    value={segment.text}
                    disabled={disabled || !segment.included}
                    onChange={(event) => updateSegmentText(index, event.target.value)}
                    className="rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2 py-1 text-fg disabled:opacity-50"
                  />
                </div>
              </li>
            ))}
          </ul>
          {segments.length === 0 ? <p className="text-muted">{t('transcribeEmpty')}</p> : null}
          <Button
            size="sm"
            disabled={disabled || !segments.some((segment) => segment.included && segment.text.trim())}
            onClick={insertSelected}
          >
            {t('transcribeInsert')}
          </Button>
        </>
      )}
    </div>
  );
}
