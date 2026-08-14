/** Canonical timeline apply. Mirrors `back/app/domain/editor/commands.py`. */

import {
  type CanonicalDocument,
  type EditCommand,
  type EditCommandBatch,
  type TimelineElement,
  type TimelineTrack,
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
]);

export class BatchRolledBackError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BatchRolledBackError';
  }
}

export function cloneDocument(document: CanonicalDocument): CanonicalDocument {
  return structuredClone(document);
}

export function emptyDocument(width = 1080, height = 1920): CanonicalDocument {
  return {
    schema_version: 1,
    engine: 'zaolang-canonical',
    canvas: { width, height, fps_num: 30, fps_den: 1 },
    tracks: [
      { id: 'trk_video', kind: 'video', elements: [] },
      { id: 'trk_audio', kind: 'audio', elements: [] },
      { id: 'trk_caption', kind: 'caption', elements: [] },
      { id: 'trk_overlay', kind: 'overlay', elements: [] },
    ],
    brand_overlay: null,
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

function applyOne(
  document: CanonicalDocument,
  command: EditCommand,
  knownAssets: Set<string>,
): void {
  switch (command.type) {
    case 'insert_clip': {
      const track = findTrack(document, command.track_id);
      if (!track) throw new Error('轨道不存在。');
      if (knownAssets.size && !knownAssets.has(command.asset_id)) {
        throw new Error('素材不存在或不属于该项目。');
      }
      assertSafeTicks(command.at_ticks, 'at_ticks');
      assertSafeTicks(command.duration_ticks, 'duration_ticks');
      const sourceIn = command.source_in_ticks ?? 0;
      track.elements.push({
        id: command.element_id ?? newElementId(),
        type: 'clip',
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
        id: newElementId(),
        start_ticks: command.at_ticks,
        duration_ticks: duration - left,
        source_in_ticks: sourceIn + left,
        source_out_ticks: sourceIn + duration,
      };
      found.element.duration_ticks = left;
      found.element.source_out_ticks = sourceIn + left;
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
    }
  }
}
