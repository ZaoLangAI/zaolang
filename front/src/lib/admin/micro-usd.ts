/**
 * Converts between the dollars an operator types and the micro-USD integers
 * the API speaks.
 *
 * Micro-USD (1e-6 USD) exists because vendor list prices go far below a cent:
 * $0.00286 per image is 2_860, whereas cents would round it to zero. The
 * conversion is done on the decimal string rather than with `value * 1e6`,
 * because `0.00286 * 1e6` is 2859.9999999999995 in IEEE floats and would
 * silently shave a fraction off every price an operator saves.
 *
 * CNY input is a form convenience only: the operator types yuan, we convert
 * through an explicit CNY-per-USD rate (also a decimal string), and the API
 * still receives micro-USD. The rate is never defaulted on a typo — an empty
 * or non-positive rate is a validation error, same as a malformed price.
 */

const MICRO_DIGITS = 6;
const MICRO = 1_000_000;

/** Default CNY-per-USD rate the admin form seeds. Not a fallback for a
 * missing or invalid typed rate — `parseCnyPerUsd` still returns `null`
 * for those, so a save cannot silently use this number. */
export const DEFAULT_CNY_PER_USD = '7.2';

export type PriceInputCurrency = 'USD' | 'CNY';

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

/**
 * Parses a CNY-per-USD rate into micro-CNY (the same 6-decimal scale as a
 * price). Empty, zero, negative, and non-decimals are `null` — never coerced
 * to `DEFAULT_CNY_PER_USD`.
 */
export function parseCnyPerUsd(input: string): number | null {
  const micro = dollarsToMicroUsd(input);
  if (micro === null || micro <= 0) return null;
  return micro;
}

/**
 * Yuan typed by the operator → micro-USD, using `rateMicro` from
 * `parseCnyPerUsd`. Truncates toward zero so the saved USD price cannot
 * exceed what the typed yuan / rate would imply.
 */
export function cnyToMicroUsd(cnyInput: string, rateMicro: number): number | null {
  if (rateMicro <= 0) return null;
  const microCny = dollarsToMicroUsd(cnyInput);
  if (microCny === null) return null;
  if (microCny === 0) return 0;
  return Number((BigInt(microCny) * BigInt(MICRO)) / BigInt(rateMicro));
}

/** Inverse of `cnyToMicroUsd` for the form: stored micro-USD → editable yuan
 * string at the current rate. Empty when the stored price is undeclared. */
export function microUsdToCny(microUsd: number, rateMicro: number): string {
  if (!microUsd) return '';
  if (rateMicro <= 0) return '';
  const microCny = Number((BigInt(microUsd) * BigInt(rateMicro)) / BigInt(MICRO));
  return microUsdToDollars(microCny);
}

/**
 * Display-currency string → micro-USD. `USD` ignores `rateMicro`; `CNY`
 * requires a positive rate already parsed by the caller.
 */
export function displayToMicroUsd(
  input: string,
  currency: PriceInputCurrency,
  rateMicro: number,
): number | null {
  return currency === 'USD' ? dollarsToMicroUsd(input) : cnyToMicroUsd(input, rateMicro);
}

/**
 * Stored micro-USD → display-currency string. Used when opening a form in
 * USD (exact) and when toggling USD → CNY (converted).
 */
export function microUsdToDisplay(
  microUsd: number,
  currency: PriceInputCurrency,
  rateMicro: number,
): string {
  return currency === 'USD' ? microUsdToDollars(microUsd) : microUsdToCny(microUsd, rateMicro);
}

/**
 * Rewrites a typed price from one display currency to the other. Invalid or
 * empty input is returned unchanged so a mid-keystroke `"0."` is not erased
 * and a typo is not silently replaced.
 */
export function convertDisplayPrice(
  input: string,
  from: PriceInputCurrency,
  to: PriceInputCurrency,
  rateMicro: number,
): string {
  if (from === to) return input;
  const trimmed = input.trim();
  if (!trimmed) return input;
  // `"0."` parses as zero under `dollarsToMicroUsd`, and formatting zero
  // yields `""` — the same caret-fight the form already avoids on
  // keystroke. A trailing point is mid-edit, not a finished number.
  if (trimmed.endsWith('.')) return input;
  const micro = displayToMicroUsd(input, from, rateMicro);
  if (micro === null) return input;
  return microUsdToDisplay(micro, to, rateMicro);
}
