'use client';

import { useTranslations } from 'next-intl';

import type { AssetGraph } from '@/lib/api/types';

/** Human names for graph nodes: a look by its name, an image as
 * 「look · type」 — what relation lists and pickers show. */
export function useNodeNames(graph: AssetGraph) {
  const t = useTranslations('assetVariants');
  const variants = graph.variants ?? [];
  const lookName = new Map(variants.map((v) => [v.id, v.name]));
  const entryName = new Map<string, string>();
  for (const variant of variants) {
    (variant.entries ?? []).forEach((entry, index) => {
      entryName.set(entry.id, `${variant.name} · ${t(`type.${entry.entry_type}`)} ${index + 1}`);
    });
  }
  return (level: 'variant' | 'entry', id: string): string =>
    (level === 'variant' ? lookName.get(id) : entryName.get(id)) ?? id;
}
