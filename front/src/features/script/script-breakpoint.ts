import type { Draft } from '@/lib/api/types';

import type { ScriptBlock, ScriptDocument, ScriptScene } from './api';

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
 * The video-studio jump-out for a breakpoint that has not generated yet.
 * `referenceCharacterIds`/`referenceSceneIds` are generation *input*;
 * `linkEpisodeId`/`linkBreakpointKey` are what let the draft land on the
 * episode workspace and this exact chip. No refs → no generate link.
 * `continuityAssetId` — the previous segment's already-generated video, if
 * any (`previousBoundVideoAssetId`) — lets the studio auto-extract that
 * clip's last frame as this one's first frame (see `VideoGenerationStudio`'s
 * `continuitySourceAssetId`), so cuts flow instead of jumping between shots.
 */
export function buildBreakpointVideoHref({
  episodeId,
  key,
  characterIds,
  sceneId,
  prompt,
  continuityAssetId,
}: {
  episodeId: string;
  key: string;
  characterIds: string[];
  sceneId: string | null;
  prompt: string;
  continuityAssetId?: string | null;
}): string | undefined {
  if (characterIds.length === 0 && !sceneId) return undefined;
  const params = new URLSearchParams({
    mode: 'video_creation',
    linkEpisodeId: episodeId,
    linkBreakpointKey: key,
  });
  if (prompt) params.set('prompt', prompt);
  if (characterIds.length) params.set('referenceCharacterIds', characterIds.join(','));
  if (sceneId) params.set('referenceSceneIds', sceneId);
  if (continuityAssetId) params.set('continuityAssetId', continuityAssetId);
  return `/create/new?${params.toString()}`;
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
 * Where the "建议切分"/"查看/调整视频" chip goes. Once a draft is bound —
 * whatever its state (still generating, failed, or succeeded) — the chip
 * always resumes that exact draft in the video studio (`?draftId=`), which
 * shows its live/finished result, its full version history, and lets the
 * user tweak the prompt/params and generate another version right there;
 * there is no more separate read-only `/jobs/{id}` destination for a
 * breakpoint. `viewGenerated` only distinguishes the chip's label (already
 * has an output vs. still just a suggestion) — the destination is the
 * studio either way.
 */
export function resolveBreakpointHref({
  episodeId,
  key,
  characterIds,
  sceneId,
  prompt,
  binding,
  continuityAssetId,
}: {
  episodeId?: string;
  key: string;
  characterIds: string[];
  sceneId: string | null;
  prompt: string;
  binding?: BreakpointVideoBinding;
  /** The previous segment's bound video, if any — only meaningful for a
   * fresh (unbound) generate link; see `buildBreakpointVideoHref`. */
  continuityAssetId?: string | null;
}): { href?: string; viewGenerated: boolean } {
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
      prompt,
      continuityAssetId,
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

  for (const draft of drafts) {
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
