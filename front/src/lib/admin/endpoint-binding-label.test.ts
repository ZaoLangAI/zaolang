import { describe, expect, it } from 'vitest';

import { endpointBindingLabel } from './endpoint-binding-label';

describe('endpointBindingLabel', () => {
  it('tags only endpoints that declare image input', () => {
    expect(
      endpointBindingLabel(
        { name: 'GLM', model: 'glm-5.3-flash', input_modalities: ['text', 'image', 'video'] },
        '识图',
      ),
    ).toBe('GLM · glm-5.3-flash · 识图');
    expect(
      endpointBindingLabel(
        { name: 'Qwen', model: 'qwen3.8-flash', input_modalities: ['text'] },
        '识图',
      ),
    ).toBe('Qwen · qwen3.8-flash');
  });

  it('falls back to the name when no model is declared', () => {
    expect(endpointBindingLabel({ name: 'Bare', model: '' }, '识图')).toBe('Bare');
  });
});
