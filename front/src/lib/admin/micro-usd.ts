/**
 * Converts between the dollars an operator types and the micro-USD integers
 * the API speaks.
 *
 * Micro-USD (1e-6 USD) exists because vendor list prices go far below a cent:
 * $0.00286 per image is 2_860, whereas cents would round it to zero. The
 * conversion is done on the decimal string rather than with `value * 1e6`,
 * because `0.00286 * 1e6` is 2859.9999999999995 in IEEE floats and would
 * silently shave a fraction off every price an operator saves.
 */

const MICRO_DIGITS = 6;

/**
 * Parses a dollar amount into micro-USD. Returns `null` for anything that is
 * not a plain non-negative decimal, so a typo becomes a validation error
 * rather than a zero price that reads as "free".
 */
export function dollarsToMicroUsd(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) return 0;
  if (!/^\d*\.?\d*$/.test(trimmed) || trimmed === '.') return null;

  const [whole = '', fraction = ''] = trimmed.split('.');
  // Digits beyond micro-USD cannot be represented; truncating instead of
  // rounding keeps the saved price from exceeding what was typed.
  const micros = fraction.slice(0, MICRO_DIGITS).padEnd(MICRO_DIGITS, '0');
  const value = Number(`${whole || '0'}${micros}`);
  return Number.isSafeInteger(value) ? value : null;
}

/** Formats micro-USD back into an editable dollar string, without trailing
 * zeros — `2_860` becomes `"0.00286"`, not `"0.002860"`. */
export function microUsdToDollars(value: number): string {
  if (!value) return '';
  const negative = value < 0;
  const digits = String(Math.abs(value)).padStart(MICRO_DIGITS + 1, '0');
  const whole = digits.slice(0, -MICRO_DIGITS);
  const fraction = digits.slice(-MICRO_DIGITS).replace(/0+$/, '');
  return `${negative ? '-' : ''}${whole}${fraction ? `.${fraction}` : ''}`;
}

/** Display form for a spend total, e.g. `"$12.34"`. Spend is summed over many
 * calls, so two decimals is the right resolution here — unlike a unit price,
 * which needs all six. */
export function formatMicroUsd(value: number, fractionDigits = 2): string {
  return `$${(value / 1_000_000).toFixed(fractionDigits)}`;
}
