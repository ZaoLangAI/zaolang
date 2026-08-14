# OpenCut classic WASM compositor

Rebuilt (`wasm-pack build rust/wasm --target web`) from
[OpenCut-app/opencut-classic](https://github.com/OpenCut-app/opencut-classic)
at commit `cf5e79e919144200294fb9fed22a222592a0aeea` (archived, MIT licensed —
see `LICENSE` in this directory). Source is vendored at
`third_party/opencut-classic/` in this repository, pinned to the same commit.

Loaded at runtime by `front/src/features/editor/engine/wasm-compositor.ts`.
Never claim it is present without checking: `loadModule()` returns `null` on
any fetch/instantiate failure, and every caller falls back to the Canvas2D
compositor in `engine/compositor.ts` when that happens.
