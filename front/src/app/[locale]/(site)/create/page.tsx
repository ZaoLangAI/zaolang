import { getTranslations } from 'next-intl/server';

import { CreateModeCards } from '@/components/create/create-mode-cards';
import { GatewayBanner } from '@/components/create/gateway-banner';
import { RecentDrafts } from '@/components/create/recent-drafts';
import { CreditsTile } from '@/components/create/credits-tile';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Draft, GatewayStatus, Me, Page } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('createPage');
  return { title: t('title'), description: t('subtitle') };
}

export default async function CreatePage() {
  const t = await getTranslations('createPage');

  // All three are optional: an anonymous visitor still gets the full create
  // centre and only hits the login dialog when they choose a mode.
  const [me, gateway, drafts] = await Promise.all([
    serverFetchOrNull<Me>('/v1/auth/me', { authenticated: true }),
    serverFetchOrNull<GatewayStatus>('/v1/gateway/status', { revalidate: 30 }),
    serverFetchOrNull<Page<Draft>>('/v1/drafts', { authenticated: true, query: { limit: 6 } }),
  ]);

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
        <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
        <CreditsTile available={me?.available_credits ?? null} />
      </div>

      <GatewayBanner status={gateway} />

      <section>
        <h2 className="text-lg font-semibold">{t('startCreating')}</h2>
        <p className="mt-1 text-xs text-muted">{t('startHint')}</p>
        <CreateModeCards className="mt-5" />
      </section>

      <RecentDrafts drafts={drafts?.items ?? []} />
    </div>
  );
}
