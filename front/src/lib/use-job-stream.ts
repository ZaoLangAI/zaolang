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
export type StreamedEvent = Omit<JobEvent, 'created_at' | 'sequence'> & {
  sequence?: number;
  status: JobStatus;
  created_at?: string;
  cancel_requested?: boolean;
  thinking?: string;
};

export interface LiveThinking {
  nodeId: string | null;
  text: string;
}

export const EMPTY_LIVE_THINKING: LiveThinking = { nodeId: null, text: '' };

export interface JobStreamState {
  job: GenerationJob | null;
  events: StreamedEvent[];
  connected: boolean;
  /** True while a dropped stream is being re-established. */
  reconnecting: boolean;
  /** In-flight reasoning for the current node — Redis-only, not backfilled. */
  liveThinking: LiveThinking;
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
  const [liveThinking, setLiveThinking] = useState<LiveThinking>(EMPTY_LIVE_THINKING);

  // Survives re-renders and reconnects so a resumed stream never replays.
  const lastEventId = useRef<number>(
    initial?.events?.reduce((max, event) => Math.max(max, event.sequence), 0) ?? 0,
  );

  // Every existing caller mounts this hook once per job (a new page instance
  // per navigation), so `job`/`events` only ever needed their `useState`
  // initializer. The image studio's inline preview instead keeps one long-
  // lived hook instance and swaps `jobId` in place when the user submits a
  // new iteration or clicks an older version in the history strip — without
  // this reset, the previous job's state (and its `Last-Event-ID` position)
  // would leak into the next one.
  const previousJobId = useRef(jobId);
  useEffect(() => {
    if (previousJobId.current === jobId) return;
    previousJobId.current = jobId;
    setJob(initial);
    setEvents(initial?.events ?? []);
    setLiveThinking(EMPTY_LIVE_THINKING);
    lastEventId.current =
      initial?.events?.reduce((max, event) => Math.max(max, event.sequence ?? 0), 0) ?? 0;
    // `initial` is only meaningful at the moment `jobId` changes — it is not
    // itself a dependency, or a caller passing a fresh object each render
    // (`initial ?? undefined`-style props) would reset state every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  useEffect(() => {
    // An empty id means "nothing selected yet" — the image studio's inline
    // preview calls this hook unconditionally (hooks can't be called
    // conditionally) before a job exists, so this has to be a safe no-op
    // rather than opening a stream against `/generation-jobs//events`.
    if (!jobId) return;
    if (initial && isTerminal(initial.status)) return;

    const controller = new AbortController();
    let attempt = 0;
    let stopped = false;

    const rememberSequences = (incoming: StreamedEvent[]) => {
      const sequences = incoming
        .map((event) => event.sequence)
        .filter((sequence): sequence is number => sequence != null);
      if (sequences.length === 0) return;
      lastEventId.current = Math.max(lastEventId.current, ...sequences);
    };

    const applyLatest = (latest: GenerationJob) => {
      setJob((current) => clampProgress(current, latest));
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
              if (isThinkingFrame(payload)) {
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
              const stale = sequence < lastEventId.current;
              lastEventId.current = Math.max(lastEventId.current, sequence);
              setLiveThinking((current) => {
                const nodeId = payload.node_id ?? null;
                if (current.nodeId && nodeId && current.nodeId !== nodeId) {
                  return { nodeId, text: '' };
                }
                return current;
              });
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
    setJob((current) => clampProgress(current, next));
    if (!next.events?.length) return;
    setEvents((current) => mergeEvents(current, next.events ?? []));
    const sequences = next.events
      .map((event) => event.sequence)
      .filter((sequence): sequence is number => sequence != null);
    if (sequences.length) lastEventId.current = Math.max(lastEventId.current, ...sequences);
  };

  return { job, events, connected, reconnecting, liveThinking, applyJob };
}

/**
 * A multi-view `CHARACTER` job's progress constants restart lower on each
 * loop back through `asset_planning` before the backend's own rescaling (see
 * `zaolang-generation-jobs`) catches up — and a REST re-fetch (unlike the SSE
 * frame path below) has no per-event ordering guarantee to lean on. Once a
 * higher number has been shown, never show a lower one for the same job
 * before it reaches a terminal status.
 */
function clampProgress(current: GenerationJob | null, next: GenerationJob): GenerationJob {
  if (!current || current.id !== next.id || isTerminal(next.status)) return next;
  return { ...next, progress: Math.max(current.progress, next.progress) };
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
  for (const event of current) {
    if (event.sequence == null) continue;
    bySequence.set(event.sequence, event);
  }
  for (const event of incoming) {
    if (event.sequence == null) continue;
    const existing = bySequence.get(event.sequence);
    bySequence.set(event.sequence, existing ? { ...existing, ...event } : event);
  }
  return [...bySequence.values()].sort(
    (left, right) => (left.sequence ?? 0) - (right.sequence ?? 0),
  );
}

type ThinkingFrame = StreamedEvent & { event_type: 'thinking'; thinking?: string };

function isThinkingFrame(payload: StreamedEvent): payload is ThinkingFrame {
  return payload.event_type === 'thinking';
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
