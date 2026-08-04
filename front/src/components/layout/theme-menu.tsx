'use client';

import { useTranslations } from 'next-intl';

import { useTheme } from '@/components/theme/theme-provider';
import {
  DropdownMenu,
  DropdownMenuGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu';
import { IconMonitor, IconMoon, IconSun } from '@/components/ui/icons';
import { themePreferences, type ThemePreference } from '@/lib/theme';

const themeIcons: Record<ThemePreference, React.ComponentType<{ className?: string }>> = {
  system: IconMonitor,
  dark: IconMoon,
  light: IconSun,
};

/**
 * Theme only, three states.
 *
 * No preference write here: `ThemeProvider` already persists through its
 * `onPersist` hook, so patching again would send the same request twice.
 */
export function ThemeMenu() {
  const t = useTranslations();
  const { preference, setPreference } = useTheme();
  const TriggerIcon = themeIcons[preference];

  return (
    <DropdownMenu
      ariaLabel={t('a11y.themeMenu')}
      triggerIcon={<TriggerIcon className="size-4" />}
      triggerLabel={t(`theme.${preference}`)}
      width="w-44"
    >
      {(close) => (
        <DropdownMenuGroup label={t('theme.label')}>
          {themePreferences.map((value) => {
            const Icon = themeIcons[value];
            return (
              <DropdownMenuRadioItem
                key={value}
                selected={preference === value}
                onSelect={() => {
                  setPreference(value);
                  close();
                }}
                icon={<Icon className="size-4" />}
              >
                {t(`theme.${value}`)}
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuGroup>
      )}
    </DropdownMenu>
  );
}
