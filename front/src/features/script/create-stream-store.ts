'use client';

import { useSyncExternalStore } from 'react';

import * as scriptApi from './api';
import type { ScriptTurnCompleteEvent } from './api';

export interface CreateStreamState {
  episodeId: string | null;
  streaming: boolean;
  liveText: string;
  error: string | null;
  result: ScriptTurnCompleteEvent | null;
}

const EMPTY_STATE: CreateStreamState = {
  episodeId: null,
  streaming: false,
  liveText: '',
  error: null,
  result: null,
};

/**
 * Module-level singleton, not component state — deliberately outlives
 * whichever component started it. `ScriptLanding` kicks a first-draft
 * stream off and navigates away the instant `episode_id` is known (see
 * `startCreate`'s `onEpisodeReady`), so the fetch reading the SSE body must
 * keep running and updating this store after `ScriptLanding` unmounts;
 * `ScriptEditor` on the destination route picks the same state back up via
 * `useCreateStream`.
 */
let state: CreateStreamState = EMPTY_STATE;
let controller: AbortController | null = null;
const listeners = new Set<() => void>();

function setState(patch: Partial<CreateStreamState>): void {
  state = { ...state, ...patch };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): CreateStreamState {
  return state;
}

function getServerSnapshot(): CreateStreamState {
  return EMPTY_STATE;
}

export interface StartCreateInput {
  title: string;
  idea: string;
  referencedSkillIds: string[];
}

/**
 * Starts a script's first-draft stream. `onEpisodeReady` fires as soon as
 * the `start` SSE frame carries the freshly created `episode_id` — which
 * the backend sends before any LLM token, right after it commits the
 * `Series`/`DramaEpisode` shell (see `create_script` in
 * `back/app/api/v1/scripts.py`) — so the caller can navigate to
 * `/create/script/{episodeId}` immediately instead of waiting for the
 * whole draft to finish streaming.
 */
export function startCreate(
  input: StartCreateInput,
  { onEpisodeReady }: { onEpisodeReady: (episodeId: string) => void },
): void {
  controller?.abort();
  const nextController = new AbortController();
  controller = nextController;
  state = { episodeId: null, streaming: true, liveText: '', error: null, result: null };
  for (const listener of listeners) listener();

  void (async () => {
    try {
      const events = scriptApi.createScript(input, nextController.signal);
      for await (const event of events) {
        if (nextController.signal.aborted) return;
        if (event.event === 'start') {
          setState({ episodeId: event.data.episode_id });
          onEpisodeReady(event.data.episode_id);
        } else if (event.event === 'delta') {
          setState({ liveText: state.liveText + event.data.text });
        } else if (event.event === 'error') {
          setState({ streaming: false, error: event.data.message });
          return;
        } else if (event.event === 'complete') {
          setState({ streaming: false, result: event.data });
          return;
        }
      }
    } catch (error) {
      if (nextController.signal.aborted) return;
      setState({
        streaming: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  })();
}

/**
 * Clears the store once the destination page has consumed a finished
 * `result`/`error` for this episode — otherwise a later "new script" would
 * briefly inherit the previous one's stale `result`.
 */
export function clearCreateStream(episodeId: string): void {
  if (state.episodeId !== episodeId) return;
  state = EMPTY_STATE;
  for (const listener of listeners) listener();
}

/**
 * Reads the shared first-draft stream, scoped to one episode — `null` when
 * the store holds no stream, or one for a different episode, so a page
 * never renders another episode's in-flight generation as its own.
 */
export function useCreateStream(episodeId: string): CreateStreamState | null {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return snapshot.episodeId === episodeId ? snapshot : null;
}

/**
 * Reads the store unscoped — only meaningful for the brief window between a
 * "new script" submit and the `start` frame naming its `episode_id` (before
 * that, `episodeId` is still `null`), which is the one moment `ScriptLanding`
 * itself needs to react to (e.g. a validation error before any episode was
 * even created).
 */
export function useCreateStreamSnapshot(): CreateStreamState {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

/**
 * Drops a stale pre-navigation error/state before starting a fresh attempt
 * (e.g. reopening the "new script" dialog after a previous validation
 * failure). A no-op once the previous attempt actually got an `episodeId` —
 * that stream belongs to the destination page now, not this reset.
 */
export function resetPendingCreate(): void {
  if (state.episodeId !== null) return;
  state = EMPTY_STATE;
  for (const listener of listeners) listener();
}
