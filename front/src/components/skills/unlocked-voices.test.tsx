import { NextIntlClientProvider } from 'next-intl';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import messages from '@/i18n/messages/zh-CN.json';
import type { AssetVariant, CharacterVoice } from '@/lib/api/types';

import { UnlockedVoicesSection } from './unlocked-voices';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const voice = (overrides: Partial<CharacterVoice>) =>
  ({
    id: 'chv_1',
    name: '日常',
    source: 'preset',
    model: 'tts-pro',
    voice: '柔美女友',
    params: { speed: null, emotion: null },
    attributes: { age_stage: 'youth', emotion: null, use: 'dialogue', custom: [] },
    sample: null,
    preview: { asset_id: 'ast_p', url: 'https://cdn/p.mp3' },
    preview_text: null,
    is_default: true,
    look_ids: ['skv_1'],
    ...overrides,
  }) as CharacterVoice;

function render(voices: CharacterVoice[]) {
  act(() =>
    root.render(
      <NextIntlClientProvider locale="zh-CN" messages={messages}>
        <UnlockedVoicesSection
          voices={voices}
          looks={[{ id: 'skv_1', name: '战甲' } as AssetVariant]}
        />
      </NextIntlClientProvider>,
    ),
  );
}

describe('UnlockedVoicesSection', () => {
  it('lists each voice with its kind, model, use, looks and preview', () => {
    render([
      voice({}),
      voice({
        id: 'chv_2',
        name: '旁白克隆',
        source: 'clone',
        model: null,
        voice: null,
        attributes: { age_stage: null, emotion: null, use: 'narration', custom: [] },
        preview: null,
        is_default: false,
        look_ids: [],
      }),
    ]);
    const rows = [...container.querySelectorAll('li')].map((li) => li.textContent);
    expect(rows[0]).toContain('日常');
    expect(rows[0]).toContain('默认');
    expect(rows[0]).toContain('预设音色 · tts-pro · 柔美女友');
    expect(rows[0]).toContain('对白');
    expect(rows[0]).toContain('战甲');
    expect(container.querySelectorAll('li')[0]!.querySelector('button')).not.toBeNull();
    expect(rows[1]).toContain('克隆音色 · 旁白');
    expect(rows[1]).toContain('还没有试听');
  });

  it('renders nothing without voices', () => {
    render([]);
    expect(container.innerHTML).toBe('');
  });
});
