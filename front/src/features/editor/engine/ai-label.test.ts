import { describe, expect, it } from 'vitest';

import { aiLabelFontSize, aiLabelRect } from './compositor';
import { AIGC_CONTENT_PRODUCER, aigcMetadataTags } from './export-runner';

describe('aiLabelRect (visible AI-generated label)', () => {
  it('sits in the top-right corner, inside the frame', () => {
    const rect = aiLabelRect(1080, 1920, 100);
    expect(rect.y).toBeGreaterThan(0);
    expect(rect.x).toBeGreaterThan(1080 / 2);
    expect(rect.x + rect.width).toBeLessThan(1080);
  });

  it('scales its type with the frame height, with a readable floor', () => {
    expect(aiLabelFontSize(1920)).toBeGreaterThan(aiLabelFontSize(720));
    expect(aiLabelFontSize(100)).toBe(12);
  });

  it('never grows wider than the frame', () => {
    const rect = aiLabelRect(320, 180, 10_000);
    expect(rect.x).toBeGreaterThanOrEqual(0);
    expect(rect.x + rect.width).toBeLessThanOrEqual(320);
  });
});

describe('aigcMetadataTags (implicit AI-generated label)', () => {
  it('writes the AIGC JSON with the platform as content producer', () => {
    const exportedAt = new Date('2026-09-14T00:00:00Z');
    const tags = aigcMetadataTags(exportedAt);
    const comment = tags.comment ?? '';

    expect(tags.date).toBe(exportedAt);
    expect(comment.startsWith('AIGC ')).toBe(true);
    expect(JSON.parse(comment.slice('AIGC '.length))).toMatchObject({
      Label: '1',
      ContentProducer: AIGC_CONTENT_PRODUCER,
    });
  });
});
