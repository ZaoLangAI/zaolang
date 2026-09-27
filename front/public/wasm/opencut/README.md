# OpenCut classic WASM compositor

Rebuilt (`wasm-pack build rust/wasm --target web`) from
[OpenCut-app/opencut-classic](https://github.com/OpenCut-app/opencut-classic)
at commit `cf5e79e919144200294fb9fed22a222592a0aeea` (archived, MIT licensed —
see `LICENSE` in this directory). Source is vendored at
`third_party/opencut-classic/` in this repository (Rust workspace only),
pinned to the same commit.

Loaded at runtime by `front/src/features/editor/engine/wasm-compositor.ts`.
Never claim it is present without checking: `loadModule()` returns `null` on
any fetch/instantiate failure, and every caller falls back to the Canvas2D
compositor in `engine/compositor.ts` when that happens.

**Effects/masks**: the binary exports working `applyEffectPasses`/
`applyMaskFeather` (confirmed by direct empirical test — upload a texture,
run a pass, read the pixels back), but at this pinned commit the underlying
Rust pipeline (`third_party/opencut-classic/rust/crates/effects/src/pipeline.rs`)
has only `gaussian-blur` actually registered as a shader. `engine/wasm-compositor.ts`'s
`applyBlur` uses it; every other effect type is a Canvas2D `ctx.filter`
(`engine/effects.ts`) regardless of whether this module loaded, and masks
always use Canvas2D feathering rather than `applyMaskFeather` (that call
feathers luminance, not alpha — using it for real-time masking would need a
per-frame CPU readback this module's contract doesn't need for anything
else). Don't assume a new effect type has GPU support here without checking
the pipeline source the same way.
