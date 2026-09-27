import { getTranslations } from 'next-intl/server';

import { LlmProvidersPanel } from '@/components/admin/models/llm-providers-panel';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetchOrNull } from '@/lib/api/admin-server';
import type { LlmProviderPool, ModelCatalogResponse } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminProviders');
  return { title: t('title') };
}

export default async function AdminProvidersPage() {
  const t = await getTranslations('adminProviders');

  // A reviewer sees the pool read-only rather than an error page — the
  // gateway endpoints are operator-only to edit, not to view.
  const llmPool = await adminFetchOrNull<LlmProviderPool>('/v1/admin/llm-providers');
  // The curated catalogue is a pure UX convenience (see `VendorModelPicker`)
  // — a failed fetch degrades to "custom only" rather than blocking the page.
  const catalog = await adminFetchOrNull<ModelCatalogResponse>('/v1/admin/llm-providers/catalog');

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} descriptionClassName="truncate" />
      {llmPool ? (
        <LlmProvidersPanel initial={llmPool} catalog={catalog ?? { vendors: [] }} />
      ) : null}
    </div>
  );
}
