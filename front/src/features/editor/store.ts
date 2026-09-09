import { create } from 'zustand';

import { TICKS_PER_SECOND, type ResolvedAsset } from './engine/ports';

interface EditorUiState {
  selectedIds: string[];
  playheadTicks: number;
  readonly: boolean;
  /** Live playback flag — owned here (not inside `Preview`) so the timeline can auto-follow the playhead and shortcuts can toggle it from anywhere. */
  playing: boolean;
  /** Snap-to-edges while dragging/trimming/scrubbing. Toggled by the toolbar magnet or `N`; Shift held during a drag bypasses it without flipping this. */
  snappingEnabled: boolean;
  /** Element ids captured by Ctrl+C. Paste re-issues them as `duplicate_elements` anchored at the playhead — a deleted source simply fails the paste, there is no detached element snapshot. */
  clipboardIds: string[];
  /**
   * Assets the UI has touched (media-library insert/drag, fresh upload) but
   * the head revision's `asset_urls` doesn't list yet. Lets an optimistic
   * `insert_clip` render immediately instead of waiting for the server's
   * revision to name the asset; superseded by the revision's own entry once
   * it lands.
   */
  knownAssets: Record<string, ResolvedAsset>;
  select: (ids: string[]) => void;
  setPlayhead: (ticks: number) => void;
  setReadonly: (readonly: boolean) => void;
  setPlaying: (playing: boolean) => void;
  toggleSnapping: () => void;
  setClipboard: (ids: string[]) => void;
  rememberAsset: (asset: ResolvedAsset) => void;
}

export const useEditorUi = create<EditorUiState>((set) => ({
  selectedIds: [],
  playheadTicks: 0,
  readonly: false,
  playing: false,
  snappingEnabled: true,
  clipboardIds: [],
  knownAssets: {},
  select: (selectedIds) => set({ selectedIds }),
  setPlayhead: (playheadTicks) => set({ playheadTicks }),
  setReadonly: (readonly) => set({ readonly }),
  setPlaying: (playing) => set({ playing }),
  toggleSnapping: () => set((state) => ({ snappingEnabled: !state.snappingEnabled })),
  setClipboard: (clipboardIds) => set({ clipboardIds }),
  rememberAsset: (asset) =>
    set((state) =>
      state.knownAssets[asset.asset_id]?.url === asset.url
        ? state
        : { knownAssets: { ...state.knownAssets, [asset.asset_id]: asset } },
    ),
}));

/** `ResolvedAsset` from the media API's `AssetResponse` shape. */
export function resolvedAssetFrom(asset: {
  id: string;
  url?: string | null;
  mime_type: string;
  media_type: string;
  duration_ms?: number | null;
  width?: number | null;
  height?: number | null;
}): ResolvedAsset | null {
  if (!asset.url) return null;
  return {
    asset_id: asset.id,
    url: asset.url,
    mime_type: asset.mime_type,
    media_type: asset.media_type,
    duration_ticks:
      asset.duration_ms && asset.duration_ms > 0
        ? Math.round((asset.duration_ms / 1000) * TICKS_PER_SECOND)
        : null,
    width: asset.width ?? null,
    height: asset.height ?? null,
  };
}
