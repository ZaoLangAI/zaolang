import type { ComponentProps, ReactNode } from 'react';

import { IconArrowLeft } from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import { Link } from '@/i18n/navigation';

export function BackLink({
  href,
  children,
  className,
}: {
  href: ComponentProps<typeof Link>['href'];
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        'flex min-h-9 w-fit items-center gap-1.5 rounded-[var(--radius-sm)] py-1 text-sm text-muted hover:text-text focus-visible:outline-2',
        className,
      )}
    >
      <IconArrowLeft className="size-4" />
      {children}
    </Link>
  );
}
