import { api, buildUrl, getAccessToken, newIdempotencyKey, refreshAccessToken } from '@/lib/api/client';
import { ApiError, type ApiErrorBody } from '@/lib/api/errors';

export type ScriptBlockType = 'scene' | 'action' | 'camera' | 'dialogue' | 'breakpoint';

export interface ScriptBlock {
  type: ScriptBlockType;
  character: string | null;
  text: string;
}

export interface ScriptScene {
  heading: string;
  blocks: ScriptBlock[];
  /** Links this heading to a reusable `Scene` asset — set only via
   * `updateScriptLinks`, never by a model turn. */
  ref_id: string | null;
}

export interface ScriptCharacter {
  name: string;
  traits: string;
  /** Links this character to a reusable `Character` asset — set only via
   * `updateScriptLinks`, never by a model turn. */
  character_ref_id: string | null;
}

export interface ScriptDocument {
  title: string;
  logline: string;
  characters: ScriptCharacter[];
  scenes: ScriptScene[];
}

export interface ScriptTurnSummary {
  id: string;
  turn_no: number;
  user_message: string;
  summary: string;
  referenced_skill_ids: string[];
  created_at: string;
}

export interface ScriptSummary {
  episode_id: string;
  title: string;
  logline: string;
  status: string;
  turn_count: number;
  updated_at: string;
}

export interface ScriptDetail {
  episode_id: string;
  series_id: string;
  title: string;
  status: string;
  script: ScriptDocument;
  turns: ScriptTurnSummary[];
}

export interface ScriptTurnSnapshot {
  turn_id: string;
  turn_no: number;
  summary: string;
  script: ScriptDocument;
}

export interface ScriptTurnCompleteEvent {
  episode_id: string;
  turn_id: string;
  turn_no: number;
  summary: string;
  script: ScriptDocument;
  degraded: boolean;
}

export type ScriptStreamEvent =
  | { event: 'start'; data: { episode_id: string } }
  | { event: 'delta'; data: { text: string } }
  | { event: 'complete'; data: ScriptTurnCompleteEvent }
  | { event: 'error'; data: { message: string } };

export function listScripts() {
  return api.get<ScriptSummary[]>('/v1/scripts');
}

export function getScript(episodeId: string) {
  return api.get<ScriptDetail>(`/v1/scripts/${episodeId}`);
}

export function deleteScript(episodeId: string) {
  return api.delete<void>(`/v1/scripts/${episodeId}`);
}

export function getTurnSnapshot(episodeId: string, turnId: string) {
  return api.get<ScriptTurnSnapshot>(`/v1/scripts/${episodeId}/turns/${turnId}/snapshot`);
}

/**
 * Links a character/scene heading to a reusable `Character`/`Scene` asset.
 *
 * Deliberately a plain PATCH, not a chat turn: this is a structural edit the
 * user makes by picking from a list, not a content revision described in
 * words, so it must not spend a model call or create a new turn in the
 * conversation history. Only the names/headings included here are touched —
 * everything else in the document passes through unchanged.
 */
export function updateScriptLinks(
  episodeId: string,
  input: {
    characters?: { name: string; character_ref_id: string | null }[];
    scenes?: { heading: string; ref_id: string | null }[];
  },
) {
  return api.patch<ScriptDocument>(`/v1/scripts/${episodeId}/links`, {
    characters: input.characters ?? [],
    scenes: input.scenes ?? [],
  });
}

/**
 * Persists a hand-edit of the script text (logline, character traits, block
 * text) directly to `episode.script_json` — bypasses the LLM turn machinery,
 * same as `updateScriptLinks` above. Always sends the *entire* document, not
 * a per-field patch, since the backend re-validates/bounds the whole thing
 * through the same sanitizer every LLM-produced script goes through.
 */
export function updateScriptContent(episodeId: string, script: ScriptDocument) {
  return api.patch<ScriptDocument>(`/v1/scripts/${episodeId}`, { script });
}

/**
 * Low-level SSE-over-POST reader.
 *
 * Unlike `useJobStream`'s GET-based long-lived progress feed, one script
 * turn is a single request/response: the whole reply (delta chunks, then a
 * `complete` or `error` frame) arrives on the body of the very `POST` that
 * started it, so there is no resume/reconnect protocol to implement — just
 * read the stream until it ends.
 */
async function* streamPost(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<ScriptStreamEvent> {
  const token = getAccessToken() ?? (await refreshAccessToken());
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    headers: {
      accept: 'text/event-stream',
      'content-type': 'application/json',
      'idempotency-key': newIdempotencyKey(),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    credentials: 'include',
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    // Same envelope `apiRequest` parses for every non-streaming call — a
    // failure here (most commonly the feature flag being off) must surface
    // its `error.message`, not the raw JSON body, in the chat panel.
    const text = await response.text().catch(() => '');
    let body: ApiErrorBody | undefined;
    try {
      body = text ? (JSON.parse(text) as ApiErrorBody) : undefined;
    } catch {
      body = undefined;
    }
    throw new ApiError(response.status, body, response.statusText || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; anything after the last one
    // is a partial frame that has to wait for the next chunk.
    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';
    for (const frame of frames) {
      const parsed = parseSseFrame(frame);
      if (parsed) yield parsed;
    }
  }
}

function parseSseFrame(frame: string): ScriptStreamEvent | null {
  let event = 'message';
  let data = '';
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice('event:'.length).trim();
    else if (line.startsWith('data:')) data += line.slice('data:'.length).trim();
  }
  if (!data) return null;
  try {
    return { event, data: JSON.parse(data) } as ScriptStreamEvent;
  } catch {
    return null;
  }
}

export function createScript(
  input: { title: string; idea: string; referencedSkillIds: string[] },
  signal?: AbortSignal,
) {
  return streamPost(
    '/v1/scripts',
    {
      title: input.title,
      idea: input.idea,
      referenced_skill_ids: input.referencedSkillIds,
    },
    signal,
  );
}

export function sendTurn(
  episodeId: string,
  input: { message: string; referencedSkillIds: string[]; currentScript: ScriptDocument },
  signal?: AbortSignal,
) {
  return streamPost(
    `/v1/scripts/${episodeId}/turns`,
    {
      message: input.message,
      referenced_skill_ids: input.referencedSkillIds,
      // Always the exact document on screen — see `ScriptEditor.sendTurn`:
      // this may be an earlier turn the user has browsed back to, not
      // necessarily the episode's true latest turn.
      current_script: input.currentScript,
    },
    signal,
  );
}
