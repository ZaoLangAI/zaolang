'use client';

import { useEffect, useRef } from 'react';

import { buildUrl, getAccessToken, refreshAccessToken } from '@/lib/api/client';
import type { Notification } from '@/lib/api/types';

const MAX_BACKOFF_MS = 15_000;

/**
 * Live tail of `GET /v1/notifications/stream`.
 *
 * Shaped like `useJobStream`: `fetch` with a streamed body (not `EventSource`,
 * which cannot carry the bearer token), reconnecting with exponential backoff.
 * Unlike a job stream there is no terminal status and no `Last-Event-ID`
 * bookkeeping — the connection is simply held open for the life of the
 * session and reconnected whenever it drops. The onus of staying correct
 * across a dropped connection falls on the REST endpoints the caller already
 * polls once on mount (`GET /notifications/unread-count`, `GET
 * /notifications?limit=5`), not on this stream replaying anything.
 */
export function useNotificationStream(
  enabled: boolean,
  onEvent: (notification: Notification) => void,
): void {
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!enabled) return;

    const controller = new AbortController();
    let stopped = false;
    let attempt = 0;

    const run = async () => {
      while (!stopped) {
        try {
          const token = getAccessToken() ?? (await refreshAccessToken());
          const response = await fetch(buildUrl('/v1/notifications/stream'), {
            headers: {
              accept: 'text/event-stream',
              ...(token ? { authorization: `Bearer ${token}` } : {}),
            },
            credentials: 'include',
            signal: controller.signal,
          });
          if (!response.ok || !response.body) throw new Error(String(response.status));

          attempt = 0;
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';

          while (!stopped) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const frames = buffer.split('\n\n');
            buffer = frames.pop() ?? '';

            for (const frame of frames) {
              const notification = parseFrame(frame);
              if (notification) onEventRef.current(notification);
            }
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          void error;
        }

        if (stopped) break;
        attempt += 1;
        const delay = Math.min(1000 * 2 ** (attempt - 1), MAX_BACKOFF_MS);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    };

    void run();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [enabled]);
}

function parseFrame(frame: string): Notification | null {
  const data = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
    .join('');
  if (!data) return null;
  try {
    return JSON.parse(data) as Notification;
  } catch {
    return null;
  }
}
