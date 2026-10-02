import type { ScriptDocument } from '@/features/script/api';
import { api } from '@/lib/api/client';
import { streamPost } from '@/lib/sse-post';

import type { AspectRatio, BlockingDocument, BlockingState } from './types';

/** Which of a 白膜 turn's model calls the following `delta`/`thinking`
 * frames belong to — see `back/app/api/v1/blocking.py`. */
export type BlockingPhase = 'route' | 'script' | 'blocking';

export interface BlockingTurnCompleteEvent {
  episode_id: string;
  /** `null` for a rebuild, which writes no chat turn. */
  turn_id: string | null;
  turn_no: number;
  summary: string;
  script: ScriptDocument;
  script_changed: boolean;
  blocking: BlockingState;
  degraded: boolean;
  thinking: string;
}

export type BlockingStreamEvent =
  | { event: 'phase'; data: { name: BlockingPhase } }
  | { event: 'delta'; data: { text: string } }
  | { event: 'thinking'; data: { text: string } }
  | { event: 'complete'; data: BlockingTurnCompleteEvent }
  | { event: 'error'; data: { message: string } };

async function* stream(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<BlockingStreamEvent> {
  for await (const frame of streamPost(path, body, signal)) {
    yield frame as BlockingStreamEvent;
  }
}

export function sendBlockingTurn(
  episodeId: string,
  input: { message: string; currentScript: ScriptDocument },
  signal?: AbortSignal,
) {
  return stream(
    `/v1/scripts/${episodeId}/blocking/turns`,
    { message: input.message, current_script: input.currentScript },
    signal,
  );
}

/** First build, or re-staging after the script changed elsewhere. */
export function rebuildBlocking(episodeId: string, signal?: AbortSignal) {
  return stream(`/v1/scripts/${episodeId}/blocking:rebuild`, {}, signal);
}

/** A manual edit (drag, preset pick). 409s when `baseVersionNo` is stale. */
export function patchBlocking(
  episodeId: string,
  document: BlockingDocument,
  baseVersionNo: number,
) {
  return api.patch<BlockingState>(`/v1/scripts/${episodeId}/blocking`, {
    document,
    base_version_no: baseVersionNo,
  });
}

export function updateBlockingSettings(
  episodeId: string,
  input: { targetDurationSeconds: number | null; aspectRatio?: AspectRatio; baseVersionNo: number },
) {
  return api.patch<BlockingState>(`/v1/scripts/${episodeId}/blocking/settings`, {
    target_duration_seconds: input.targetDurationSeconds,
    aspect_ratio: input.aspectRatio,
    base_version_no: input.baseVersionNo,
  });
}
