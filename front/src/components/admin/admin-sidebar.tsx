'use client';

import { useTranslations } from 'next-intl';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { useTheme } from '@/components/theme/theme-provider';
import { Button } from '@/components/ui/button';
import {
  IconAlert,
  IconBell,
  IconGear,
  IconGrid,
  IconImage,
  IconMonitor,
  IconMoon,
  IconRemix,
  IconShield,
  IconSparkle,
  IconSun,
  IconUser,
  IconWallet,
  IconWave,
} from '@/components/ui/icons';
import { Link, usePathname } from '@/i18n/navigation';
import { visibleGroups, type NavItem } from '@/lib/admin/rbac';
import { cn } from '@/lib/cn';

const ICONS: Record<NavItem['icon'], React.ComponentType<{ className?: string }>> = {
  health: IconMonitor,
  jobs: IconSparkle,
  providers: IconGrid,
  agents: IconSparkle,
  moderation: IconShield,
  reports: IconAlert,
  learnPosts: IconImage,
  skillLibrary: IconRemix,
  users: IconUser,
  credits: IconWallet,
  config: IconGear,
  data: IconGrid,
  audit: IconShield,
  announcements: IconBell,
};

/**
 * Console navigation, trimmed to the operator's role.
 *
 * Hiding a route is a courtesy only — the server returns 403 for anything the
 * role cannot do — so this never needs to be treated as a security boundary.
 */
export function AdminSidebar() {
  const t = useTranslations('admin');
  const tTheme = useTranslations('theme');
  const pathname = usePathname();
  const { session, role, signOut } = useAdminSession();
  const { preference, setPreference } = useTheme();

  const groups = visibleGroups(role);
  const roleLabel = t(
    `role${role.charAt(0).toUpperCase()}${role.slice(1)}` as
      'roleViewer' | 'roleReviewer' | 'roleOperator' | 'roleAdmin',
  );

  const nextTheme = preference === 'dark' ? 'light' : preference === 'light' ? 'system' : 'dark';
  const ThemeIcon =
    preference === 'dark' ? IconMoon : preference === 'light' ? IconSun : IconMonitor;

  return (
    <div className="flex h-full flex-col gap-4 border-r border-border bg-surface px-3 py-4">
      <Link href="/admin" className="flex items-center gap-2.5 px-2">
        <IconWave className="size-6 text-primary" />
        <span className="text-sm font-semibold">{t('consoleShort')}</span>
      </Link>

      <nav aria-label={t('console')} className="flex-1 overflow-y-auto">
        {groups.map((group) => (
          <div key={group.labelKey} className="mb-4">
            <p className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
              {t(group.labelKey as 'groupRuntime' | 'groupDomain' | 'groupPlatform')}
            </p>
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => {
                const Icon = ICONS[item.icon];
                // `/admin` must not light up for every child route.
                const active =
                  item.href === '/admin' ? pathname === '/admin' : pathname.startsWith(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? 'page' : undefined}
                      className={cn(
                        'flex items-center gap-2.5 rounded-[var(--radius-sm)] px-2.5 py-2 text-sm transition-colors',
                        active
                          ? 'bg-primary/12 text-primary'
                          : 'text-muted hover:bg-surface-soft hover:text-text',
                      )}
                    >
                      <Icon className="size-4 shrink-0" />
                      {t(item.labelKey as 'navHealth')}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-border pt-3">
        <p className="truncate px-2 text-xs">{session.email}</p>
        <p className="mt-0.5 px-2 text-[11px] text-muted">
          {t('role')} · {roleLabel}
        </p>

        <div className="mt-3 flex flex-col gap-1.5">
          <button
            type="button"
            onClick={() => setPreference(nextTheme)}
            className="flex items-center gap-2.5 rounded-[var(--radius-sm)] px-2.5 py-2 text-xs text-muted hover:bg-surface-soft hover:text-text"
          >
            <ThemeIcon className="size-4" />
            {tTheme(preference)}
          </button>
          <Link
            href="/discover"
            className="rounded-[var(--radius-sm)] px-2.5 py-2 text-xs text-muted hover:bg-surface-soft hover:text-text"
          >
            {t('backToSite')}
          </Link>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void signOut()}
            className="justify-start"
          >
            {t('signOut')}
          </Button>
        </div>
      </div>
    </div>
  );
}
