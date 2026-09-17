'use client';

import type { ReactNode } from 'react';

import { IconArrowLeft } from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import { useRouter } from '@/i18n/navigation';

/**
 * Same look as `BackLink`, but goes to whatever page the user actually came
 * from (`router.back()`) instead of a fixed destination — falls back to
 * `fallbackHref` only when there is no in-app history to go back to (a fresh
 * tab, a deep link).
 */
export function GoBackLink({
  fallbackHref,
  children,
  className,
}: {
  fallbackHref: string;
  children: ReactNode;
  className?: string;
}) {
  const router = useRouter();

  return (
    <button
      type="button"
      onClick={() => {
        if (typeof window !== 'undefined' && window.history.length > 1) {
          router.back();
        } else {
          router.push(fallbackHref);
        }
      }}
      className={cn(
        'flex min-h-9 w-fit items-center gap-1.5 rounded-[var(--radius-sm)] py-1 text-sm text-muted hover:text-text focus-visible:outline-2',
        className,
      )}
    >
      <IconArrowLeft className="size-4" />
      {children}
    </button>
  );
}
