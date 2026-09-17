# Third-party notices

The layout and component structure of this directory (`front/src/features/editor/studio/`)
is adapted from **OpenCut** (`opencut-app/opencut-classic`), specifically:

- `apps/web/src/app/editor/[project_id]/page.tsx` — the overall shell / resizable-panel
  layout → `studio-shell.tsx`
- `apps/web/src/components/editor/editor-header.tsx` → `editor-header.tsx`
- `apps/web/src/components/editor/panels/assets/index.tsx` and `tabbar.tsx` — the tab bar +
  view-map pattern → `media-library-panel.tsx`
- `apps/web/src/components/editor/panels/properties/index.tsx`, `empty-view.tsx` and the
  per-type `registry.ts` sub-tab idea → `properties-panel.tsx`
- `apps/web/src/components/editor/panels/properties/property-item.tsx` — the numeric row
  whose label scrubs the value and shows a reset glyph → `number-field.tsx`
- `apps/web/src/components/editor/panels/assets/views/media.tsx` — whole-panel drop-to-
  upload overlay, search box, grid/list toggle, draggable cards → `media-library-panel.tsx`
- `apps/web/src/components/editor/timeline/timeline-toolbar.tsx` — the icon toolbar layout
  (split / keep-left / keep-right / duplicate / delete / marker / snapping / zoom slider)
  → `../timeline/toolbar.tsx`
- `apps/web/src/components/editor/preview-panel.tsx` (toolbar portion only) — the
  transport bar (skip / step / play / timecode / fullscreen) → the toolbar in `../preview.tsx`
- `apps/web/src/hooks/use-keyboard-shortcuts.ts` — the key map (Space/K, J/L, S/W/Q,
  Ctrl+D, N, M, Home/End …) → `useEditorShortcuts` in `studio-shell.tsx` and the listing
  in `shortcuts-dialog.tsx`

Only UI shell/layout/presentational structure was adapted. None of OpenCut's own timeline
data model, undo/redo command stack, canvas/WASM compositor, or rendering/export code was
used — this editor's timeline geometry/snapping (`../timeline/geometry.ts`), ruler,
drag/drop/marquee logic (`../timeline/timeline.tsx`), on-canvas transform gizmo
(`../transform-gizmo.tsx`), preview compositor, and export logic are ZaoLang's own
(`front/src/features/editor/engine/`), unrelated to OpenCut's implementation.

```
MIT License

Copyright 2025-2026 OpenCut

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```
