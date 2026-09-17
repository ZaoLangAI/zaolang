'use client';

import { useTranslations } from 'next-intl';
import { useMemo } from 'react';

import { OptionGroup } from '@/components/studio/option-group';
import type { QualityTier, Quote } from '@/lib/api/types';

/** The preview/standard/cinematic quality choice, identical for image, video and audio. */
export function QualityTierField({
  tier,
  onChange,
  quote,
}: {
  tier: QualityTier;
  onChange: (value: QualityTier) => void;
  quote: Quote | null;
}) {
  const t = useTranslations('remixPage');

  const tierOptions = useMemo(
    () => [
      { value: 'preview' as const, label: t('tierPreview'), hint: t('tierPreviewDesc') },
      { value: 'standard' as const, label: t('tierStandard'), hint: t('tierStandardDesc') },
      { value: 'cinematic' as const, label: t('tierCinematic'), hint: t('tierCinematicDesc') },
    ],
    [t],
  );

  return (
    <OptionGroup
      label={t('quality')}
      value={tier}
      onChange={onChange}
      options={tierOptions.map((option) => ({
        ...option,
        trailing: quote && option.value === tier ? `${quote.credits}+` : undefined,
      }))}
    />
  );
}
