'use client';

import { useTranslations } from 'next-intl';

import { Dialog } from '@/components/ui/dialog';

/**
 * Full-viewport still preview on top of `Dialog`, so focus trap / Escape /
 * restored focus stay consistent with every other consumer overlay.
 */
export function MediaLightbox({
  open,
  onClose,
  src,
  alt,
}: {
  open: boolean;
  onClose: () => void;
  src: string | null;
  alt?: string;
}) {
  const t = useTranslations('media');

  return (
    <Dialog open={open && Boolean(src)} onClose={onClose} title={t('lightboxTitle')} size="xl">
      {src ? (
        // A plain `img` rather than `next/image`: it sizes to its actual
        // intrinsic dimensions (unknown here), so the click-to-close backdrop
        // only excludes the real pixels of the photo.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={alt ?? ''}
          className="mx-auto max-h-[75vh] max-w-full rounded-[var(--radius-md)] object-contain"
        />
      ) : null}
    </Dialog>
  );
}
