/* tslint:disable */
/* eslint-disable */
export interface FloorToFrameOptions {
    time: MediaTime;
    rate: FrameRate;
}

export interface FormatTimecodeOptions {
    time: MediaTime;
    format?: TimeCodeFormat;
    rate?: FrameRate;
}

export interface FrameRate {
    numerator: number;
    denominator: number;
}

export interface GuessTimecodeFormatOptions {
    timeCode: string;
}

export interface IsFrameAlignedOptions {
    time: MediaTime;
    rate: FrameRate;
}

export interface LastFrameTimeOptions {
    duration: MediaTime;
    rate: FrameRate;
}

export interface MediaTimeAddOptions {
    lhs: MediaTime;
    rhs: MediaTime;
}

export interface MediaTimeClampOptions {
    time: MediaTime;
    min: MediaTime;
    max: MediaTime;
}

export interface MediaTimeFromFrameOptions {
    frame: number;
    rate: FrameRate;
}

export interface MediaTimeFromSecondsOptions {
    seconds: number;
}

export interface MediaTimeMaxOptions {
    lhs: MediaTime;
    rhs: MediaTime;
}

export interface MediaTimeMinOptions {
    lhs: MediaTime;
    rhs: MediaTime;
}

export interface MediaTimeSubOptions {
    lhs: MediaTime;
    rhs: MediaTime;
}

export interface MediaTimeToFrameOptions {
    time: MediaTime;
    rate: FrameRate;
}

export interface MediaTimeToSecondsOptions {
    time: MediaTime;
}

export interface ParseTimecodeOptions {
    timeCode: string;
    format?: TimeCodeFormat;
    rate?: FrameRate;
}

export interface RoundToFrameOptions {
    time: MediaTime;
    rate: FrameRate;
}

export interface SnappedSeekTimeOptions {
    time: MediaTime;
    duration: MediaTime;
    rate: FrameRate;
}

export type MediaTime = number;

export type TimeCodeFormat = "MM:SS" | "HH:MM:SS" | "HH:MM:SS:CS" | "HH:MM:SS:FF";


export function TICKS_PER_SECOND(): number;

export function applyEffectPasses(options: any): OffscreenCanvas;

export function applyMaskFeather(options: any): OffscreenCanvas;

export function floorToFrame(arg0: FloorToFrameOptions): MediaTime | undefined;

export function formatTimecode(arg0: FormatTimecodeOptions): string | undefined;

export function getCompositorCanvas(): HTMLCanvasElement;

export function getLastFrameProfile(): Array<any>;

export function guessTimecodeFormat(arg0: GuessTimecodeFormatOptions): TimeCodeFormat | undefined;

export function initCompositor(width: number, height: number): void;

export function initializeGpu(): Promise<void>;

export function isFrameAligned(arg0: IsFrameAlignedOptions): boolean | undefined;

export function lastFrameTime(arg0: LastFrameTimeOptions): MediaTime | undefined;

export function mediaTimeAdd(arg0: MediaTimeAddOptions): MediaTime;

export function mediaTimeClamp(arg0: MediaTimeClampOptions): MediaTime;

export function mediaTimeFromFrame(arg0: MediaTimeFromFrameOptions): MediaTime | undefined;

export function mediaTimeFromSeconds(arg0: MediaTimeFromSecondsOptions): MediaTime | undefined;

export function mediaTimeMax(arg0: MediaTimeMaxOptions): MediaTime;

export function mediaTimeMin(arg0: MediaTimeMinOptions): MediaTime;

export function mediaTimeSub(arg0: MediaTimeSubOptions): MediaTime;

export function mediaTimeToFrame(arg0: MediaTimeToFrameOptions): bigint | undefined;

export function mediaTimeToSeconds(arg0: MediaTimeToSecondsOptions): number;

export function parseTimecode(arg0: ParseTimecodeOptions): MediaTime | undefined;

export function releaseTexture(id: string): void;

export function renderFrame(options: any): void;

export function resizeCompositor(width: number, height: number): void;

export function roundToFrame(arg0: RoundToFrameOptions): MediaTime | undefined;

export function snappedSeekTime(arg0: SnappedSeekTimeOptions): MediaTime | undefined;

export function uploadTexture(options: any): void;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly initializeGpu: () => any;
    readonly getCompositorCanvas: () => [number, number, number];
    readonly initCompositor: (a: number, b: number) => [number, number];
    readonly releaseTexture: (a: number, b: number) => [number, number];
    readonly renderFrame: (a: any) => [number, number];
    readonly resizeCompositor: (a: number, b: number) => [number, number];
    readonly uploadTexture: (a: any) => [number, number];
    readonly applyEffectPasses: (a: any) => [number, number, number];
    readonly getLastFrameProfile: () => any;
    readonly applyMaskFeather: (a: any) => [number, number, number];
    readonly TICKS_PER_SECOND: () => number;
    readonly floorToFrame: (a: any) => any;
    readonly isFrameAligned: (a: any) => number;
    readonly lastFrameTime: (a: any) => any;
    readonly mediaTimeAdd: (a: any) => any;
    readonly mediaTimeClamp: (a: any) => any;
    readonly mediaTimeFromFrame: (a: any) => any;
    readonly mediaTimeFromSeconds: (a: any) => any;
    readonly mediaTimeMax: (a: any) => any;
    readonly mediaTimeMin: (a: any) => any;
    readonly mediaTimeSub: (a: any) => any;
    readonly mediaTimeToFrame: (a: any) => [number, bigint];
    readonly mediaTimeToSeconds: (a: any) => number;
    readonly roundToFrame: (a: any) => any;
    readonly snappedSeekTime: (a: any) => any;
    readonly formatTimecode: (a: any) => [number, number];
    readonly guessTimecodeFormat: (a: any) => any;
    readonly parseTimecode: (a: any) => any;
    readonly wasm_bindgen_e463fd838255edfd___convert__closures_____invoke___wasm_bindgen_e463fd838255edfd___JsValue__core_9b3796e30d99ddb7___result__Result_____wasm_bindgen_e463fd838255edfd___JsError___true_: (a: number, b: number, c: any) => [number, number];
    readonly wasm_bindgen_e463fd838255edfd___convert__closures_____invoke___js_sys_cc7c71412af579c2___Function_fn_wasm_bindgen_e463fd838255edfd___JsValue_____wasm_bindgen_e463fd838255edfd___sys__Undefined___js_sys_cc7c71412af579c2___Function_fn_wasm_bindgen_e463fd838255edfd___JsValue_____wasm_bindgen_e463fd838255edfd___sys__Undefined_______true_: (a: number, b: number, c: any, d: any) => void;
    readonly wasm_bindgen_e463fd838255edfd___convert__closures_____invoke___wasm_bindgen_e463fd838255edfd___JsValue______true_: (a: number, b: number, c: any) => void;
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_exn_store: (a: number) => void;
    readonly __externref_table_alloc: () => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __wbindgen_destroy_closure: (a: number, b: number) => void;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
