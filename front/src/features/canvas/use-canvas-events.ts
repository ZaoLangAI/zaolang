'use client';

import { useEffect, useRef } from 'react';

import { buildUrl, getAccessToken, refreshAccessToken } from '@/lib/api/client';

import type { CanvasChange } from './api';

/**
 * Live changes for one open canvas.
 *
 * `fetch` with a streamed body rather than `EventSource`, for the same reason
 * every other stream in this app does it: the API authenticates with a bearer
 * token and `EventSource` cannot send headers.
 *
 * One connection per canvas, never one per generation in flight. The server
 * caps concurrent streams per user at 8, so fanning out over
 * `GET /generation-jobs/{id}/events` would let a four-task Agent run in two
 * tabs consume the whole budget and starve the notification stream.
 */

/** Backoff ceiling. Matches `use-notification-stream.ts` — long enough not to
 * hammer a server that is down, short enough that a canvas left open recovers
 * without a manual reload. */
const MAX_BACKOFF_MS = 15_000;
const BASE_BACKOFF_MS = 1_000;

export interface CanvasEventHandlers {
  /** A batch of changes to fold into the local graph. */
  onChanges: (changes: CanvasChange[], seq: number) => void;
  /** The server cannot reconstruct our cursor — re-read the canvas whole. */
  onGap: () => void;
  /** Backfill finished; everything after this is live. */
  onSynced?: (seq: number) => void;
  onConnectedChange?: (connected: boolean) => void;
}

export function useCanvasEvents(canvasId: string, enabled: boolean, handlers: CanvasEventHandlers) {
  // Held in a ref so a caller passing inline closures — which is the natural
  // way to write this at the call site — does not tear down and reopen the
  // stream on every render of the canvas.
  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  }, [handlers]);

  /** Survives reconnects, which is the whole point of it: the server replays
   * from here rather than resending the canvas. */
  const cursorRef = useRef(0);

  useEffect(() => {
    if (!enabled || !canvasId) return undefined;

    const controller = new AbortController();
    let cancelled = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    /** `stop` means the failure is permanent and retrying cannot fix it. */
    const connect = async (): Promise<'retry' | 'stop'> => {
      if (cancelled) return 'stop';
      const headers: Record<string, string> = { accept: 'text/event-stream' };
      if (cursorRef.current > 0) headers['last-event-id'] = String(cursorRef.current);

      let token = getAccessToken();
      if (!token) token = await refreshAccessToken();
      if (token) headers.authorization = `Bearer ${token}`;

      const response = await fetch(buildUrl(`/v1/canvas-projects/${canvasId}/events`), {
        headers,
        credentials: 'include',
        signal: controller.signal,
      });
      // A 404 here is the canvas being gone or the flag switched off, and a
      // 401 that survived the refresh above is a dead session. Neither is
      // fixed by trying again, so stop rather than reconnecting forever — the
      // caller's own load path surfaces the real error.
      if (response.status === 404 || response.status === 401) return 'stop';
      if (!response.ok || !response.body) throw new Error(`stream failed: ${response.status}`);

      handlersRef.current.onConnectedChange?.(true);
      attempt = 0;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line. Anything after the last
          // separator is a partial frame and stays in the buffer.
          const frames = buffer.split('\n\n');
          buffer = frames.pop() ?? '';

          const batch: CanvasChange[] = [];
          let batchSeq = cursorRef.current;

          for (const frame of frames) {
            const lines = frame.split('\n');
            const eventLine = lines.find((line) => line.startsWith('event: '));
            const dataLine = lines.find((line) => line.startsWith('data: '));
            const idLine = lines.find((line) => line.startsWith('id: '));
            if (!dataLine) continue;

            let payload: unknown;
            try {
              payload = JSON.parse(dataLine.slice('data: '.length));
            } catch {
              continue;
            }

            const name = eventLine?.slice('event: '.length);
            if (name === 'gap') {
              handlersRef.current.onGap();
              // The cursor is worthless now; the caller reloads and re-seeds
              // it. Reconnect from the origin so live updates resume.
              cursorRef.current = 0;
              return 'retry';
            }
            if (name === 'synced') {
              handlersRef.current.onSynced?.(cursorRef.current);
              continue;
            }

            if (idLine) {
              const seq = Number(idLine.slice('id: '.length));
              if (Number.isFinite(seq)) {
                cursorRef.current = seq;
                batchSeq = seq;
              }
            }
            batch.push(payload as CanvasChange);
          }

          // Delivered as one batch per read rather than one callback per frame:
          // a backfill of a hundred changes would otherwise be a hundred React
          // state updates for a single converged result.
          if (batch.length > 0) handlersRef.current.onChanges(batch, batchSeq);
        }
      } finally {
        reader.cancel().catch(() => undefined);
      }
      return 'retry';
    };

    const run = () => {
      connect()
        // A thrown error is a transient one (network drop, 5xx); those are
        // worth retrying, which is exactly what 'retry' means here.
        .catch(() => 'retry' as const)
        .then((outcome) => {
          if (cancelled) return;
          handlersRef.current.onConnectedChange?.(false);
          if (outcome === 'stop') return;
          // The server closes at its own max duration, so a clean end is
          // routine rather than an error — reconnecting after one is normal,
          // and the backoff only grows on repeated failure.
          attempt += 1;
          const delay = Math.min(BASE_BACKOFF_MS * 2 ** (attempt - 1), MAX_BACKOFF_MS);
          timer = setTimeout(run, delay);
        });
    };

    run();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
      handlersRef.current.onConnectedChange?.(false);
    };
  }, [canvasId, enabled]);
}
