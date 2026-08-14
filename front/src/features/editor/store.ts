import { create } from 'zustand';

interface EditorUiState {
  selectedIds: string[];
  playheadTicks: number;
  readonly: boolean;
  select: (ids: string[]) => void;
  setPlayhead: (ticks: number) => void;
  setReadonly: (readonly: boolean) => void;
}

export const useEditorUi = create<EditorUiState>((set) => ({
  selectedIds: [],
  playheadTicks: 0,
  readonly: false,
  select: (selectedIds) => set({ selectedIds }),
  setPlayhead: (playheadTicks) => set({ playheadTicks }),
  setReadonly: (readonly) => set({ readonly }),
}));
