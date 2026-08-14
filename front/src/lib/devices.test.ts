import { describe, expect, it } from 'vitest';

import {
  DEFAULT_DEVICE_ID,
  deviceById,
  fitWithinReferenceCanvas,
  parseCssRatio,
  PORTRAIT_STAGE_MAX_HEIGHT,
  REFERENCE_CANVAS,
} from './devices';

describe('device catalogue', () => {
  it('defaults to iPhone 17', () => {
    expect(DEFAULT_DEVICE_ID).toBe('iphone-17');
    expect(deviceById('missing').id).toBe('iphone-17');
    expect(deviceById('iphone-17')).toMatchObject(REFERENCE_CANVAS);
  });
});

describe('parseCssRatio', () => {
  it('reads CSS and slash forms', () => {
    expect(parseCssRatio('16 / 9')).toBeCloseTo(16 / 9);
    expect(parseCssRatio('9/16')).toBeCloseTo(9 / 16);
    expect(parseCssRatio('1.5')).toBe(1.5);
    expect(parseCssRatio('0')).toBeNull();
    expect(parseCssRatio(null)).toBeNull();
  });
});

describe('fitWithinReferenceCanvas', () => {
  it('lets 16:9 use the full column width', () => {
    const box = fitWithinReferenceCanvas({
      ratio: 16 / 9,
      availWidth: 800,
      availHeight: 874,
    });
    expect(box.width).toBeCloseTo(800);
    expect(box.height).toBeCloseTo(800 * (9 / 16));
  });

  it('lets 1:1 use the full column width while staying square', () => {
    const box = fitWithinReferenceCanvas({
      ratio: 1,
      availWidth: 800,
      availHeight: 874,
    });
    expect(box.width).toBeCloseTo(800);
    expect(box.height).toBeCloseTo(800);
  });

  it('keeps 9:16 phone-sized in a wide desktop column', () => {
    const box = fitWithinReferenceCanvas({
      ratio: 9 / 16,
      availWidth: 768,
      availHeight: 874,
    });
    expect(box.height).toBeCloseTo(PORTRAIT_STAGE_MAX_HEIGHT);
    expect(box.width).toBeCloseTo(PORTRAIT_STAGE_MAX_HEIGHT * (9 / 16));
    expect(box.width).toBeLessThanOrEqual(REFERENCE_CANVAS.width);
  });

  it('lets 9:16 use the column width on a phone-sized parent', () => {
    const box = fitWithinReferenceCanvas({
      ratio: 9 / 16,
      availWidth: 390,
      availHeight: 700,
    });
    expect(box.width).toBeCloseTo(390);
    expect(box.height).toBeCloseTo(390 * (16 / 9));
  });

  it('scales a tall clip down when the parent is shorter than the portrait cap', () => {
    const box = fitWithinReferenceCanvas({
      ratio: 9 / 16,
      availWidth: 768,
      availHeight: 400,
    });
    expect(box.height).toBeCloseTo(400);
    expect(box.width).toBeCloseTo(400 * (9 / 16));
  });
});
