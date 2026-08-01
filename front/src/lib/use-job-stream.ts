'use client';

import { useEffect, useRef, useState } from 'react';

import { api, buildUrl, getAccessToken, refreshAccessToken } from '@/lib/api/client';
import type { GenerationJob, JobEvent, JobStatus } from '@/lib/api/types';

const TERMINAL_STATUSES = ['succeeded', 'failed', 'cancelled', 'expired'] as const;

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
};

export interface JobStreamState {
  job: GenerationJob | null;
  events: StreamedEvent[];
  connected: boolean;
  /** True while a dropped stream is being re-established. */
  reconnecting: boolean;
}

/**
 * Live progress for one generation job.
 *
 * Uses `fetch` with a streamed body rather than `EventSource`, because the API
 * authenticates with a bearer token and `EventSource` cannot send headers.
 * Doing it by hand also lets us resume with `Last-Event-ID`, which is what
 * guarantees no progress step is lost across a reconnect.
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

    const refreshJob = async () => {
      try {
        const latest = await api.get<GenerationJob>(`/v1/generation-jobs/${jobId}`);
        setJob(latest);
        if (latest.events?.length) setEvents(latest.events);
        return latest;
      } catch {
        return null;
      }
    };

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
              lastEventId.current = Math.max(lastEventId.current, payload.sequence);
              setEvents((current) =>
                current.some((event) => event.sequence === payload.sequence)
                  ? current
                  : [...current, payload],
              );
              setJob((current) =>
                current
                  ? { ...current, status: payload.status, progress: payload.progress }
                  : current,
              );
              if (isTerminal(payload.status)) {
                stopped = true;
                // The stream carries progress only; the terminal record has the
                // settled credits and the output, so re-read it once.
                await refreshJob();
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

        // Back off, but never so far that a finished job goes unnoticed.
        attempt += 1;
        const delay = Math.min(1000 * 2 ** (attempt - 1), 15_000);
        await new Promise((resolve) => setTimeout(resolve, delay));

        const latest = await refreshJob();
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
  }, [jobId, initial]);

  return { job, events, connected, reconnecting };
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
