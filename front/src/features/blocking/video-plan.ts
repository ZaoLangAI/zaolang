import type { ScriptDocument } from '@/features/script/api';
import { locateBreakpoint } from '@/features/script/script-breakpoint';
import { breakpointSegmentPrompt } from '@/features/script/script-prompts';
import { STUDIO_PROMPT_MAX_LENGTH } from '@/lib/prompt-limits';

import type { BlockingDocument, CameraHeight, CameraSide, ShotSize } from './types';

/**
 * One segment's video job, planned from the blockout rather than from the
 * script alone: the segment's *own* duration, the linked character assets
 * of everyone the blockout puts on set, and a colour legend so the model
 * can map each mannequin in the reference clip to its reference images.
 */
export interface SegmentVideoPlan {
  key: string;
  heading: string;
  durationSeconds: number;
  characterIds: string[];
  sceneId: string | null;
  prompt: string;
  /** Cast on set with no linked character asset — the clip still generates,
   * but that person's look comes from the prompt only. */
  unlinkedCast: string[];
  /** The segment's opening shot camera — the backend ranks each linked
   * card's library images by how close their angle is to it (AC-3). */
  referenceCamera: {
    reference_shot_size: ShotSize;
    reference_camera_side: CameraSide;
    reference_camera_height: CameraHeight;
  } | null;
}

/** Model-facing colour names — prompt text, like the rest of
 * `script-prompts.ts`, not UI copy. Index-aligned with `palette.CAST_COLORS`. */
const PROMPT_COLOR_NAMES = ['红色', '蓝色', '绿色', '黄色', '紫色', '橙色', '青色', '粉色'];

export function castLegend(document: BlockingDocument, segmentKey: string): string {
  const segment = document.segments?.find((item) => item.key === segmentKey);
  const byId = new Map((document.cast ?? []).map((member) => [member.id, member]));
  const parts: string[] = [];
  for (const entry of segment?.start ?? []) {
    const member = byId.get(entry.cast_id);
    if (!member) continue;
    const color = PROMPT_COLOR_NAMES[member.color_index % PROMPT_COLOR_NAMES.length];
    parts.push(`${color}人偶是${member.name}`);
  }
  return parts.length ? `参考视频中${parts.join('，')}。` : '';
}

export function planSegmentVideo(
  document: BlockingDocument,
  script: ScriptDocument,
  segmentKey: string,
): SegmentVideoPlan | null {
  const segment = document.segments?.find((item) => item.key === segmentKey);
  const located = locateBreakpoint(script, segmentKey);
  if (!segment || !located) return null;

  const castById = new Map((document.cast ?? []).map((member) => [member.id, member]));
  const characterIds: string[] = [];
  const unlinkedCast: string[] = [];
  for (const entry of segment.start ?? []) {
    const member = castById.get(entry.cast_id);
    if (!member) continue;
    if (member.character_ref_id) {
      if (!characterIds.includes(member.character_ref_id))
        characterIds.push(member.character_ref_id);
    } else {
      unlinkedCast.push(member.name);
    }
  }

  // The legend leads so a long segment's description, not the mapping the
  // reference clip depends on, is what gets clipped at the length cap.
  const legend = castLegend(document, segmentKey);
  const body = breakpointSegmentPrompt(located.scene, located.blockIndex);
  const prompt = (legend ? `${legend}\n${body}` : body).slice(0, STUDIO_PROMPT_MAX_LENGTH);

  const opening = segment.camera_override ? null : (segment.shots ?? [])[0];
  return {
    key: segment.key,
    heading: segment.heading,
    durationSeconds: segment.duration_s,
    characterIds,
    sceneId: located.scene.ref_id,
    prompt,
    unlinkedCast,
    referenceCamera: opening
      ? {
          reference_shot_size: opening.size,
          reference_camera_side: opening.side,
          reference_camera_height: opening.height,
        }
      : null,
  };
}

export function planSegmentVideos(
  document: BlockingDocument,
  script: ScriptDocument,
  keys: string[],
): SegmentVideoPlan[] {
  return keys
    .map((key) => planSegmentVideo(document, script, key))
    .filter((plan): plan is SegmentVideoPlan => plan !== null);
}
