import { describe, expect, it } from 'vitest';

import { videoFirstFrameSrc } from './video-first-frame';

describe('videoFirstFrameSrc', () => {
  it('keeps the signed query and drops a media fragment', () => {
    expect(videoFirstFrameSrc('http://localhost:9000/zaolang/out/clip.mp4?sig=1')).toBe(
      'http://localhost:9000/zaolang/out/clip.mp4?sig=1',
    );
    expect(videoFirstFrameSrc('http://localhost:9000/zaolang/out/clip.mp4#t=3')).toBe(
      'http://localhost:9000/zaolang/out/clip.mp4',
    );
  });
});
