import type { Draft } from '@/lib/api/types';

import type { ScriptScene } from './api';

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

/**
 * The video-studio jump-out for a breakpoint that has not generated yet.
 * `referenceCharacterIds`/`referenceSceneIds` are generation *input*;
 * `linkEpisodeId`/`linkBreakpointKey` are what let the draft land on the
 * episode workspace and this exact chip. No refs → no generate link.
 */
export function buildBreakpointVideoHref({
  episodeId,
  key,
  characterIds,
  sceneId,
  prompt,
}: {
  episodeId: string;
  key: string;
  characterIds: string[];
  sceneId: string | null;
  prompt: string;
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
  return `/create/new?${params.toString()}`;
}

export type BreakpointVideoBinding = {
  latestJobId: string | null;
  outputAssetId: string | null;
};

export function resolveBreakpointHref({
  episodeId,
  key,
  characterIds,
  sceneId,
  prompt,
  binding,
}: {
  episodeId?: string;
  key: string;
  characterIds: string[];
  sceneId: string | null;
  prompt: string;
  binding?: BreakpointVideoBinding;
}): { href?: string; viewGenerated: boolean } {
  if (binding?.latestJobId) {
    return { href: `/jobs/${binding.latestJobId}`, viewGenerated: true };
  }
  // A linked draft with no job yet still owns this chip — don't spawn another.
  if (binding) return { viewGenerated: false };
  if (!episodeId) return { viewGenerated: false };
  return {
    href: buildBreakpointVideoHref({
      episodeId,
      key,
      characterIds,
      sceneId,
      prompt,
    }),
    viewGenerated: false,
  };
}

function draftBinding(draft: Draft): BreakpointVideoBinding {
  return {
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
