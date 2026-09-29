'use client';

import { useEffect, useRef, useState } from 'react';

import { getAdminToken } from '@/lib/api/admin-client';
import { adminApi } from '@/lib/api/admin-client';
import type { AdminJobDetail } from '@/lib/api/admin-types';
import { buildUrl } from '@/lib/api/client';

const TERMINAL_STATUSES = ['succeeded', 'failed', 'cancelled', 'expired'] as const;
const DETAIL_POLL_MS = 5_000;

function isTerminal(status: string): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(status);
}

export interface AdminStreamedEvent {
  sequence?: number;
  event_type: string;
  status: string;
  progress: number;
  message: string;
  node_id?: string | null;
  thinking?: string;
}

export interface LiveThinking {
  nodeId: string | null;
  text: string;
}

export const EMPTY_LIVE_THINKING: LiveThinking = { nodeId: null, text: '' };

export interface AdminJobStreamState {
  events: AdminStreamedEvent[];
  detail: AdminJobDetail | null;
  connected: boolean;
  reconnecting: boolean;
  liveThinking: LiveThinking;
}

/**
 * Live progress for one admin-visible generation job (sandbox try-it or ops).
 *
 * Mirrors `useJobStream` but talks to `/v1/admin/jobs/{id}/stream` with the
 * console bearer token. GET detail is the source of truth for both in-flight
 * `async_task` and the terminal record (`preview_url`, settled events): SSE
 * can miss a Redis pub/sub frame while the connection stays open, so we also
 * poll the detail every 5s until the job finishes.
 */
export function useAdminJobStream(jobId: string | null): AdminJobStreamState {
  const [events, setEvents] = useState<AdminStreamedEvent[]>([]);
  const [detail, setDetail] = useState<AdminJobDetail | null>(null);
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [liveThinking, setLiveThinking] = useState<LiveThinking>(EMPTY_LIVE_THINKING);
  const lastEventId = useRef(0);

  useEffect(() => {
    // No job: the return below already masks every field, and `run()` resets
    // them all (thinking included) when the next job starts.
    if (!jobId) {
      lastEventId.current = 0;
      return;
    }

    const controller = new AbortController();
    let attempt = 0;
    let stopped = false;
    lastEventId.current = 0;

    const applyDetail = (latest: AdminJobDetail) => {
      setDetail(latest);
      if (!latest.events?.length) return;
      const incoming = latest.events.map(toStreamedEvent);
      setEvents((current) => mergeEvents(current, incoming));
      const sequences = incoming
        .map((event) => event.sequence)
        .filter((sequence): sequence is number => sequence != null);
      if (sequences.length) lastEventId.current = Math.max(lastEventId.current, ...sequences);
    };

    const refreshDetail = async () => {
      try {
        const latest = await adminApi.get<AdminJobDetail>(`/v1/admin/jobs/${jobId}`);
        applyDetail(latest);
        return latest;
      } catch {
        return null;
      }
    };

    const halt = () => {
      stopped = true;
      window.clearInterval(pollTimer);
      controller.abort();
    };

    const pollTimer = window.setInterval(() => {
      if (stopped) return;
      void (async () => {
        const latest = await refreshDetail();
        if (latest && isTerminal(latest.status)) halt();
      })();
    }, DETAIL_POLL_MS);

    const run = async () => {
      // Yield so the reset is not a synchronous setState inside the effect.
      await Promise.resolve();
      if (stopped) return;
      setEvents([]);
      setDetail(null);
      setConnected(false);
      setReconnecting(false);
      setLiveThinking(EMPTY_LIVE_THINKING);

      const initial = await refreshDetail();
      if (initial && isTerminal(initial.status)) {
        halt();
        setConnected(false);
        setReconnecting(false);
        return;
      }

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
              if (payload.event_type === 'thinking') {
                const increment = payload.thinking ?? '';
                const nodeId = payload.node_id ?? null;
                if (increment) {
                  setLiveThinking((current) => {
                    if (current.nodeId && nodeId && current.nodeId !== nodeId) {
                      return { nodeId, text: increment };
                    }
                    return { nodeId: nodeId ?? current.nodeId, text: current.text + increment };
                  });
                }
                continue;
              }
              const sequence = payload.sequence ?? 0;
              lastEventId.current = Math.max(lastEventId.current, sequence);
              setLiveThinking((current) => {
                const nodeId = payload.node_id ?? null;
                if (current.nodeId && nodeId && current.nodeId !== nodeId) {
                  return { nodeId, text: '' };
                }
                return current;
              });
              setEvents((current) =>
                payload.sequence != null &&
                current.some((event) => event.sequence === payload.sequence)
                  ? current
                  : [...current, payload],
              );
              if (isTerminal(payload.status)) {
                halt();
                await refreshDetail();
              } else if (
                payload.status === 'awaiting_input' ||
                payload.event_type === 'generating' ||
                payload.event_type === 'progress'
              ) {
                await refreshDetail();
              }
            }
          }
        } catch (error) {
          if (controller.signal.aborted) {
            setConnected(false);
            setReconnecting(false);
            window.clearInterval(pollTimer);
            return;
          }
          void error;
        }

        if (stopped) break;
        setConnected(false);
        setReconnecting(true);
        attempt += 1;
        const delay = Math.min(1000 * 2 ** (attempt - 1), 15_000);
        await new Promise((resolve) => setTimeout(resolve, delay));
        const latest = await refreshDetail();
        if (latest && isTerminal(latest.status)) {
          halt();
          break;
        }
      }
      window.clearInterval(pollTimer);
      setConnected(false);
      setReconnecting(false);
    };

    void run();
    return () => {
      stopped = true;
      controller.abort();
      window.clearInterval(pollTimer);
    };
  }, [jobId]);

  if (!jobId) {
    return {
      events: [],
      detail: null,
      connected: false,
      reconnecting: false,
      liveThinking: EMPTY_LIVE_THINKING,
    };
  }
  return { events, detail, connected, reconnecting, liveThinking };
}

function toStreamedEvent(event: {
  sequence: number;
  event_type: string;
  status: string;
  progress: number;
  message: string;
  node_id?: string | null;
}): AdminStreamedEvent {
  return {
    sequence: event.sequence,
    event_type: event.event_type,
    status: event.status,
    progress: event.progress,
    message: event.message,
    node_id: event.node_id,
  };
}

function mergeEvents(
  current: AdminStreamedEvent[],
  incoming: AdminStreamedEvent[],
): AdminStreamedEvent[] {
  const bySequence = new Map<number, AdminStreamedEvent>();
  for (const event of current) {
    if (event.sequence == null) continue;
    bySequence.set(event.sequence, event);
  }
  for (const event of incoming) {
    if (event.sequence == null) continue;
    bySequence.set(event.sequence, event);
  }
  return [...bySequence.values()].sort(
    (left, right) => (left.sequence ?? 0) - (right.sequence ?? 0),
  );
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
