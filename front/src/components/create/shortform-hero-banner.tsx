'use client';

import { useTranslations } from 'next-intl';

import { useSession } from '@/components/auth/session-provider';
import { ShortformIllustration } from '@/components/create/mode-illustrations';
import { Button } from '@/components/ui/button';
import { IconArrowRight, IconPhone } from '@/components/ui/icons';
import { useRouter } from '@/i18n/navigation';

/**
 * The short-video entry point, promoted to its own banner above the mode grid.
 *
 * `CreateModeCards` keeps its own `shortform` tile untouched — this is an
 * additional, larger door into the same route (`/create/short`), not a
 * replacement, so a returning user who has learned the grid layout still
 * finds it exactly where it was.
 */
export function ShortformHeroBanner() {
  const t = useTranslations('createPage');
  const router = useRouter();
  const { requireAuth } = useSession();

  const start = () =>
    requireAuth({
      label: t('shortformHeroTitle'),
      run: () => router.push('/create/short'),
    });

  return (
    <section className="shortform-hero-panel relative overflow-hidden rounded-[var(--radius-lg)] border border-border p-5 sm:p-8">
      <ShortformIllustration className="pointer-events-none absolute inset-y-0 right-4 hidden w-28 text-amber opacity-25 lg:block" />

      <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
        <div className="flex gap-4 sm:items-center">
          <span className="grid size-12 shrink-0 place-items-center rounded-full bg-amber/15 text-amber sm:size-14">
            <IconPhone className="size-6 sm:size-7" />
          </span>
          <div className="min-w-0">
            <p className="eyebrow">{t('shortformHeroTag')}</p>
            <h2 className="mt-1 text-xl font-bold tracking-tight sm:text-2xl">
              {t('shortformHeroTitle')}
            </h2>
            <p className="mt-1.5 max-w-xl text-sm leading-relaxed text-muted">
              {t('shortformHeroDesc')}
            </p>
          </div>
        </div>

        <Button
          size="lg"
          onClick={start}
          icon={<IconArrowRight className="size-5" />}
          className="relative shrink-0"
        >
          {t('shortformHeroCta')}
        </Button>
      </div>
    </section>
  );
}
