'use client';

import { useEffect, useRef, useState } from 'react';

import { getAdminToken } from '@/lib/api/admin-client';
import { adminApi } from '@/lib/api/admin-client';
import type { AdminJobDetail } from '@/lib/api/admin-types';
import { buildUrl } from '@/lib/api/client';

const TERMINAL_STATUSES = ['succeeded', 'failed', 'cancelled', 'expired'] as const;

function isTerminal(status: string): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(status);
}

export interface AdminStreamedEvent {
  sequence: number;
  event_type: string;
  status: string;
  progress: number;
  message: string;
  node_id?: string | null;
}

export interface AdminJobStreamState {
  events: AdminStreamedEvent[];
  detail: AdminJobDetail | null;
  connected: boolean;
  reconnecting: boolean;
}

/**
 * Live progress for one admin-visible generation job (sandbox try-it or ops).
 *
 * Mirrors `useJobStream` but talks to `/v1/admin/jobs/{id}/stream` with the
 * console bearer token. Prompt bodies are not on the wire — `detail` is
 * re-fetched on terminal so the inspector can show I/O and the preview.
 */
export function useAdminJobStream(jobId: string | null): AdminJobStreamState {
  const [events, setEvents] = useState<AdminStreamedEvent[]>([]);
  const [detail, setDetail] = useState<AdminJobDetail | null>(null);
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const lastEventId = useRef(0);

  useEffect(() => {
    if (!jobId) {
      lastEventId.current = 0;
      return;
    }

    const controller = new AbortController();
    let attempt = 0;
    let stopped = false;
    lastEventId.current = 0;

    const refreshDetail = async () => {
      try {
        const latest = await adminApi.get<AdminJobDetail>(`/v1/admin/jobs/${jobId}`);
        setDetail(latest);
        return latest;
      } catch {
        return null;
      }
    };

    const run = async () => {
      // Yield so the reset is not a synchronous setState inside the effect.
      await Promise.resolve();
      if (stopped) return;
      setEvents([]);
      setDetail(null);
      setConnected(false);
      setReconnecting(false);

      while (!stopped) {
        try {
          const token = getAdminToken();
          const response = await fetch(buildUrl(`/v1/admin/jobs/${jobId}/stream`), {
            headers: {
              accept: 'text/event-stream',
              ...(token ? { authorization: `Bearer ${token}` } : {}),
              ...(lastEventId.current ? { 'last-event-id': String(lastEventId.current) } : {}),
            },
            credentials: 'include',
            signal: controller.signal,
          });
          if (!response.ok || !response.body) throw new Error(String(response.status));

          setConnected(true);
          setReconnecting(false);
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
              const payload = parseFrame(frame);
              if (!payload) continue;
              lastEventId.current = Math.max(lastEventId.current, payload.sequence);
              setEvents((current) =>
                current.some((event) => event.sequence === payload.sequence)
                  ? current
                  : [...current, payload],
              );
              if (isTerminal(payload.status)) {
                stopped = true;
                await refreshDetail();
              } else if (payload.status === 'awaiting_input') {
                await refreshDetail();
              }
            }
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          void error;
        }

        if (stopped) break;
        setConnected(false);
        setReconnecting(true);
        attempt += 1;
        const delay = Math.min(1000 * 2 ** (attempt - 1), 15_000);
        await new Promise((resolve) => setTimeout(resolve, delay));
        const latest = await refreshDetail();
        if (latest && isTerminal(latest.status)) break;
      }
      setConnected(false);
      setReconnecting(false);
    };

    void run();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [jobId]);

  if (!jobId) {
    return { events: [], detail: null, connected: false, reconnecting: false };
  }
  return { events, detail, connected, reconnecting };
}

function parseFrame(frame: string): AdminStreamedEvent | null {
  const data = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
    .join('');
  if (!data) return null;
  try {
    return JSON.parse(data) as AdminStreamedEvent;
  } catch {
    return null;
  }
}
