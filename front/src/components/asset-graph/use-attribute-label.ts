'use client';

import { useTranslations } from 'next-intl';

import {
  AGE_STAGES,
  SCENE_LIGHTINGS,
  SCENE_PERIODS,
  SCENE_STATES,
  SCENE_WEATHERS,
} from '@/features/image-assets/vocabulary';

import type { AttributeRow } from './graph-model';

const ENUM_TABLES: Partial<Record<AttributeRow['key'], Record<string, { labelKey: string }>>> = {
  period: SCENE_PERIODS,
  lighting: SCENE_LIGHTINGS,
  weather: SCENE_WEATHERS,
  scene_state: SCENE_STATES,
};

/** `(row) → { label, value }` in the viewer's language: enumerated values go
 * through their vocabulary copy, free text and custom names stay as typed. */
export function useAttributeLabel(): (row: AttributeRow) => { label: string; value: string } {
  const t = useTranslations('assetGraph');
  const tVariants = useTranslations('assetVariants');
  const tPresets = useTranslations('remixPage');
  return (row) => {
    if (row.key === 'custom') return { label: row.name ?? '', value: row.value };
    const label = t(`row.${row.key}`);
    if (row.key === 'age_stage') {
      const entry = AGE_STAGES[row.value as keyof typeof AGE_STAGES];
      return { label, value: entry ? tVariants(entry.labelKey) : row.value };
    }
    const table = ENUM_TABLES[row.key];
    const entry = table?.[row.value];
    return { label, value: entry ? tPresets(`presets.${entry.labelKey}`) : row.value };
  };
}
