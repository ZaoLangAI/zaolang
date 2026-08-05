'use client';

import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { ErrorNotice, SectionHeading } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { RedeemCodeResponse } from '@/lib/api/types';

/** Redeems an invite/promo code for its face-value credits. The page's stat
 * tile and ledger are server-rendered, so a refresh — not local state — is
 * what makes the new balance and the fresh ledger row show up. */
export function RedeemCodeForm() {
  const t = useTranslations('billingPage');
  const { notify } = useToast();
  const router = useRouter();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const redeem = async () => {
    const trimmed = code.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<RedeemCodeResponse>('/v1/credits/redeem', {
        code: trimmed,
      });
      notify(t('redeemSucceeded', { count: result.credits_granted }), 'success');
      setCode('');
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('redeemFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
      <SectionHeading title={t('redeemTitle')} description={t('redeemHint')} />
      <form
        className="mt-3 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void redeem();
        }}
      >
        <TextInput
          label={t('redeemCodeLabel')}
          value={code}
          onChange={(event) => setCode(event.target.value.toUpperCase())}
          placeholder="ZAOLANG2026"
          className="w-56 font-mono uppercase tracking-wide"
          autoComplete="off"
        />
        <Button type="submit" loading={busy} disabled={!code.trim()}>
          {t('redeemSubmit')}
        </Button>
      </form>
      {error ? (
        <div className="mt-3">
          <ErrorNotice title={error} />
        </div>
      ) : null}
    </section>
  );
}
