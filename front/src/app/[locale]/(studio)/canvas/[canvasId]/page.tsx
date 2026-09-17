import { getTranslations } from 'next-intl/server';

import { CanvasShell } from '@/features/canvas/canvas-shell';

export async function generateMetadata() {
  const t = await getTranslations('canvas');
  return { title: t('title') };
}

export default async function CanvasPage({
  params,
}: {
  params: Promise<{ canvasId: string }>;
}) {
  const { canvasId } = await params;
  return <CanvasShell canvasId={canvasId} />;
}
