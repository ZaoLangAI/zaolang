import { getTranslations } from 'next-intl/server';

import { CreateModeCards } from '@/components/create/create-mode-cards';
import { GatewayBanner } from '@/components/create/gateway-banner';
import { InspirationRecommendations } from '@/components/create/inspiration-recommendations';
import { RecentDrafts } from '@/components/create/recent-drafts';
import { CreditsTile } from '@/components/create/credits-tile';
import { ShortformHeroBanner } from '@/components/create/shortform-hero-banner';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Draft, GatewayStatus, Me, Page, StyleGalleryEntry } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('createPage');
  return { title: t('title'), description: t('subtitle') };
}

export default async function CreatePage() {
  const t = await getTranslations('createPage');

  // All four are optional: an anonymous visitor still gets the full create
  // centre and only hits the login dialog when they choose a mode.
  const [me, gateway, drafts, styleGallery] = await Promise.all([
    serverFetchOrNull<Me>('/v1/auth/me', { authenticated: true }),
    serverFetchOrNull<GatewayStatus>('/v1/gateway/status', { revalidate: 30 }),
    serverFetchOrNull<Page<Draft>>('/v1/drafts', { authenticated: true, query: { limit: 6 } }),
    serverFetchOrNull<Page<StyleGalleryEntry>>('/v1/style-gallery'),
  ]);

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
        <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
        <CreditsTile available={me?.available_credits ?? null} />
      </div>

      <GatewayBanner status={gateway} />

      <ShortformHeroBanner />

      <section>
        <h2 className="text-lg font-semibold">{t('startCreating')}</h2>
        <p className="mt-1 text-xs text-muted">{t('startHint')}</p>
        <CreateModeCards className="mt-5" />
      </section>

      <InspirationRecommendations entries={styleGallery?.items ?? []} />

      <RecentDrafts drafts={drafts?.items ?? []} />
    </div>
  );
}
