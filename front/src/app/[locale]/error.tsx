'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';

export default function LocaleError({ reset }: { error: Error; reset: () => void }) {
  const t = useTranslations('states');
  const tActions = useTranslations('actions');

  return (
    <div className="mx-auto flex min-h-[50vh] w-full max-w-[720px] flex-col justify-center px-4 py-16">
      <EmptyState
        title={t('error')}
        description={t('errorHint')}
        action={
          <div className="flex flex-wrap justify-center gap-3">
            <Button onClick={() => reset()}>{tActions('retry')}</Button>
            <Link href="/discover">
              <Button variant="secondary">{t('backHome')}</Button>
            </Link>
          </div>
        }
      />
    </div>
  );
}
