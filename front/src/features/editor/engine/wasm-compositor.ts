/**
 * Real OpenCut classic Rust/WASM compositor, rebuilt from
 * github.com/OpenCut-app/opencut-classic @ cf5e79e919144200294fb9fed22a222592a0aeea
 * (MIT licensed — see /wasm/opencut/LICENSE). Renders the active video layer
 * through wgpu (WebGPU with a WebGL2 fallback, both handled inside the
 * module); captions/brand overlay stay on the caller's 2D canvas, drawn on
 * top of this module's output. Any init/render failure degrades to the
 * existing Canvas2D-only path in `compositor.ts` — this module never throws
 * out to callers, it returns `null`/`false` instead.
 */

interface FrameLayerTransform {
  centerX: number;
  centerY: number;
  width: number;
  height: number;
  rotationDegrees: number;
  flipX: boolean;
  flipY: boolean;
}

interface OpencutWasmModule {
  initializeGpu(): Promise<void>;
  initCompositor(width: number, height: number): void;
  resizeCompositor(width: number, height: number): void;
  getCompositorCanvas(): HTMLCanvasElement;
  uploadTexture(options: {
    id: string;
    source: OffscreenCanvas;
    width: number;
    height: number;
  }): void;
  releaseTexture(id: string): void;
  renderFrame(options: unknown): void;
  applyEffectPasses(options: {
    source: OffscreenCanvas;
    width: number;
    height: number;
    passes: Array<{ shader: string; uniforms: Array<{ name: string; value: number[] }> }>;
  }): OffscreenCanvas;
  applyMaskFeather(options: {
    mask: OffscreenCanvas;
    width: number;
    height: number;
    feather: number;
  }): OffscreenCanvas;
}

const WASM_JS_URL = '/wasm/opencut/opencut_wasm.js';
const WASM_BINARY_URL = '/wasm/opencut/opencut_wasm_bg.wasm';

let modulePromise: Promise<OpencutWasmModule | null> | null = null;

async function loadModule(): Promise<OpencutWasmModule | null> {
  try {
    // Dynamic string import of a public static asset — not a bundler module,
    // so bundlers must not try to resolve/transform it at build time.
    const mod = (await import(/* webpackIgnore: true */ WASM_JS_URL)) as {
      default: (input: string) => Promise<unknown>;
    } & OpencutWasmModule;
    await mod.default(WASM_BINARY_URL);
    return mod;
  } catch {
    return null;
  }
}

export class WasmCompositor {
  private disposed = false;

  private constructor(
    private readonly wasmModule: OpencutWasmModule,
    private width: number,
    private height: number,
  ) {}

  static async create(width: number, height: number): Promise<WasmCompositor | null> {
    modulePromise ??= loadModule();
    const wasmModule = await modulePromise;
    if (!wasmModule) return null;
    try {
      await wasmModule.initializeGpu();
      wasmModule.initCompositor(width, height);
      return new WasmCompositor(wasmModule, width, height);
    } catch {
      return null;
    }
  }

  /** The GPU-backed canvas the module renders into; draw this onto the app's 2D canvas. */
  get canvas(): HTMLCanvasElement | null {
    try {
      return this.wasmModule.getCompositorCanvas();
    } catch {
      return null;
    }
  }

  resize(width: number, height: number): void {
    if (this.disposed || (this.width === width && this.height === height)) return;
    try {
      this.wasmModule.resizeCompositor(width, height);
      this.width = width;
      this.height = height;
    } catch {
      // Leave stale dimensions; next renderVideoFrame call will just fail
      // and the caller falls back to Canvas2D.
    }
  }

  /**
   * Real GPU Gaussian blur via the vendored module's `applyEffectPasses`
   * (confirmed working by direct empirical test — see
   * `zaolang-editor-drama`'s effects invariant; `gaussian-blur` is, at this
   * pinned commit, the *only* shader actually registered in the Rust
   * pipeline, which is why blur alone gets this treatment and every other
   * effect stays a plain Canvas2D `ctx.filter`). Splits into multiple H+V
   * pass pairs at high sigma, mirroring OpenCut's own `buildGaussianBlurPasses`
   * — a single pass's kernel can't cover a very wide blur without banding.
   * Returns null on any failure so the caller falls back to a CSS blur.
   */
  applyBlur(source: OffscreenCanvas, sigmaX: number, sigmaY: number): OffscreenCanvas | null {
    if (this.disposed) return null;
    const maxSigma = Math.max(sigmaX, sigmaY);
    if (maxSigma < 0.001) return source;
    const MAX_SINGLE_PASS_SIGMA = 10;
    const MAX_STEP = 4;
    const MAX_EFFECTIVE_SIGMA = MAX_SINGLE_PASS_SIGMA * MAX_STEP;
    const MAX_ITERATIONS = 8;
    const iterations = Math.min(
      MAX_ITERATIONS,
      Math.max(1, Math.ceil((maxSigma * maxSigma) / (MAX_EFFECTIVE_SIGMA * MAX_EFFECTIVE_SIGMA))),
    );
    const perPassSigmaX = sigmaX / Math.sqrt(iterations);
    const perPassSigmaY = sigmaY / Math.sqrt(iterations);
    const stepX = Math.max(1, perPassSigmaX / MAX_SINGLE_PASS_SIGMA);
    const stepY = Math.max(1, perPassSigmaY / MAX_SINGLE_PASS_SIGMA);
    const passes: Array<{ shader: string; uniforms: Array<{ name: string; value: number[] }> }> = [];
    for (let i = 0; i < iterations; i += 1) {
      passes.push({
        shader: 'gaussian-blur',
        uniforms: [
          { name: 'u_sigma', value: [perPassSigmaX] },
          { name: 'u_step', value: [stepX] },
          { name: 'u_direction', value: [1, 0] },
        ],
      });
      passes.push({
        shader: 'gaussian-blur',
        uniforms: [
          { name: 'u_sigma', value: [perPassSigmaY] },
          { name: 'u_step', value: [stepY] },
          { name: 'u_direction', value: [0, 1] },
        ],
      });
    }
    try {
      return this.wasmModule.applyEffectPasses({ source, width: this.width, height: this.height, passes });
    } catch {
      return null;
    }
  }

  /**
   * Uploads `source` (already cover-fit to this compositor's width/height by
   * the caller) as the sole full-frame layer and renders it. Returns false
   * on any failure so the caller can fall back to Canvas2D for this frame.
   */
  renderVideoFrame(source: OffscreenCanvas): boolean {
    if (this.disposed) return false;
    const textureId = 'clip';
    try {
      this.wasmModule.uploadTexture({
        id: textureId,
        source,
        width: this.width,
        height: this.height,
      });
      const transform: FrameLayerTransform = {
        centerX: this.width / 2,
        centerY: this.height / 2,
        width: this.width,
        height: this.height,
        rotationDegrees: 0,
        flipX: false,
        flipY: false,
      };
      this.wasmModule.renderFrame({
        width: this.width,
        height: this.height,
        clear: { color: [0, 0, 0, 1] },
        items: [
          {
            type: 'layer',
            textureId,
            transform,
            opacity: 1,
            blendMode: 'normal',
            effectPassGroups: [],
            mask: null,
          },
        ],
      });
      return true;
    } catch {
      return false;
    } finally {
      try {
        this.wasmModule.releaseTexture(textureId);
      } catch {
        // best-effort cleanup only
      }
    }
  }

  dispose(): void {
    this.disposed = true;
  }
}
