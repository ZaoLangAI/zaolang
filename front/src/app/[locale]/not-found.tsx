import { getTranslations } from 'next-intl/server';

import { EmptyState } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';

/**
 * Without this file, `notFound()` calls anywhere under `[locale]` (missing
 * work/job/profile/etc.) would bubble past this layout's `<html>`/`<body>`
 * and render with the bare root layout instead — see
 * https://nextjs.org/docs/messages/missing-root-layout-tags.
 */
export default async function LocaleNotFound() {
  const t = await getTranslations('states');

  return (
    <div className="mx-auto flex min-h-[50vh] w-full max-w-[720px] flex-col justify-center px-4 py-16">
      <EmptyState
        title={t('notFound')}
        description={t('notFoundHint')}
        action={
          <Link href="/discover" className="text-sm font-medium text-primary hover:underline">
            {t('backHome')}
          </Link>
        }
      />
    </div>
  );
}
