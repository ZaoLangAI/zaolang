import { describe, expect, it } from 'vitest';

import {
  DEFAULT_CNY_PER_USD,
  cnyToMicroUsd,
  convertDisplayPrice,
  displayToMicroUsd,
  dollarsToMicroUsd,
  microUsdToCny,
  microUsdToDisplay,
  microUsdToDollars,
  parseCnyPerUsd,
} from './micro-usd';

const RATE_7_2 = 7_200_000;

describe('dollarsToMicroUsd', () => {
  it('parses a sub-cent vendor price without a float multiply', () => {
    expect(dollarsToMicroUsd('0.00286')).toBe(2_860);
  });

  it('treats a blank as undeclared (zero), not invalid', () => {
    expect(dollarsToMicroUsd('')).toBe(0);
    expect(dollarsToMicroUsd('   ')).toBe(0);
  });

  it('rejects a lone decimal point and any non-decimal', () => {
    expect(dollarsToMicroUsd('.')).toBeNull();
    expect(dollarsToMicroUsd('-1')).toBeNull();
    expect(dollarsToMicroUsd('$0.02')).toBeNull();
  });

  it('truncates digits beyond micro-USD instead of rounding up', () => {
    // Six fractional digits are kept (`002869`); the seventh `9` is dropped
    // rather than rounding 2869 up to 2870.
    expect(dollarsToMicroUsd('0.0028699')).toBe(2_869);
  });
});

describe('microUsdToDollars', () => {
  it('strips trailing zeros so 2860 edits as 0.00286', () => {
    expect(microUsdToDollars(2_860)).toBe('0.00286');
  });

  it('returns empty for an undeclared price', () => {
    expect(microUsdToDollars(0)).toBe('');
  });
});

describe('parseCnyPerUsd', () => {
  it('parses the form default as 7.2 yuan per dollar', () => {
    expect(parseCnyPerUsd(DEFAULT_CNY_PER_USD)).toBe(RATE_7_2);
  });

  it('rejects empty, zero, and non-positive rates instead of falling back', () => {
    expect(parseCnyPerUsd('')).toBeNull();
    expect(parseCnyPerUsd('0')).toBeNull();
    expect(parseCnyPerUsd('0.0')).toBeNull();
    expect(parseCnyPerUsd('-7.2')).toBeNull();
    expect(parseCnyPerUsd('abc')).toBeNull();
  });
});

describe('cnyToMicroUsd', () => {
  it('converts yuan through the rate with integer division', () => {
    // 0.02 CNY / 7.2 = 0.002777… USD → 2_777 micro-USD (truncated).
    expect(cnyToMicroUsd('0.02', RATE_7_2)).toBe(2_777);
  });

  it('returns zero for a blank yuan field', () => {
    expect(cnyToMicroUsd('', RATE_7_2)).toBe(0);
  });

  it('rejects a non-positive rate and a malformed yuan string', () => {
    expect(cnyToMicroUsd('0.02', 0)).toBeNull();
    expect(cnyToMicroUsd('0.02', -1)).toBeNull();
    expect(cnyToMicroUsd('¥0.02', RATE_7_2)).toBeNull();
  });
});

describe('microUsdToCny', () => {
  it('formats stored micro-USD as an editable yuan string', () => {
    expect(microUsdToCny(2_777, RATE_7_2)).toBe('0.019994');
  });

  it('returns empty for an undeclared price or a broken rate', () => {
    expect(microUsdToCny(0, RATE_7_2)).toBe('');
    expect(microUsdToCny(2_777, 0)).toBe('');
  });
});

describe('displayToMicroUsd / microUsdToDisplay', () => {
  it('ignores the rate in USD and applies it in CNY', () => {
    expect(displayToMicroUsd('0.00286', 'USD', RATE_7_2)).toBe(2_860);
    expect(displayToMicroUsd('0.02', 'CNY', RATE_7_2)).toBe(2_777);
    expect(microUsdToDisplay(2_860, 'USD', RATE_7_2)).toBe('0.00286');
    expect(microUsdToDisplay(2_777, 'CNY', RATE_7_2)).toBe('0.019994');
  });
});

describe('convertDisplayPrice', () => {
  it('rewrites a finished number when the operator toggles currency', () => {
    expect(convertDisplayPrice('0.02', 'CNY', 'USD', RATE_7_2)).toBe('0.002777');
    expect(convertDisplayPrice('0.00286', 'USD', 'CNY', RATE_7_2)).toBe('0.020592');
  });

  it('leaves a mid-keystroke or invalid string alone', () => {
    expect(convertDisplayPrice('0.', 'USD', 'CNY', RATE_7_2)).toBe('0.');
    expect(convertDisplayPrice('abc', 'USD', 'CNY', RATE_7_2)).toBe('abc');
  });

  it('leaves an empty field empty so undeclared stays undeclared', () => {
    expect(convertDisplayPrice('', 'USD', 'CNY', RATE_7_2)).toBe('');
  });
});
