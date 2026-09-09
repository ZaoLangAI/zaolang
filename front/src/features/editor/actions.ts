/**
 * The editor's command surface, built once in `DramaEditor` and handed to the
 * shell, the timeline toolbar and the keyboard map so every entry point
 * (button, shortcut, context action) runs the exact same code path.
 */
export interface EditorActions {
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
  /** `S` — splits the selection at the playhead, or every element under it when nothing is selected. */
  splitAtPlayhead: () => void;
  /** `W` — keeps what is left of the playhead, dropping the right part of each selected element. */
  keepLeft: () => void;
  /** `Q` — keeps what is right of the playhead, dropping the left part of each selected element. */
  keepRight: () => void;
  /** `Ctrl+D` — duplicates the selection right after itself. */
  duplicateSelected: () => void;
  /** `Ctrl+C` / `Ctrl+V` — clipboard holds element ids; paste duplicates them anchored at the playhead. */
  copySelected: () => void;
  paste: () => void;
  canPaste: boolean;
  deleteSelected: () => void;
  selectAll: () => void;
  deselectAll: () => void;
  /** `M` — adds a marker at the playhead, or removes the one already there. */
  toggleMarkerAtPlayhead: () => void;
  /** Moves the selection so its earliest start sits on the playhead. */
  alignSelectedToPlayhead: () => void;
  /** `N` */
  toggleSnapping: () => void;
  togglePlay: () => void;
  seekTo: (ticks: number) => void;
  seekBy: (deltaTicks: number) => void;
  stepFrames: (frames: number) => void;
  goToStart: () => void;
  goToEnd: () => void;
  /** Adds an empty video/audio track. */
  addTrack: (kind: 'video' | 'audio') => void;
}
