import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SequentialExportRunner, fitExportCanvas } from './export-runner';
import { TICKS_PER_SECOND } from './ports';

const BASE_SPEC = {
  profile_key: 'test',
  width: 1080,
  height: 1920,
  fps_num: 30,
  fps_den: 1,
  format: 'mp4' as const,
  caption_language: null,
  caption_mode: 'none' as const,
  max_duration_ticks: 10 * TICKS_PER_SECOND,
};

describe('SequentialExportRunner.preflight', () => {
  let originalUserAgent: string;
  let originalVideoEncoder: unknown;

  beforeEach(() => {
    originalUserAgent = navigator.userAgent;
    originalVideoEncoder = (globalThis as Record<string, unknown>).VideoEncoder;
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
      configurable: true,
    });
    (globalThis as Record<string, unknown>).VideoEncoder = class {};
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'userAgent', { value: originalUserAgent, configurable: true });
    (globalThis as Record<string, unknown>).VideoEncoder = originalVideoEncoder;
    vi.restoreAllMocks();
  });

  it('accepts a spec within every cap on desktop Chrome with WebCodecs', async () => {
    const report = await new SequentialExportRunner().preflight(BASE_SPEC);
    expect(report.ok).toBe(true);
    expect(report.reasons).toEqual([]);
  });

  it('accepts 4K and 60s on desktop Chrome with WebCodecs', async () => {
    const report = await new SequentialExportRunner().preflight({
      ...BASE_SPEC,
      width: 3840,
      height: 2160,
      max_duration_ticks: 60 * TICKS_PER_SECOND,
    });
    expect(report.ok).toBe(true);
    expect(report.reasons).toEqual([]);
  });

  it('rejects a non-Chrome/Edge browser', async () => {
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
      configurable: true,
    });
    const report = await new SequentialExportRunner().preflight(BASE_SPEC);
    expect(report.reasons).toContain('browser');
  });

  it('rejects a mobile Chrome user agent', async () => {
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36',
      configurable: true,
    });
    const report = await new SequentialExportRunner().preflight(BASE_SPEC);
    expect(report.reasons).toContain('browser');
  });

  it('rejects when WebCodecs is unavailable', async () => {
    delete (globalThis as Record<string, unknown>).VideoEncoder;
    const report = await new SequentialExportRunner().preflight(BASE_SPEC);
    expect(report.reasons).toContain('webcodecs');
  });
});

describe('fitExportCanvas', () => {
  it('keeps a 9:16 spec at even original pixels', () => {
    expect(fitExportCanvas(1080, 1920)).toEqual({ width: 1080, height: 1920 });
  });

  it('keeps a 16:9 spec at even original pixels', () => {
    expect(fitExportCanvas(1920, 1080)).toEqual({ width: 1920, height: 1080 });
  });

  it('rounds odd edges down to even without flipping orientation', () => {
    expect(fitExportCanvas(1081, 1921)).toEqual({ width: 1080, height: 1920 });
    const portrait = fitExportCanvas(1080, 1920);
    expect(portrait.height).toBeGreaterThan(portrait.width);
    const landscape = fitExportCanvas(1920, 1080);
    expect(landscape.width).toBeGreaterThan(landscape.height);
  });
});
