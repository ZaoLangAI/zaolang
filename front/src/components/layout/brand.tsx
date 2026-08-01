import { useTranslations } from 'next-intl';

import { IconWave } from '@/components/ui/icons';
import { Link } from '@/i18n/navigation';

export function Brand({ href = '/discover' }: { href?: string }) {
  const t = useTranslations('brand');
  return (
    <Link
      href={href}
      className="flex shrink-0 items-center gap-2 text-lg font-bold tracking-tight text-text"
    >
      <IconWave className="size-6 text-primary" />
      <span>{t('name')}</span>
    </Link>
  );
}
