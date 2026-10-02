import { describe, expect, it } from 'vitest';

import type { ScriptScene } from './api';
import { parseScenePresets } from './scene-heading';

function scene(heading: string, sceneText = ''): Pick<ScriptScene, 'heading' | 'blocks'> {
  return {
    heading,
    blocks: sceneText ? [{ type: 'scene', character: null, text: sceneText }] : [],
  };
}

describe('parseScenePresets', () => {
  it('reads a trailing time token', () => {
    expect(parseScenePresets(scene('便利店 - 夜'))).toEqual({ lighting: 'night_interior' });
    expect(parseScenePresets(scene('第一场 · 便利店 - 日'))).toEqual({ lighting: 'day' });
  });

  it('splits night into interior and exterior', () => {
    expect(parseScenePresets(scene('内景 值班室 夜'))).toEqual({ lighting: 'night_interior' });
    expect(parseScenePresets(scene('外景 天台 夜'))).toEqual({ lighting: 'night_exterior' });
    expect(parseScenePresets(scene('EXT. STREET - NIGHT'))).toEqual({
      lighting: 'night_exterior',
    });
  });

  it('prefers dusk over a bare day marker and reads weather', () => {
    expect(parseScenePresets(scene('海边 黄昏'))).toEqual({ lighting: 'dusk' });
    expect(parseScenePresets(scene('雨巷'))).toEqual({ weather: 'rain' });
  });

  it('falls back to the scene description when the heading names nothing', () => {
    expect(parseScenePresets(scene('内景 值班室', '深夜，只有一盏台灯亮着，窗外下雨'))).toEqual({
      lighting: 'night_interior',
      weather: 'rain',
    });
    expect(parseScenePresets(scene('公寓客厅', '客厅里堆着杂物'))).toEqual({});
  });

  it('does not read a bare 日 inside another word', () => {
    expect(parseScenePresets(scene('日料店'))).toEqual({});
  });
});
