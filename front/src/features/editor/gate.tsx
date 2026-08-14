'use client';

import { useTranslations } from 'next-intl';

import { EmptyState } from '@/components/ui/primitives';
import { useMinWidth } from '@/lib/use-media-query';

import { isDesktopChromeOrEdge } from './browser';

export function EditorGate({ children }: { children: React.ReactNode }) {
  const t = useTranslations('editor');
  const wide = useMinWidth('md');

  if (!wide) {
    return <EmptyState title={t('gateDesktopTitle')} description={t('gateDesktopHint')} />;
  }
  if (!isDesktopChromeOrEdge()) {
    return <EmptyState title={t('gateBrowserTitle')} description={t('gateBrowserHint')} />;
  }
  return children;
}
