/** Canonical timeline apply. Mirrors `back/app/domain/editor/commands.py`. */

import {
  type CanonicalDocument,
  type EditCommand,
  type EditCommandBatch,
  type TimelineElement,
  type TimelineTrack,
  type TrackKind,
  MAX_COMMANDS_PER_BATCH,
  assertSafeTicks,
} from './ports';

const ALLOWED = new Set([
  'insert_clip',
  'delete_elements',
  'move_elements',
  'trim_element',
  'split_element',
  'set_clip_volume',
  'set_clip_speed',
  'insert_caption',
  'update_caption',
  'set_canvas',
  'set_brand_overlay',
  'add_track',
  'remove_track',
  'set_track_order',
  'set_track_muted',
  'add_effect',
  'remove_effect',
  'update_effect_params',
  'set_clip_mask',
  'set_keyframe',
  'delete_keyframe',
  'clear_keyframes',
  'set_transition',
  'add_marker',
  'remove_marker',
  'update_marker',
]);

const TRACK_KINDS_ADDABLE = new Set(['video', 'audio']);
const MAX_TRACKS_PER_KIND = 16;
// Only `blur` runs on the vendored WASM shader (confirmed the only one
// actually registered in the pinned Rust pipeline) — the rest are always
// Canvas2D `ctx.filter`. Keeping the allowlist here, not open-ended, means a
// caller can never request an effect the renderer has no path for.
const EFFECT_TYPES = new Set(['blur', 'brightness', 'contrast', 'saturate', 'grayscale']);
const MASK_SHAPES = new Set(['rect', 'ellipse']);
const MAX_EFFECTS_PER_ELEMENT = 8;

// A closed, per-property-validated enum — not the generic path/value update
// `validate_batch` permanently forbids. `set_keyframe`'s `property` field
// only ever selects one of these five names, each with its own numeric
// range below; it can never address an arbitrary tree path.
const ANIMATABLE_PROPERTIES = new Set([
  'opacity',
  'transform.x_milli',
  'transform.y_milli',
  'transform.scale_millipercent',
  'transform.rotation_millidegrees',
  'volume',
]);
const PROPERTY_RANGES: Record<string, [number, number]> = {
  opacity: [0, 100_000],
  'transform.x_milli': [-2000, 2000],
  'transform.y_milli': [-2000, 2000],
  'transform.scale_millipercent': [10_000, 500_000],
  'transform.rotation_millidegrees': [-180_000, 180_000],
  volume: [0, 200_000],
};
const MAX_KEYFRAMES_PER_CHANNEL = 64;
const EASING_TYPES = new Set(['linear', 'ease_in', 'ease_out']);
const DEFAULT_EASING = 'linear';
const MAX_MARKERS = 200;

const ELEMENT_TYPES_ADDABLE = new Set(['clip', 'sticker']);
const TRANSITION_TYPES = new Set(['crossfade', 'dip_to_black']);

export class BatchRolledBackError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BatchRolledBackError';
  }
}

export function cloneDocument(document: CanonicalDocument): CanonicalDocument {
  return structuredClone(document);
}

function emptyTrack(id: string, kind: TrackKind): TimelineTrack {
  return { id, kind, elements: [], order: 0, label: null, muted: false };
}

export function emptyDocument(width = 1080, height = 1920): CanonicalDocument {
  return {
    schema_version: 1,
    engine: 'zaolang-canonical',
    canvas: { width, height, fps_num: 30, fps_den: 1 },
    tracks: [
      emptyTrack('trk_video', 'video'),
      emptyTrack('trk_audio', 'audio'),
      emptyTrack('trk_caption', 'caption'),
      emptyTrack('trk_overlay', 'overlay'),
    ],
    brand_overlay: null,
    markers: [],
  };
}

export function durationTicks(document: CanonicalDocument): number {
  let end = 0;
  for (const track of document.tracks) {
    for (const element of track.elements) {
      end = Math.max(end, element.start_ticks + element.duration_ticks);
    }
  }
  return end;
}

export function validateBatch(input: unknown): EditCommandBatch {
  if (!input || typeof input !== 'object') throw new Error('命令批次必须是对象。');
  const payload = input as Record<string, unknown>;
  if (payload.schema_version !== 1) throw new Error('不支持的命令 schema。');
  if (typeof payload.batch_id !== 'string' || !payload.batch_id.trim()) {
    throw new Error('缺少 batch_id。');
  }
  if (!Array.isArray(payload.commands) || payload.commands.length === 0) {
    throw new Error('commands 不能为空。');
  }
  if (payload.commands.length > MAX_COMMANDS_PER_BATCH) {
    throw new Error(`单批最多 ${MAX_COMMANDS_PER_BATCH} 条命令。`);
  }
  const commands = payload.commands.map((raw, index) => {
    if (!raw || typeof raw !== 'object') throw new Error(`commands[${index}] 必须是对象。`);
    const command = raw as EditCommand;
    if (!ALLOWED.has(command.type)) throw new Error(`不支持的命令类型: ${command.type}。`);
    if ('path' in command) throw new Error('禁止通用路径更新。');
    return command;
  });
  return {
    schema_version: 1,
    batch_id: payload.batch_id,
    expected_revision_id:
      typeof payload.expected_revision_id === 'string' ? payload.expected_revision_id : null,
    commands,
  };
}

export function applyBatch(
  document: CanonicalDocument,
  commands: EditCommand[],
  knownAssets: Set<string>,
): CanonicalDocument {
  const working = cloneDocument(document);
  try {
    for (const command of commands) applyOne(working, command, knownAssets);
  } catch (error) {
    throw new BatchRolledBackError(error instanceof Error ? error.message : '命令批次已回滚');
  }
  return working;
}

function findTrack(document: CanonicalDocument, trackId: string): TimelineTrack | undefined {
  return document.tracks.find((track) => track.id === trackId);
}

function findElement(
  document: CanonicalDocument,
  elementId: string,
): { track: TimelineTrack; element: TimelineElement } | undefined {
  for (const track of document.tracks) {
    const element = track.elements.find((item) => item.id === elementId);
    if (element) return { track, element };
  }
  return undefined;
}

function newElementId(): string {
  return `el_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`;
}

function newTrackId(): string {
  return `trk_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`;
}

function newMarkerId(): string {
  return `mrk_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`;
}

function applyOne(
  document: CanonicalDocument,
  command: EditCommand,
  knownAssets: Set<string>,
): void {
  switch (command.type) {
    case 'insert_clip': {
      const track = findTrack(document, command.track_id);
      if (!track) throw new Error('轨道不存在。');
      if (!TRACK_KINDS_ADDABLE.has(track.kind)) throw new Error('片段只能插入视频或音频轨道。');
      const elementType = command.element_type ?? 'clip';
      if (!ELEMENT_TYPES_ADDABLE.has(elementType)) throw new Error('不支持的元素类型。');
      if (knownAssets.size && !knownAssets.has(command.asset_id)) {
        throw new Error('素材不存在或不属于该项目。');
      }
      assertSafeTicks(command.at_ticks, 'at_ticks');
      assertSafeTicks(command.duration_ticks, 'duration_ticks');
      const sourceIn = command.source_in_ticks ?? 0;
      track.elements.push({
        id: command.element_id ?? newElementId(),
        type: elementType,
        track_id: track.id,
        asset_id: command.asset_id,
        start_ticks: command.at_ticks,
        duration_ticks: command.duration_ticks,
        source_in_ticks: sourceIn,
        source_out_ticks: sourceIn + command.duration_ticks,
        volume_millipercent: 100_000,
        speed_millipercent: 100_000,
        text: null,
        caption_language: null,
        effects: [],
        mask: null,
        animations: { channels: {} },
        transition_in: null,
        transition_out: null,
      });
      return;
    }
    case 'delete_elements': {
      const ids = new Set(command.element_ids);
      for (const track of document.tracks) {
        track.elements = track.elements.filter((element) => !ids.has(element.id));
      }
      return;
    }
    case 'move_elements': {
      const target = command.track_id ? findTrack(document, command.track_id) : undefined;
      for (const elementId of command.element_ids) {
        const found = findElement(document, elementId);
        if (!found) throw new Error('元素不存在。');
        found.element.start_ticks = Math.max(0, found.element.start_ticks + command.delta_ticks);
        if (target && target.id !== found.track.id) {
          if (target.kind !== found.track.kind) throw new Error('不能跨轨道类型移动元素。');
          found.track.elements = found.track.elements.filter((item) => item.id !== elementId);
          found.element.track_id = target.id;
          target.elements.push(found.element);
        }
      }
      return;
    }
    case 'trim_element': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      found.element.start_ticks = command.start_ticks;
      found.element.duration_ticks = command.duration_ticks;
      found.element.source_in_ticks = command.source_in_ticks;
      found.element.source_out_ticks = command.source_out_ticks;
      return;
    }
    case 'split_element': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      const start = found.element.start_ticks;
      const duration = found.element.duration_ticks;
      if (command.at_ticks <= start || command.at_ticks >= start + duration) {
        throw new Error('拆分点必须落在元素内部。');
      }
      const left = command.at_ticks - start;
      const sourceIn = found.element.source_in_ticks;
      const right: TimelineElement = {
        ...found.element,
        // A shallow spread still shares the `effects` array (and its effect
        // objects), and the `animations.channels` map, with the original —
        // `update_effect_params`/`set_keyframe` mutate a key on one of those
        // shared objects in place, which would otherwise leak across both
        // split halves. `mask` needs no such copy: every write to it
        // replaces the whole value rather than mutating it.
        effects: found.element.effects.map((effect) => ({ ...effect })),
        animations: {
          channels: Object.fromEntries(
            Object.entries(found.element.animations.channels).map(([property, channel]) => [
              property,
              { kind: channel!.kind, points: [...channel!.points] },
            ]),
          ),
        },
        id: newElementId(),
        start_ticks: command.at_ticks,
        duration_ticks: duration - left,
        source_in_ticks: sourceIn + left,
        source_out_ticks: sourceIn + duration,
        // The split point is a brand-new internal edge on both halves — the
        // original's own transition_in stays on the left half (its start
        // didn't move) and transition_out stays on the right half (inherited
        // by the spread above, since its end didn't move either); neither
        // edge transition should duplicate onto the new cut point.
        transition_in: null,
      };
      found.element.duration_ticks = left;
      found.element.source_out_ticks = sourceIn + left;
      found.element.transition_out = null;
      found.track.elements.push(right);
      return;
    }
    case 'set_clip_volume': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      found.element.volume_millipercent = command.volume_millipercent;
      return;
    }
    case 'set_clip_speed': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      found.element.speed_millipercent = command.speed_millipercent;
      return;
    }
    case 'insert_caption': {
      const track = findTrack(document, command.track_id);
      if (!track) throw new Error('轨道不存在。');
      if (track.kind !== 'caption') throw new Error('字幕只能插入字幕轨道。');
      track.elements.push({
        id: command.element_id ?? newElementId(),
        type: 'caption',
        track_id: track.id,
        asset_id: null,
        start_ticks: command.at_ticks,
        duration_ticks: command.duration_ticks,
        source_in_ticks: 0,
        source_out_ticks: command.duration_ticks,
        volume_millipercent: 100_000,
        speed_millipercent: 100_000,
        text: command.text,
        caption_language: command.caption_language ?? 'zh-CN',
        effects: [],
        mask: null,
        animations: { channels: {} },
        transition_in: null,
        transition_out: null,
      });
      return;
    }
    case 'update_caption': {
      const found = findElement(document, command.element_id);
      if (!found || found.element.type !== 'caption') throw new Error('目标不是字幕。');
      if (command.text !== undefined) found.element.text = command.text;
      if (command.at_ticks !== undefined) found.element.start_ticks = command.at_ticks;
      if (command.duration_ticks !== undefined)
        found.element.duration_ticks = command.duration_ticks;
      return;
    }
    case 'set_canvas': {
      document.canvas.width = command.width;
      document.canvas.height = command.height;
      if (command.fps_num) document.canvas.fps_num = command.fps_num;
      if (command.fps_den) document.canvas.fps_den = command.fps_den;
      return;
    }
    case 'set_brand_overlay': {
      document.brand_overlay = command.overlay;
      return;
    }
    case 'add_track': {
      if (!TRACK_KINDS_ADDABLE.has(command.kind))
        throw new Error('轨道类型必须是 video 或 audio。');
      const sameKind = document.tracks.filter((track) => track.kind === command.kind);
      if (sameKind.length >= MAX_TRACKS_PER_KIND) {
        throw new Error(`同类轨道最多 ${MAX_TRACKS_PER_KIND} 条。`);
      }
      const trackId = command.track_id ?? newTrackId();
      if (findTrack(document, trackId)) throw new Error('轨道 id 已存在。');
      const maxOrder = sameKind.reduce((max, track) => Math.max(max, track.order), -1);
      document.tracks.push({
        id: trackId,
        kind: command.kind,
        elements: [],
        order: command.order ?? maxOrder + 1,
        label: command.label ?? null,
        muted: false,
      });
      return;
    }
    case 'remove_track': {
      const track = findTrack(document, command.track_id);
      if (!track) throw new Error('轨道不存在。');
      if (!TRACK_KINDS_ADDABLE.has(track.kind)) throw new Error('字幕轨与角标轨不可删除。');
      if (track.elements.length > 0) throw new Error('轨道非空，无法删除，请先移除轨道上的元素。');
      const remaining = document.tracks.filter((item) => item.kind === track.kind);
      if (remaining.length <= 1) throw new Error('至少保留一条该类型轨道。');
      document.tracks = document.tracks.filter((item) => item.id !== track.id);
      return;
    }
    case 'set_track_order': {
      const track = findTrack(document, command.track_id);
      if (!track) throw new Error('轨道不存在。');
      track.order = command.order;
      return;
    }
    case 'set_track_muted': {
      const track = findTrack(document, command.track_id);
      if (!track) throw new Error('轨道不存在。');
      track.muted = command.muted;
      return;
    }
    case 'add_effect': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      if (!EFFECT_TYPES.has(command.effect.type)) throw new Error('不支持的特效类型。');
      if (found.element.effects.length >= MAX_EFFECTS_PER_ELEMENT) {
        throw new Error(`单个元素最多 ${MAX_EFFECTS_PER_ELEMENT} 个特效。`);
      }
      found.element.effects = [...found.element.effects, command.effect];
      return;
    }
    case 'remove_effect': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      if (command.effect_index < 0 || command.effect_index >= found.element.effects.length) {
        throw new Error('特效索引越界。');
      }
      found.element.effects = found.element.effects.filter(
        (_, index) => index !== command.effect_index,
      );
      return;
    }
    case 'update_effect_params': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      const effect = found.element.effects[command.effect_index];
      if (!effect) throw new Error('特效索引越界。');
      effect.params = { ...effect.params, ...command.params };
      return;
    }
    case 'set_clip_mask': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      if (command.mask && !MASK_SHAPES.has(command.mask.shape)) throw new Error('不支持的蒙版形状。');
      found.element.mask = command.mask;
      return;
    }
    case 'set_keyframe': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      if (!ANIMATABLE_PROPERTIES.has(command.property)) throw new Error('不支持的动画属性。');
      const range = PROPERTY_RANGES[command.property]!;
      if (command.value < range[0] || command.value > range[1]) {
        throw new Error(`${command.property} 的值必须在 ${range[0]} 到 ${range[1]} 之间。`);
      }
      assertSafeTicks(command.at_ticks, 'at_ticks');
      const easing = command.easing ?? DEFAULT_EASING;
      if (!EASING_TYPES.has(easing)) throw new Error('不支持的缓动类型。');
      const existing = found.element.animations.channels[command.property];
      const points = (existing?.points ?? []).filter((point) => point.at_ticks !== command.at_ticks);
      if (points.length >= MAX_KEYFRAMES_PER_CHANNEL) {
        throw new Error(`单个属性最多 ${MAX_KEYFRAMES_PER_CHANNEL} 个关键帧。`);
      }
      points.push({ at_ticks: command.at_ticks, value: command.value, easing });
      points.sort((a, b) => a.at_ticks - b.at_ticks);
      found.element.animations.channels[command.property] = { kind: 'number', points };
      return;
    }
    case 'delete_keyframe': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      const channel = found.element.animations.channels[command.property];
      const points = channel?.points ?? [];
      const next = points.filter((point) => point.at_ticks !== command.at_ticks);
      if (next.length === points.length) throw new Error('该时间点没有关键帧。');
      found.element.animations.channels[command.property] = { kind: 'number', points: next };
      return;
    }
    case 'clear_keyframes': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      delete found.element.animations.channels[command.property];
      return;
    }
    case 'set_transition': {
      const found = findElement(document, command.element_id);
      if (!found) throw new Error('元素不存在。');
      const { transition } = command;
      if (transition) {
        if (!TRANSITION_TYPES.has(transition.type)) throw new Error('不支持的转场类型。');
        if (transition.duration_ticks <= 0 || transition.duration_ticks > found.element.duration_ticks) {
          throw new Error('转场时长必须大于零且不超过该元素自身时长。');
        }
      }
      if (command.edge === 'in') found.element.transition_in = transition;
      else found.element.transition_out = transition;
      return;
    }
    case 'add_marker': {
      if (document.markers.length >= MAX_MARKERS) throw new Error(`最多 ${MAX_MARKERS} 个标记点。`);
      const markerId = command.marker_id ?? newMarkerId();
      if (document.markers.some((marker) => marker.id === markerId)) {
        throw new Error('标记点 id 已存在。');
      }
      assertSafeTicks(command.at_ticks, 'at_ticks');
      if (command.label != null && command.label.length > 120) throw new Error('标记点文案最多 120 字符。');
      document.markers.push({ id: markerId, at_ticks: command.at_ticks, label: command.label ?? null });
      return;
    }
    case 'remove_marker': {
      const next = document.markers.filter((marker) => marker.id !== command.marker_id);
      if (next.length === document.markers.length) throw new Error('标记点不存在。');
      document.markers = next;
      return;
    }
    case 'update_marker': {
      const marker = document.markers.find((item) => item.id === command.marker_id);
      if (!marker) throw new Error('标记点不存在。');
      if (command.label != null && command.label.length > 120) throw new Error('标记点文案最多 120 字符。');
      if (command.at_ticks !== undefined) marker.at_ticks = command.at_ticks;
      if (command.label !== undefined) marker.label = command.label ?? null;
      return;
    }
  }
}
