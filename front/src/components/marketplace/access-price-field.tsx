'use client';

import { useTranslations } from 'next-intl';

import { TextInput } from '@/components/ui/field';
import { cn } from '@/lib/cn';

const PRESETS = [0, 10, 50, 200] as const;

/**
 * Integer unlock price. Chips cover the suggested tiers; a custom field
 * still accepts any non-negative integer the API will validate.
 */
export function AccessPriceField({
  value,
  onChange,
  disabled,
  label,
  hint,
}: {
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  label: string;
  hint: string;
}) {
  const t = useTranslations('publishPage');
  const preset = (PRESETS as readonly number[]).includes(value);

  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm font-medium">{label}</p>
      <p className="text-xs leading-relaxed text-muted">{hint}</p>
      <div className="flex flex-wrap gap-2" role="group" aria-label={label}>
        {PRESETS.map((credits) => (
          <button
            key={credits}
            type="button"
            disabled={disabled}
            aria-pressed={value === credits}
            onClick={() => onChange(credits)}
            className={cn(
              'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
              value === credits
                ? 'border-primary bg-primary/12 text-primary'
                : 'border-border text-muted hover:border-border-strong hover:text-text',
              disabled && 'cursor-not-allowed opacity-60',
            )}
          >
            {credits === 0 ? t('accessFree') : String(credits)}
          </button>
        ))}
        <button
          type="button"
          disabled={disabled}
          aria-pressed={!preset}
          onClick={() => {
            if (preset) onChange(value === 0 ? 15 : value);
          }}
          className={cn(
            'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
            !preset
              ? 'border-primary bg-primary/12 text-primary'
              : 'border-border text-muted hover:border-border-strong hover:text-text',
            disabled && 'cursor-not-allowed opacity-60',
          )}
        >
          {t('accessCustom')}
        </button>
      </div>
      {!preset ? (
        <TextInput
          label={label}
          type="number"
          min={0}
          step={1}
          inputMode="numeric"
          disabled={disabled}
          value={Number.isFinite(value) ? String(value) : '0'}
          onChange={(event) => {
            const next = Number.parseInt(event.target.value, 10);
            onChange(Number.isFinite(next) && next >= 0 ? next : 0);
          }}
        />
      ) : null}
    </div>
  );
}
