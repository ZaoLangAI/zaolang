'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { formatDuration } from '@/lib/format';

import * as editorApi from './api';

/** One hint from the server's post-export health check (`analysis.qa_findings`). */
interface QaFinding {
  code: string;
  severity: 'warning' | 'info';
  at_seconds?: number | null;
  duration_seconds?: number | null;
  value?: number | null;
}

const POLL_MS = 3000;
const MAX_POLLS = 60;
const TERMINAL = new Set(['succeeded', 'failed', 'degraded']);

/**
 * Shows the export's health check (black frames, frozen picture, long
 * silence, loudness, clipping) once the server has run it. Hint-only: the
 * export has already succeeded and nothing here changes it. Polls
 * `GET /v1/editor-operations/{man_…}` until the analysis is terminal.
 */
export function ExportQaPanel({ operationId }: { operationId: string }) {
  const t = useTranslations('editor');
  const [operation, setOperation] = useState<editorApi.EditorOperation | null>(null);

  useEffect(() => {
    let cancelled = false;
    let polls = 0;
    let timer: number | undefined;
    const tick = () => {
      polls += 1;
      void editorApi
        .getOperation(operationId)
        .then((next) => {
          if (cancelled) return;
          setOperation(next);
          if (!TERMINAL.has(next.status) && polls < MAX_POLLS) {
            timer = window.setTimeout(tick, POLL_MS);
          }
        })
        .catch(() => {
          if (!cancelled && polls < MAX_POLLS) timer = window.setTimeout(tick, POLL_MS);
        });
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [operationId]);

  const findingText = (finding: QaFinding): string => {
    const at = formatDuration(finding.at_seconds ?? 0);
    const duration = (finding.duration_seconds ?? 0).toFixed(1);
    const value = (finding.value ?? 0).toFixed(1);
    switch (finding.code) {
      case 'black_frames':
        return t('exportQaBlackFrames', { at, duration });
      case 'frozen_frames':
        return t('exportQaFrozenFrames', { at, duration });
      case 'long_silence':
        return t('exportQaLongSilence', { at, duration });
      case 'no_audio':
        return t('exportQaNoAudio');
      case 'loudness_off_target':
        return t('exportQaLoudness', { value });
      case 'true_peak_clipping':
        return t('exportQaClipping', { value });
      default:
        return finding.code;
    }
  };

  const status = operation?.status ?? 'queued';
  const findings = (operation?.result?.findings as QaFinding[] | undefined) ?? [];

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col gap-1.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft p-2 text-xs"
    >
      <p className="font-medium text-text">{t('exportQaTitle')}</p>
      {!TERMINAL.has(status) ? (
        <p className="text-muted">{t('exportQaRunning')}</p>
      ) : status === 'degraded' ? (
        <p className="text-muted">{t('exportQaDegraded')}</p>
      ) : status === 'failed' ? (
        <p className="text-muted">{t('exportQaFailed')}</p>
      ) : findings.length === 0 ? (
        <p className="text-success">{t('exportQaClean')}</p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {findings.map((finding, index) => (
            <li
              key={`${finding.code}-${index}`}
              className={finding.severity === 'warning' ? 'text-amber' : 'text-muted'}
            >
              {findingText(finding)}
            </li>
          ))}
        </ul>
      )}
      <p className="text-muted">{t('exportQaHint')}</p>
    </div>
  );
}
