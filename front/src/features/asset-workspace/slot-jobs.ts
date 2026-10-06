import type { CardKind } from '@/components/library/entry-actions';
import type { AssetGraph, AssetVariant } from '@/lib/api/types';

import { basePrompt, KIND_CONFIG, type SlotDef } from './kind-config';

export interface SlotJobOptions {
  /** Free text appended to the card's own description. */
  extra?: string;
  expressions?: string[];
  /** A style skill (`skill_ids`) to fold into the prompt. */
  skillId?: string | null;
}

/** The job (`POST /v1/generation-jobs`, no draft) that fills a non-pose slot
 * of `variant`. Pose slots go through `…:orbit`, the in-scene slot through
 * `…:derive` — both `null` here. */
export function slotJob(
  kind: CardKind,
  graph: AssetGraph,
  variant: AssetVariant,
  slot: SlotDef,
  options: SlotJobOptions = {},
): { operation: 'text_to_image'; params: Record<string, unknown> } | null {
  if (slot.kind === 'pose' || slot.kind === 'in_scene') return null;
  const config = KIND_CONFIG[kind];
  const prompt = [basePrompt(graph, variant), (options.extra ?? '').trim()]
    .filter(Boolean)
    .join('。');
  const params: Record<string, unknown> = {
    prompt: prompt || graph.name,
    asset_kind: config.assetKind,
    [config.targetKey]: graph.card_id,
    subject_name_hint: graph.name.slice(0, 60),
    skill_ids: options.skillId ? [options.skillId] : [],
  };
  const presets = (variant.presets ?? {}) as Record<string, string | null | undefined>;
  switch (slot.kind) {
    case 'portrait':
      params.character_portrait = true;
      params.aspect_ratio = '3:4';
      break;
    case 'sheet':
      params.target_variant_id = variant.id;
      params.aspect_ratio = '16:9';
      break;
    case 'expressions':
      params.target_variant_id = variant.id;
      params.character_expressions = options.expressions?.length
        ? options.expressions
        : ['neutral', 'smile', 'anger', 'sad', 'shock', 'fear'];
      params.aspect_ratio = '1:1';
      break;
    case 'master':
      params.target_variant_id = variant.id;
      if (kind === 'scene') {
        params.aspect_ratio = '16:9';
        for (const axis of ['lighting', 'weather', 'state', 'period']) {
          if (presets[axis]) params[`scene_${axis}`] = presets[axis];
        }
      } else {
        params.aspect_ratio = '1:1';
        if (presets.prop_state) params.prop_state = presets.prop_state;
      }
      break;
  }
  return { operation: 'text_to_image', params };
}
