import { api } from '@/lib/api/client';
import { streamPost as streamAgentPost } from '@/lib/sse-post';

export type ScriptBlockType = 'scene' | 'action' | 'camera' | 'dialogue' | 'breakpoint';

/** A dialogue line's delivery for dubbing — the backend's closed
 * `copywriter.SCRIPT_EMOTIONS`. Absent/null means said plainly. */
export type ScriptEmotion = 'happy' | 'sad' | 'angry' | 'fear' | 'surprise' | 'calm';

export interface ScriptBlock {
  type: ScriptBlockType;
  character: string | null;
  text: string;
  emotion?: ScriptEmotion | null;
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
  /** The model's reasoning trace for this turn — empty for a turn written
   * before this field existed, or whose model/endpoint never produced one.
   * Rendered as a collapsed-by-default disclosure, never inside the
   * right-side script view. */
  thinking: string;
}

export interface ScriptSummary {
  episode_id: string;
  title: string;
  logline: string;
  status: string;
  turn_count: number;
  updated_at: string;
}

/** One deterministic lint finding (`app/domain/script_writing/lint.py`) — a
 * suggestion beside the script, never a blocker. `message` is written by the
 * backend in the script's own language. */
export interface ScriptLintIssue {
  code: string;
  severity: 'warning' | 'info';
  message: string;
  scene_index: number | null;
  heading: string;
  block_index: number | null;
  breakpoint_key: string | null;
  dimension: string | null;
  /** Titles of `format` skills that fix this dimension — `@`-able next turn. */
  suggested_skills: string[];
}

export interface ScriptDetail {
  episode_id: string;
  series_id: string;
  title: string;
  status: string;
  script: ScriptDocument;
  turns: ScriptTurnSummary[];
  /** Lint of the latest saved script (not of an older turn snapshot). */
  lint: ScriptLintIssue[];
  /** Author's first-draft prompt, so an empty shell can be retried without re-typing. */
  source_idea: string;
  source_referenced_skill_ids: string[];
  /** Latest failed-generation excerpt for this episode, if any. */
  last_error: string | null;
  created_at: string;
  updated_at: string;
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
  thinking: string;
}

export type ScriptStreamEvent =
  | { event: 'start'; data: { episode_id: string } }
  | { event: 'delta'; data: { text: string } }
  | { event: 'thinking'; data: { text: string } }
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
  for await (const frame of streamAgentPost(path, body, signal)) {
    yield frame as ScriptStreamEvent;
  }
}

export interface ScriptExtractResult {
  filename: string;
  text: string;
  char_count: number;
  truncated: boolean;
}

export function extractScriptSource(file: File) {
  const body = new FormData();
  body.append('file', file);
  return api.post<ScriptExtractResult>('/v1/scripts/extract', body);
}

export function createScript(
  input: { title: string; idea: string; referencedSkillIds: string[]; seriesId?: string },
  signal?: AbortSignal,
) {
  return streamPost(
    '/v1/scripts',
    {
      title: input.title,
      idea: input.idea,
      referenced_skill_ids: input.referencedSkillIds,
      series_id: input.seriesId,
    },
    signal,
  );
}

/**
 * Re-runs a first draft for an episode shell whose original stream never
 * finished (a page refresh or dropped connection lost `create-stream-store.ts`'s
 * in-memory progress) — reuses this exact `episode_id`/`Series` instead of
 * `createScript`, which always mints a brand-new one. `idea` may be omitted
 * when the episode already stored `source_idea`.
 */
export function retryScript(
  episodeId: string,
  input: { idea?: string; referencedSkillIds?: string[] } = {},
  signal?: AbortSignal,
) {
  const body: { idea?: string; referenced_skill_ids?: string[] } = {};
  const idea = input.idea?.trim();
  if (idea) body.idea = idea;
  if (input.referencedSkillIds?.length) {
    body.referenced_skill_ids = input.referencedSkillIds;
  }
  return streamPost(`/v1/scripts/${episodeId}/retry`, body, signal);
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
