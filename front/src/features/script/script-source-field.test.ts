import { describe, expect, it } from 'vitest';

import { composeScriptIdea } from './script-source-field';

describe('composeScriptIdea', () => {
  it('uses the typed idea when nothing was extracted', () => {
    expect(composeScriptIdea('  深夜便利店  ', '')).toBe('深夜便利店');
  });

  it('uses the extract when the prompt is empty', () => {
    expect(composeScriptIdea('   ', '第一场 夜')).toBe('第一场 夜');
  });

  it('puts the typed note above the extracted source', () => {
    expect(composeScriptIdea('更悬疑一点', '第一场 夜')).toBe('更悬疑一点\n\n第一场 夜');
  });
});
