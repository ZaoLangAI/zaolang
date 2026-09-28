/**
 * HTML5 drag payload shared by the media library (source) and the timeline
 * (drop target). A custom MIME keeps timeline drops from ever mistaking a
 * dragged text selection or URL for a media asset.
 */

import type { Asset } from '@/lib/api/types';

import { TICKS_PER_SECOND } from '../engine/ports';

export const ASSET_DRAG_MIME = 'application/x-zaolang-asset';

export interface AssetDragPayload {
  asset_id: string;
  media_type: string;
  mime_type: string;
  duration_ticks: number | null;
  width: number | null;
  height: number | null;
  url: string | null;
}

export function assetDragPayload(asset: Asset): AssetDragPayload {
  return {
    asset_id: asset.id,
    media_type: asset.media_type,
    mime_type: asset.mime_type,
    duration_ticks:
      asset.duration_ms && asset.duration_ms > 0
        ? Math.round((asset.duration_ms / 1000) * TICKS_PER_SECOND)
        : null,
    width: asset.width ?? null,
    height: asset.height ?? null,
    url: asset.url ?? null,
  };
}

export function writeAssetDrag(dataTransfer: DataTransfer, asset: Asset): void {
  dataTransfer.setData(ASSET_DRAG_MIME, JSON.stringify(assetDragPayload(asset)));
  dataTransfer.effectAllowed = 'copy';
}

export function hasAssetDrag(dataTransfer: DataTransfer | null): boolean {
  return !!dataTransfer && Array.from(dataTransfer.types).includes(ASSET_DRAG_MIME);
}

export function hasFileDrag(dataTransfer: DataTransfer | null): boolean {
  return !!dataTransfer && Array.from(dataTransfer.types).includes('Files');
}

export function readAssetDrag(dataTransfer: DataTransfer | null): AssetDragPayload | null {
  if (!dataTransfer) return null;
  const raw = dataTransfer.getData(ASSET_DRAG_MIME);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<AssetDragPayload>;
    if (typeof parsed.asset_id !== 'string') return null;
    return {
      asset_id: parsed.asset_id,
      media_type: typeof parsed.media_type === 'string' ? parsed.media_type : 'video',
      mime_type: typeof parsed.mime_type === 'string' ? parsed.mime_type : 'video/mp4',
      duration_ticks: typeof parsed.duration_ticks === 'number' ? parsed.duration_ticks : null,
      width: typeof parsed.width === 'number' ? parsed.width : null,
      height: typeof parsed.height === 'number' ? parsed.height : null,
      url: typeof parsed.url === 'string' ? parsed.url : null,
    };
  } catch {
    return null;
  }
}

/** Which track kind a dropped asset belongs on. Images become video-track clips (stills). */
export function trackKindForMedia(mediaType: string): 'video' | 'audio' {
  return mediaType === 'audio' ? 'audio' : 'video';
}

/** Default clip length for a dropped asset: its own length, or 3s for stills/unknown. */
export function defaultInsertDuration(payload: {
  duration_ticks: number | null;
  media_type: string;
}): number {
  if (payload.duration_ticks && payload.duration_ticks > 0) return payload.duration_ticks;
  return 3 * TICKS_PER_SECOND;
}
