'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { ErrorNotice, SectionHeading } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import { formatCount } from '@/lib/format';

/** `GET /v1/credits/balance` / `PUT /v1/credits/spend-limit`. */
interface SpendBalance {
  monthly_spend_limit: number | null;
  period_spent: number;
  period_remaining: number | null;
}

/**
 * The user's own monthly cap on generation spend. The ledger enforces it
 * inside the same conditional UPDATE as the balance, so a batch or a canvas
 * run stops at the cap instead of draining the account. Empty = no cap.
 */
export function SpendLimitForm() {
  const t = useTranslations('billingPage');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const [balance, setBalance] = useState<SpendBalance | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .get<SpendBalance>('/v1/credits/balance')
      .then((next) => {
        if (cancelled) return;
        setBalance(next);
        setDraft(next.monthly_spend_limit ? String(next.monthly_spend_limit) : '');
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async (limit: number | null) => {
    setBusy(true);
    setError(null);
    try {
      const next = await api.put<SpendBalance>('/v1/credits/spend-limit', {
        monthly_spend_limit: limit,
      });
      setBalance(next);
      setDraft(next.monthly_spend_limit ? String(next.monthly_spend_limit) : '');
      notify(limit === null ? t('spendLimitCleared') : t('spendLimitSaved'), 'success');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('spendLimitInvalid'));
    } finally {
      setBusy(false);
    }
  };

  const parsed = Number(draft);
  const valid = draft.trim() !== '' && Number.isInteger(parsed) && parsed >= 1;
  const spent = formatCount(balance?.period_spent ?? 0, locale);

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
      <SectionHeading title={t('spendLimitTitle')} description={t('spendLimitHint')} />
      {balance ? (
        <p className="mt-2 text-xs text-muted">
          {balance.monthly_spend_limit
            ? t('spendLimitUsage', {
                spent,
                limit: formatCount(balance.monthly_spend_limit, locale),
              })
            : t('spendLimitNone', { spent })}
        </p>
      ) : null}
      <form
        className="mt-3 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (valid) void save(parsed);
        }}
      >
        <TextInput
          label={t('spendLimitLabel')}
          type="number"
          inputMode="numeric"
          min={1}
          step={1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="w-40"
        />
        <Button type="submit" loading={busy} disabled={!valid}>
          {t('spendLimitSave')}
        </Button>
        {balance?.monthly_spend_limit ? (
          <Button type="button" variant="ghost" disabled={busy} onClick={() => void save(null)}>
            {t('spendLimitClear')}
          </Button>
        ) : null}
      </form>
      {error ? (
        <div className="mt-3">
          <ErrorNotice title={error} />
        </div>
      ) : null}
    </section>
  );
}
