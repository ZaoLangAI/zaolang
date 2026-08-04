'use client';

import { useLocale, useTranslations } from 'next-intl';

import { useSession } from '@/components/auth/session-provider';
import {
  DropdownMenu,
  DropdownMenuGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu';
import { IconWallet } from '@/components/ui/icons';
import { usePathname, useRouter } from '@/i18n/navigation';
import { defaultRegion, regionLocale, regions, type Locale, type Region } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { beginLocaleTransition } from '@/lib/locale-transition';

/**
 * Region drives both currency and interface language: there is no
 * standalone language switcher, so picking a region also navigates to its
 * mapped locale via `regionLocale`.
 *
 * Works signed out too — the choice always goes through `router.replace`,
 * which next-intl persists in the `zl_locale` cookie, so an anonymous pick
 * survives the next visit even with no account to store it on.
 */
export function RegionMenu() {
  const t = useTranslations();
  const { user, patchUser } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const locale = useLocale() as Locale;
  const region =
    (user?.region as Region | undefined) ??
    regions.find((value) => regionLocale[value] === locale) ??
    defaultRegion;

  const select = (value: Region) => {
    const nextLocale = regionLocale[value];
    if (user) {
      patchUser({ region: value, locale: nextLocale } as never);
      void api
        .patch('/v1/auth/me/preferences', { region: value, locale: nextLocale })
        .catch(() => undefined);
    }
    beginLocaleTransition();
    router.replace(pathname, { locale: nextLocale });
  };

  return (
    <DropdownMenu
      ariaLabel={t('a11y.regionMenu')}
      triggerIcon={<IconWallet className="size-4" />}
      triggerLabel={t(`region.${region}`)}
      width="w-44"
    >
      {(close) => (
        <DropdownMenuGroup label={t('region.label')}>
          {regions.map((value) => (
            <DropdownMenuRadioItem
              key={value}
              selected={region === value}
              onSelect={() => {
                select(value);
                close();
              }}
            >
              {t(`region.${value}`)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuGroup>
      )}
    </DropdownMenu>
  );
}
