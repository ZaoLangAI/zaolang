import type { Draft } from '@/lib/api/types';

import type { ScriptBlock, ScriptDocument, ScriptScene } from './api';

/** `DramaEpisode.id` is `dep_` + a Crockford token, stored in `String(40)`. */
export function parseScriptEpisodeId(raw: string | undefined): string | undefined {
  if (!raw || raw.length > 40 || !/^dep_[0-9A-Za-z]+$/.test(raw)) return undefined;
  return raw;
}

/** `Draft.id` is `drf_` + a Crockford token, stored in `String(40)`. */
export function parseScriptDraftId(raw: string | undefined): string | undefined {
  if (!raw || raw.length > 40 || !/^drf_[0-9A-Za-z]+$/.test(raw)) return undefined;
  return raw;
}

/** `{heading}#{ordinal}` from the clip-studio query string. */
export function parseBreakpointQueryKey(raw: string | undefined): string | undefined {
  const key = raw?.trim() ?? '';
  if (!key || key.length > 120 || !key.includes('#')) return undefined;
  return key;
}

/** Stable id for one breakpoint inside one scene — `{heading}#{ordinal}`. */
export function breakpointKey(heading: string, ordinal: number): string {
  return `${heading}#${ordinal}`;
}

/** How many `breakpoint` blocks sit before `breakpointBlockIndex` in this scene. */
export function breakpointOrdinalInScene(scene: ScriptScene, breakpointBlockIndex: number): number {
  let ordinal = 0;
  for (let index = 0; index < breakpointBlockIndex; index += 1) {
    if (scene.blocks[index]?.type === 'breakpoint') ordinal += 1;
  }
  return ordinal;
}

/** Blocks from the previous `breakpoint` (or the scene start) up to `breakpointBlockIndex`. */
export function breakpointSegmentBlocks(
  scene: ScriptScene,
  breakpointBlockIndex: number,
): ScriptBlock[] {
  let segmentStart = 0;
  for (let index = breakpointBlockIndex - 1; index >= 0; index -= 1) {
    if (scene.blocks[index]?.type === 'breakpoint') {
      segmentStart = index + 1;
      break;
    }
  }
  return scene.blocks.slice(segmentStart, breakpointBlockIndex);
}

function segmentHasShootableContent(blocks: ScriptBlock[]): boolean {
  return blocks.some((block) => block.type !== 'breakpoint' && block.text.trim());
}

/**
 * A scene whose last block is not a `breakpoint` still has an unclosed
 * shootable tail — the UI draws a synthetic chip there (never persisted).
 */
export function sceneHasUnclosedSegment(scene: ScriptScene): boolean {
  if (scene.blocks.length === 0) return false;
  if (scene.blocks[scene.blocks.length - 1]?.type === 'breakpoint') return false;
  return segmentHasShootableContent(breakpointSegmentBlocks(scene, scene.blocks.length));
}

/** Virtual closer after the last real block — key is `{heading}#{existing count}`. */
export function trailingBreakpoint(
  scene: ScriptScene,
): { key: string; blockIndex: number } | null {
  if (!sceneHasUnclosedSegment(scene)) return null;
  return {
    key: breakpointKey(scene.heading, breakpointOrdinalInScene(scene, scene.blocks.length)),
    blockIndex: scene.blocks.length,
  };
}

/**
 * The whole script's breakpoints, flattened into the order they are meant to
 * be shot/generated in: scene order, then each scene's own breakpoints by
 * ordinal, plus its trailing unclosed-segment closer (if any) last. This is
 * the "video 1, video 2, video 3, …" sequence the首尾帧 continuity feature
 * walks backwards over — see `previousBoundVideoAssetId` below.
 */
export function orderedBreakpointKeys(document: ScriptDocument): string[] {
  const keys: string[] = [];
  for (const scene of document.scenes) {
    let ordinal = 0;
    for (const block of scene.blocks) {
      if (block.type !== 'breakpoint') continue;
      keys.push(breakpointKey(scene.heading, ordinal));
      ordinal += 1;
    }
    const closer = trailingBreakpoint(scene);
    if (closer) keys.push(closer.key);
  }
  return keys;
}

/** Scene + block index for a `{heading}#{ordinal}` key, including a trailing closer. */
export function locateBreakpoint(
  document: ScriptDocument,
  key: string,
): { scene: ScriptScene; blockIndex: number } | null {
  for (const scene of document.scenes) {
    let ordinal = 0;
    for (let blockIndex = 0; blockIndex < scene.blocks.length; blockIndex += 1) {
      if (scene.blocks[blockIndex]?.type !== 'breakpoint') continue;
      if (breakpointKey(scene.heading, ordinal) === key) {
        return { scene, blockIndex };
      }
      ordinal += 1;
    }
    const closer = trailingBreakpoint(scene);
    if (closer?.key === key) return { scene, blockIndex: closer.blockIndex };
  }
  return null;
}

/**
 * The nearest *earlier* breakpoint (in the whole document's generation
 * order, not just this scene) that already has a bound video output —
 * that clip's last frame is what the next segment's generation should pick
 * up from, so the cut between them reads as continuous once assembled in
 * the editor. Returns `null` when `key` is the first breakpoint, or when no
 * earlier segment has generated a video yet.
 */
export function previousBoundVideoAssetId(
  document: ScriptDocument,
  key: string,
  bindings: Record<string, BreakpointVideoBinding>,
): string | null {
  const ordered = orderedBreakpointKeys(document);
  const index = ordered.indexOf(key);
  if (index <= 0) return null;
  for (let i = index - 1; i >= 0; i -= 1) {
    const earlierKey = ordered[i];
    const assetId = earlierKey ? bindings[earlierKey]?.outputAssetId : undefined;
    if (assetId) return assetId;
  }
  return null;
}

/**
 * The clip-studio jump-out for a breakpoint that has not generated yet.
 * Episode id and breakpoint key are the only payload — the studio loads
 * the segment from `GET /v1/scripts/{id}`. Always clickable: the clip
 * studio's scene dropdown can attach a plate even when this heading has
 * no `ref_id` yet.
 */
export function buildBreakpointVideoHref({
  episodeId,
  key,
}: {
  episodeId: string;
  key: string;
  /** @deprecated unused; kept so existing call sites can drop it gradually. */
  characterIds?: string[];
  /** @deprecated unused; kept so existing call sites can drop it gradually. */
  sceneId?: string | null;
  /** @deprecated unused; kept so existing call sites can drop it gradually. */
  prompt?: string;
}): string {
  const params = new URLSearchParams({ key });
  return `/create/script/${episodeId}/clip?${params.toString()}`;
}

export type BreakpointVideoBinding = {
  /** The generation draft this breakpoint's video lives under — always set
   * once a binding exists (`draftBinding` always has a real `Draft.id` on
   * hand). This is what lets the chip resume the video studio's full
   * version history (`GenerationVersionHistory`) instead of a read-only
   * job page — see `resolveBreakpointHref`. */
  draftId: string;
  latestJobId: string | null;
  outputAssetId: string | null;
};

/**
 * Where the "生成视频"/"查看/调整视频" chip goes. Both states land on the
 * script clip studio (`/create/script/{episodeId}/clip?key=`). A bound
 * draft adds `draftId` so that session's version history resumes.
 * `viewGenerated` only distinguishes the chip's label.
 */
export function resolveBreakpointHref({
  episodeId,
  key,
  characterIds,
  sceneId,
  binding,
}: {
  episodeId?: string;
  key: string;
  characterIds: string[];
  sceneId: string | null;
  /** @deprecated unused. */
  prompt?: string;
  binding?: BreakpointVideoBinding;
}): { href?: string; viewGenerated: boolean } {
  if (binding && episodeId) {
    const params = new URLSearchParams({ key, draftId: binding.draftId });
    return {
      href: `/create/script/${episodeId}/clip?${params.toString()}`,
      viewGenerated: Boolean(binding.outputAssetId),
    };
  }
  if (binding) {
    const params = new URLSearchParams({ mode: 'video_creation', draftId: binding.draftId });
    return {
      href: `/create/new?${params.toString()}`,
      viewGenerated: Boolean(binding.outputAssetId),
    };
  }
  if (!episodeId) return { viewGenerated: false };
  return {
    href: buildBreakpointVideoHref({
      episodeId,
      key,
      characterIds,
      sceneId,
    }),
    viewGenerated: false,
  };
}

function draftBinding(draft: Draft): BreakpointVideoBinding {
  return {
    draftId: draft.id,
    latestJobId: draft.latest_job_id ?? null,
    outputAssetId: draft.output_asset_id ?? null,
  };
}

function stringParam(params: Record<string, unknown> | undefined, name: string): string | null {
  const value = params?.[name];
  return typeof value === 'string' && value ? value : null;
}

/**
 * Maps episode-linked drafts onto `{heading}#{ordinal}`. Prefers the key
 * written at submit time; drafts that predate that field fall back to
 * "prompt starts with this scene's heading → first unused breakpoint".
 */
export function indexBreakpointVideos(
  drafts: Draft[],
  scenes: ScriptScene[],
): Record<string, BreakpointVideoBinding> {
  const byKey: Record<string, BreakpointVideoBinding> = {};
  const unmatched: Draft[] = [];

  // Only ever consider `text_to_video` drafts — a script-linked draft can
  // now also be `audio_generation` (dubbing, see `dubbedDialogueKeys`
  // below) or an image batch item, none of which should ever bind onto a
  // breakpoint's video chip. Drafts from before `operation` was stored in
  // `params` (none left in practice, but harmless to keep) fall through.
  // `image_to_video` is a segment generated from its confirmed storyboard
  // keyframe (`indexBreakpointKeyframes`) — still that segment's video.
  const videoDrafts = drafts.filter((draft) => {
    const operation = stringParam(draft.params, 'operation');
    return !operation || operation === 'text_to_video' || operation === 'image_to_video';
  });

  for (const draft of videoDrafts) {
    const key = stringParam(draft.params, 'link_breakpoint_key');
    if (key) byKey[key] = draftBinding(draft);
    else unmatched.push(draft);
  }

  const unusedOrdinal = (heading: string): number | null => {
    const scene = scenes.find((item) => item.heading === heading);
    if (!scene) return null;
    let ordinal = 0;
    for (const block of scene.blocks) {
      if (block.type !== 'breakpoint') continue;
      const key = breakpointKey(heading, ordinal);
      if (!(key in byKey)) return ordinal;
      ordinal += 1;
    }
    if (sceneHasUnclosedSegment(scene) && !(breakpointKey(heading, ordinal) in byKey)) {
      return ordinal;
    }
    return null;
  };

  for (const draft of unmatched) {
    const prompt = stringParam(draft.params, 'prompt');
    if (!prompt) continue;
    for (const scene of scenes) {
      if (!prompt.startsWith(scene.heading)) continue;
      const ordinal = unusedOrdinal(scene.heading);
      if (ordinal === null) continue;
      byKey[breakpointKey(scene.heading, ordinal)] = draftBinding(draft);
      break;
    }
  }

  return byKey;
}

/** `link_breakpoint_key`s already dubbed by an episode-linked
 * `audio_generation` draft — used by `pendingDialogueLines` to skip lines
 * that already have a voice clip. Only the key matters (no chip/history UI
 * hangs off a dubbed line the way `BreakpointVideoBinding` does for video),
 * so this stays a plain `Set` rather than a binding map. */
export function dubbedDialogueKeys(drafts: Draft[]): Set<string> {
  const keys = new Set<string>();
  for (const draft of drafts) {
    if (stringParam(draft.params, 'operation') !== 'audio_generation') continue;
    const key = stringParam(draft.params, 'link_breakpoint_key');
    if (key) keys.add(key);
  }
  return keys;
}

/** `{heading}#K{ordinal}` — a segment's storyboard keyframe draft. Same
 * `link_breakpoint_key` slot as its video (`{heading}#{ordinal}`) and its
 * voice lines (`{heading}#L{blockIndex}`), in a shape neither can collide with. */
export function keyframeKey(segmentKey: string): string {
  const hash = segmentKey.lastIndexOf('#');
  return `${segmentKey.slice(0, hash)}#K${segmentKey.slice(hash + 1)}`;
}

export interface KeyframeBinding {
  draftId: string;
  /** The draft's current (applied) version — what 「确认」 pins. */
  appliedJobId: string | null;
  outputAssetId: string | null;
  outputUrl: string | null;
  /** The author confirmed exactly this version as the segment's first frame. */
  confirmed: boolean;
}

/**
 * Episode-linked `text_to_image` keyframe drafts, keyed by their *segment*
 * key. Confirmed means `params.keyframe_confirmed_job_id` names the draft's
 * current applied version: a regenerate moves the applied version on and so
 * un-confirms it by construction — a first frame is never used without the
 * author having looked at that exact image.
 */
export function indexBreakpointKeyframes(drafts: Draft[]): Record<string, KeyframeBinding> {
  const byKey: Record<string, KeyframeBinding> = {};
  for (const draft of drafts) {
    if (stringParam(draft.params, 'operation') !== 'text_to_image') continue;
    const match = /^(.*)#K(\d+)$/.exec(stringParam(draft.params, 'link_breakpoint_key') ?? '');
    if (!match) continue;
    const appliedJobId = draft.applied_job_id ?? null;
    const confirmedJobId = stringParam(draft.params, 'keyframe_confirmed_job_id');
    byKey[breakpointKey(match[1] ?? '', Number(match[2]))] = {
      draftId: draft.id,
      appliedJobId,
      outputAssetId: draft.output_asset_id ?? null,
      outputUrl: draft.output_url ?? null,
      confirmed: Boolean(
        confirmedJobId && confirmedJobId === appliedJobId && draft.output_asset_id,
      ),
    };
  }
  return byKey;
}

/** Segment key → confirmed keyframe asset, for `pendingVideos`' first frames. */
export function confirmedFirstFrames(
  keyframes: Record<string, KeyframeBinding>,
): Record<string, string> {
  const frames: Record<string, string> = {};
  for (const [key, binding] of Object.entries(keyframes)) {
    if (binding.confirmed && binding.outputAssetId) frames[key] = binding.outputAssetId;
  }
  return frames;
}
