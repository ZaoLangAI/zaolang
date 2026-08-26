# Third-party notices

The layout and component structure of this directory (`front/src/features/editor/studio/`)
is adapted from **OpenCut** (`opencut-app/opencut-classic`), specifically:

- `apps/web/src/app/editor/[project_id]/page.tsx` — the overall shell / resizable-panel
  layout → `studio-shell.tsx`
- `apps/web/src/components/editor/editor-header.tsx` → `editor-header.tsx`
- `apps/web/src/components/editor/panels/assets/index.tsx` and `tabbar.tsx` — the tab bar +
  view-map pattern → `media-library-panel.tsx`
- `apps/web/src/components/editor/panels/properties/index.tsx` and `empty-view.tsx` —
  the properties-panel shell → `properties-panel.tsx`

Only UI shell/layout/presentational structure was adapted. None of OpenCut's own timeline
data model, undo/redo command stack, canvas/WASM compositor, or rendering/export code was
used — this editor's timeline, preview, and export logic are ZaoLang's own
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
