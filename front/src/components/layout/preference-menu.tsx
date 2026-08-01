'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { useTheme } from '@/components/theme/theme-provider';
import { IconChevronDown, IconGlobe, IconMonitor, IconMoon, IconSun } from '@/components/ui/icons';
import { usePathname, useRouter } from '@/i18n/navigation';
import { locales, regions, type Locale, type Region } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { cn } from '@/lib/cn';
import { themePreferences, type ThemePreference } from '@/lib/theme';

const themeIcons: Record<ThemePreference, React.ComponentType<{ className?: string }>> = {
  system: IconMonitor,
  dark: IconMoon,
  light: IconSun,
};

/**
 * Region, language and theme in one popover.
 *
 * They belong together because they are all "how this page should present
 * itself to me", and the design's top bar has room for exactly one control.
 */
export function PreferenceMenu() {
  const t = useTranslations();
  const locale = useLocale() as Locale;
  const router = useRouter();
  const pathname = usePathname();
  const { preference, setPreference } = useTheme();
  const { user, patchUser } = useSession();

  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const region = (user?.region ?? 'CN') as Region;

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const persist = (patch: { region?: Region; locale?: Locale; theme?: ThemePreference }) => {
    if (!user) return;
    patchUser(patch as never);
    // Fire and forget: the UI has already changed, and a failed preference
    // write should not block the interaction or throw a dialog at the user.
    void api.patch('/v1/auth/me/preferences', patch).catch(() => undefined);
  };

  const ThemeIcon = themeIcons[preference];

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2.5 text-xs font-medium text-text hover:border-muted/40"
      >
        <IconGlobe className="size-4 text-muted" />
        <span className="hidden sm:inline">{t(`region.${region}`)}</span>
        <IconChevronDown className="size-3.5 text-muted" />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-40 mt-2 w-64 rounded-[var(--radius-md)] border border-border bg-surface-raised p-3 shadow-raised"
        >
          <Group label={t('region.label')}>
            {regions.map((value) => (
              <Choice
                key={value}
                selected={region === value}
                onSelect={() => persist({ region: value })}
              >
                {t(`region.${value}`)}
              </Choice>
            ))}
          </Group>

          <Group label={t('locale.label')}>
            {locales.map((value) => (
              <Choice
                key={value}
                selected={locale === value}
                onSelect={() => {
                  persist({ locale: value });
                  // Locale lives in the URL, so switching it is a navigation
                  // rather than a state change.
                  router.replace(pathname, { locale: value });
                }}
              >
                {t(`locale.${value}`)}
              </Choice>
            ))}
          </Group>

          <Group label={t('theme.label')}>
            {themePreferences.map((value) => {
              const Icon = themeIcons[value];
              return (
                <Choice
                  key={value}
                  selected={preference === value}
                  onSelect={() => {
                    setPreference(value);
                    persist({ theme: value });
                  }}
                  icon={<Icon className="size-4" />}
                >
                  {t(`theme.${value}`)}
                </Choice>
              );
            })}
          </Group>

          <p className="mt-2 flex items-center gap-1.5 border-t border-border pt-2 text-[11px] text-muted">
            <ThemeIcon className="size-3.5" />
            {t(`theme.${preference}`)}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2 last:mb-0">
      <p className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </p>
      <div className="flex flex-col">{children}</div>
    </div>
  );
}

function Choice({
  selected,
  onSelect,
  children,
  icon,
}: {
  selected: boolean;
  onSelect: () => void;
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        'flex h-9 items-center gap-2 rounded-[var(--radius-sm)] px-2 text-left text-sm transition-colors',
        selected ? 'bg-primary/12 text-primary' : 'text-text hover:bg-surface-soft',
      )}
    >
      {icon}
      {children}
    </button>
  );
}
