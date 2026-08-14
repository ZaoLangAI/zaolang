'use client';

import { useEffect, useRef, useState } from 'react';

import { api, buildUrl, getAccessToken, refreshAccessToken } from '@/lib/api/client';
import type { GenerationJob, JobEvent, JobStatus } from '@/lib/api/types';

const TERMINAL_STATUSES = ['succeeded', 'failed', 'cancelled', 'expired'] as const;
const DETAIL_POLL_MS = 5_000;

function isTerminal(status: string): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(status);
}

/**
 * The stream carries the same shape as a `JobEvent`, except that the timestamp
 * is only assigned when the row is written, so a live frame may not have one.
 */
export type StreamedEvent = Omit<JobEvent, 'created_at'> & {
  status: JobStatus;
  created_at?: string;
  cancel_requested?: boolean;
};

export interface JobStreamState {
  job: GenerationJob | null;
  events: StreamedEvent[];
  connected: boolean;
  /** True while a dropped stream is being re-established. */
  reconnecting: boolean;
  applyJob: (next: GenerationJob) => void;
}

/**
 * Live progress for one generation job.
 *
 * Uses `fetch` with a streamed body rather than `EventSource`, because the API
 * authenticates with a bearer token and `EventSource` cannot send headers.
 * Doing it by hand also lets us resume with `Last-Event-ID`, which is what
 * guarantees no progress step is lost across a reconnect.
 *
 * SSE can miss a Redis pub/sub frame while the connection stays open, so we
 * also poll GET `/generation-jobs/{id}` every 5s (same source of truth as the
 * admin stream) until the job reaches a terminal status.
 */
export function useJobStream(jobId: string, initial: GenerationJob | null): JobStreamState {
  const [job, setJob] = useState<GenerationJob | null>(initial);
  const [events, setEvents] = useState<StreamedEvent[]>(initial?.events ?? []);
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  // Survives re-renders and reconnects so a resumed stream never replays.
  const lastEventId = useRef<number>(
    initial?.events?.reduce((max, event) => Math.max(max, event.sequence), 0) ?? 0,
  );

  useEffect(() => {
    if (initial && isTerminal(initial.status)) return;

    const controller = new AbortController();
    let attempt = 0;
    let stopped = false;

    const rememberSequences = (incoming: StreamedEvent[]) => {
      if (incoming.length === 0) return;
      lastEventId.current = Math.max(
        lastEventId.current,
        ...incoming.map((event) => event.sequence),
      );
    };

    const applyLatest = (latest: GenerationJob) => {
      setJob(latest);
      if (!latest.events?.length) return;
      setEvents((current) => mergeEvents(current, latest.events ?? []));
      rememberSequences(latest.events);
    };

    const refreshJob = async () => {
      try {
        const latest = await api.get<GenerationJob>(`/v1/generation-jobs/${jobId}`);
        applyLatest(latest);
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
        const latest = await refreshJob();
        if (latest && isTerminal(latest.status)) halt();
      })();
    }, DETAIL_POLL_MS);

    const run = async () => {
      while (!stopped) {
        try {
          const token = getAccessToken() ?? (await refreshAccessToken());
          const response = await fetch(buildUrl(`/v1/generation-jobs/${jobId}/events`), {
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

            // SSE frames are separated by a blank line; anything after the last
            // one is a partial frame that has to wait for the next chunk.
            const frames = buffer.split('\n\n');
            buffer = frames.pop() ?? '';

            for (const frame of frames) {
              const payload = parseFrame(frame);
              if (!payload) continue;
              const stale = payload.sequence < lastEventId.current;
              lastEventId.current = Math.max(lastEventId.current, payload.sequence);
              setEvents((current) => mergeEvents(current, [payload]));
              if (!stale) {
                setJob((current) => patchJobFromEvent(current, payload));
              }
              if (isTerminal(payload.status)) {
                halt();
                // The stream carries progress only; the terminal record has the
                // settled credits and the output, so re-read it once.
                await refreshJob();
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

        // Back off, but never so far that a finished job goes unnoticed.
        attempt += 1;
        const delay = Math.min(1000 * 2 ** (attempt - 1), 15_000);
        await new Promise((resolve) => setTimeout(resolve, delay));

        const latest = await refreshJob();
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
  }, [jobId, initial]);

  const applyJob = (next: GenerationJob) => {
    setJob(next);
    if (!next.events?.length) return;
    setEvents((current) => mergeEvents(current, next.events ?? []));
    lastEventId.current = Math.max(
      lastEventId.current,
      ...next.events.map((event) => event.sequence),
    );
  };

  return { job, events, connected, reconnecting, applyJob };
}

function patchJobFromEvent(
  current: GenerationJob | null,
  payload: StreamedEvent,
): GenerationJob | null {
  if (!current) return current;
  const nextProgress = Math.max(current.progress, payload.progress);
  return {
    ...current,
    status: isTerminal(current.status) ? current.status : payload.status,
    progress: isTerminal(payload.status) ? 100 : nextProgress,
    cancel_requested:
      payload.cancel_requested === true ||
      payload.status === 'cancelled' ||
      current.cancel_requested,
  };
}

function mergeEvents(current: StreamedEvent[], incoming: StreamedEvent[]): StreamedEvent[] {
  const bySequence = new Map<number, StreamedEvent>();
  for (const event of current) bySequence.set(event.sequence, event);
  for (const event of incoming) {
    const existing = bySequence.get(event.sequence);
    bySequence.set(event.sequence, existing ? { ...existing, ...event } : event);
  }
  return [...bySequence.values()].sort((left, right) => left.sequence - right.sequence);
}

function parseFrame(frame: string): StreamedEvent | null {
  const data = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
    .join('');
  if (!data) return null;
  try {
    return JSON.parse(data) as StreamedEvent;
  } catch {
    return null;
  }
}
