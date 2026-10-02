import { describe, expect, it } from 'vitest';

import { recorderMimeType, segmentClipName } from './render-segment';

describe('recorderMimeType', () => {
  it('prefers H.264 MP4 when the recorder offers it', () => {
    expect(recorderMimeType(() => true)).toBe('video/mp4;codecs=avc1');
  });

  it('falls back to WebM where MP4 recording is unsupported', () => {
    expect(recorderMimeType((type) => type.startsWith('video/webm'))).toBe('video/webm;codecs=vp9');
  });

  it('reports nothing when the browser cannot record', () => {
    expect(recorderMimeType(() => false)).toBeNull();
  });
});

describe('segmentClipName', () => {
  it('uses the encoded container as the extension', () => {
    expect(segmentClipName('客厅 夜#1')).toBe('blocking_客厅_夜#1.mp4');
    expect(segmentClipName('客厅#2', 'webm')).toBe('blocking_客厅#2.webm');
  });
});
