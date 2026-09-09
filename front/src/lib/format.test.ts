import { describe, expect, it } from 'vitest';

import { formatDate, formatDateTime, isLocalDateTime, localDateTimeToIso } from './format';

describe('formatDateTime', () => {
  it('shows China wall clock for a UTC instant in every locale', () => {
    expect(formatDateTime('2026-09-02T05:35:39.604492+00:00', 'zh-CN')).toContain('13:35');
    expect(formatDateTime('2026-09-02T05:35:39.604492Z', 'en')).toMatch(/1:35/);
    expect(formatDateTime('2026-09-02T05:35:39.604492Z', 'ja')).toContain('13:35');
  });

  it('treats a naive API timestamp as UTC, not the browser zone', () => {
    expect(formatDateTime('2026-09-02T05:35:39.604492', 'zh-CN')).toContain('13:35');
  });
});

describe('formatDate', () => {
  it('rolls a late UTC afternoon into the next China calendar day', () => {
    expect(formatDate('2026-09-02T16:00:00.000Z', 'zh-CN')).toContain('3');
  });
});

describe('localDateTimeToIso', () => {
  it('stamps Asia/Shanghai on a datetime-local value', () => {
    expect(localDateTimeToIso('2026-09-02T12:31', 'Asia/Shanghai')).toBe(
      '2026-09-02T12:31:00+08:00',
    );
  });

  it('leaves already-offset strings alone', () => {
    expect(isLocalDateTime('2026-09-02T12:31:00+08:00')).toBe(false);
    expect(localDateTimeToIso('2026-09-02T12:31:00+08:00', 'Asia/Shanghai')).toBe(
      '2026-09-02T12:31:00+08:00',
    );
  });
});
