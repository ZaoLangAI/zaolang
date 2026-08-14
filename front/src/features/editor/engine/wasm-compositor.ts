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
