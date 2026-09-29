'use client';

import { useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { use, useEffect, useState } from 'react';

import { PageHeading } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import * as distributionApi from '@/features/drama-dashboard/distribution-api';
import { useRouter } from '@/i18n/navigation';
import { isApiError } from '@/lib/api/errors';

/**
 * `/create/short/platform-callback/{channel}`: where Douyin/Kuaishou's own
 * OAuth redirect lands. The platform hands this page `code`/`state` in the
 * query string; this page's only job is to hand those straight to the
 * backend callback endpoint (which verifies `state`, exchanges `code`, and
 * stores the encrypted token) and then send the creator back to the
 * dashboard.
 */
export default function PlatformCallbackPage({ params }: { params: Promise<{ channel: string }> }) {
  const { channel } = use(params);
  const t = useTranslations('editor');
  const router = useRouter();
  const searchParams = useSearchParams();
  const code = searchParams.get('code');
  const state = searchParams.get('state');

  // Missing params is knowable at first render (no fetch needed to discover
  // it), so it's the lazy initial state rather than a synchronous setState
  // inside the effect below.
  const [status, setStatus] = useState<'connecting' | 'success' | 'error'>(() =>
    code && state ? 'connecting' : 'error',
  );
  const [error, setError] = useState<string | null>(() =>
    code && state ? null : t('platformCallbackMissingParams'),
  );

  useEffect(() => {
    if (!code || !state) return;
    void distributionApi
      .completeConnect(channel, code, state)
      .then(() => {
        setStatus('success');
        setTimeout(() => router.push('/create/short'), 1200);
      })
      .catch((err: unknown) => {
        setStatus('error');
        setError(isApiError(err) ? err.message : t('commandFailed'));
      });
    // Only ever run once per callback landing — re-running with the same
    // `code` would fail anyway (OAuth codes are single-use).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col items-center gap-6 px-4 py-16 text-center">
      <PageHeading
        eyebrow={t('dashboardEyebrow')}
        title={
          status === 'connecting'
            ? t('platformCallbackConnecting')
            : status === 'success'
              ? t('platformCallbackSuccess')
              : t('platformCallbackError')
        }
        description={status === 'error' ? (error ?? '') : ''}
      />
      {status === 'connecting' ? <Spinner label={t('platformCallbackConnecting')} /> : null}
    </div>
  );
}
