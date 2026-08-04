'use client';

import { useTranslations } from 'next-intl';

import { useSession } from '@/components/auth/session-provider';
import {
  DropdownMenu,
  DropdownMenuGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu';
import { IconWallet } from '@/components/ui/icons';
import { usePathname, useRouter } from '@/i18n/navigation';
import { regionLocale, regions, type Region } from '@/i18n/routing';
import { api } from '@/lib/api/client';

/**
 * Region drives both currency and interface language: there is no
 * standalone language switcher, so picking a region also navigates to its
 * mapped locale via `regionLocale`.
 */
export function RegionMenu() {
  const t = useTranslations();
  const { user, patchUser } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const region = (user?.region ?? 'CN') as Region;

  const select = (value: Region) => {
    if (!user) return;
    const locale = regionLocale[value];
    patchUser({ region: value, locale } as never);
    void api.patch('/v1/auth/me/preferences', { region: value, locale }).catch(() => undefined);
    router.replace(pathname, { locale });
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
