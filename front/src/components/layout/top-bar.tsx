'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { Brand } from '@/components/layout/brand';
import { PreferenceMenu } from '@/components/layout/preference-menu';
import { Button } from '@/components/ui/button';
import {
  IconBell,
  IconChevronDown,
  IconClose,
  IconMenu,
  IconPlus,
  IconSearch,
  IconSparkle,
  IconUser,
} from '@/components/ui/icons';
import { Link, usePathname, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { cn } from '@/lib/cn';
import { formatCount } from '@/lib/format';

const NAV = [
  { key: 'discover', href: '/discover' },
  { key: 'create', href: '/create' },
  { key: 'learn', href: '/learn' },
  { key: 'collection', href: '/collection' },
] as const;

export function TopBar() {
  const t = useTranslations();
  const locale = useLocale() as Locale;
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, status, openLogin, signOut } = useSession();

  const routeQuery = pathname === '/discover' ? (searchParams.get('q') ?? '') : '';
  const [query, setQuery] = useState(routeQuery);
  const [mirroredQuery, setMirroredQuery] = useState({ pathname, q: routeQuery });
  const [mobileOpen, setMobileOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [menuPath, setMenuPath] = useState(pathname);

  // Navigating away closes the mobile menu. Adjusting during render rather
  // than in an effect avoids a frame where the new page shows with the old
  // menu still open over it.
  if (menuPath !== pathname) {
    setMenuPath(pathname);
    setMobileOpen(false);
  }

  // Mirror discover's `q` into the search box (and clear it off-route) so
  // Cmd+K / shared links land with the keyword already filled.
  if (mirroredQuery.pathname !== pathname || mirroredQuery.q !== routeQuery) {
    setMirroredQuery({ pathname, q: routeQuery });
    setQuery(routeQuery);
  }

  useEffect(() => {
    if (status !== 'authenticated') return;
    void api
      .get<{ count: number }>('/v1/notifications/unread-count')
      .then((body) => setUnread(body.count))
      .catch(() => undefined);
  }, [status, pathname]);

  const onSearch = (event: React.FormEvent) => {
    event.preventDefault();
    const params = new URLSearchParams();
    const trimmed = query.trim();
    if (trimmed) params.set('q', trimmed);
    // Preserve tag/sort filters when refining the keyword from the top bar.
    if (pathname === '/discover') {
      const tag = searchParams.get('tag');
      const sort = searchParams.get('sort');
      if (tag) params.set('tag', tag);
      if (sort) params.set('sort', sort);
    }
    const qs = params.toString();
    router.push(qs ? `/discover?${qs}` : '/discover');
  };

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-bg/92 backdrop-blur">
      <div className="page-x mx-auto flex h-16 max-w-[1440px] items-center gap-3">
        <button
          type="button"
          className="-ml-1 inline-flex size-11 items-center justify-center rounded-[var(--radius-sm)] text-muted lg:hidden"
          aria-label={mobileOpen ? t('nav.closeMenu') : t('nav.openMenu')}
          aria-expanded={mobileOpen}
          onClick={() => setMobileOpen((value) => !value)}
        >
          {mobileOpen ? <IconClose className="size-5" /> : <IconMenu className="size-5" />}
        </button>

        <Brand />

        <nav
          aria-label={t('nav.mainNavigation')}
          className="ml-2 hidden items-center gap-1 lg:flex"
        >
          {NAV.map((item) => {
            const activeItem = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.key}
                href={item.href}
                aria-current={activeItem ? 'page' : undefined}
                className={cn(
                  'relative flex h-16 items-center px-3 text-sm font-medium transition-colors',
                  activeItem ? 'text-primary' : 'text-muted hover:text-text',
                )}
              >
                {t(`nav.${item.key}`)}
                {activeItem ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-primary"
                  />
                ) : null}
              </Link>
            );
          })}
        </nav>

        <form
          role="search"
          onSubmit={onSearch}
          className="mx-auto hidden h-10 w-full max-w-md items-center gap-2 rounded-full border border-border bg-surface-soft px-4 md:flex"
        >
          <IconSearch className="size-4 shrink-0 text-muted" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('actions.search')}
            aria-label={t('actions.search')}
            className="w-full bg-transparent text-sm outline-none placeholder:text-muted"
          />
          <kbd
            aria-hidden="true"
            className="hidden rounded border border-border px-1.5 text-[11px] text-muted lg:block"
          >
            /
          </kbd>
        </form>

        <div className="ml-auto flex items-center gap-2 md:ml-0">
          <div className="hidden md:block">
            <PreferenceMenu />
          </div>

          {status === 'authenticated' && user ? (
            <Link
              href="/billing"
              className="hidden h-9 items-center gap-1.5 rounded-[var(--radius-sm)] border border-amber/35 bg-amber/12 px-2.5 text-xs font-semibold text-amber sm:inline-flex"
            >
              <IconSparkle className="size-4" />
              <span className="tabular">
                {t('credits.amount', { count: formatCount(user.available_credits, locale) })}
              </span>
            </Link>
          ) : null}

          <Button
            size="sm"
            icon={<IconPlus className="size-4" />}
            onClick={() => router.push('/create')}
          >
            <span className="hidden sm:inline">{t('actions.create')}</span>
          </Button>

          {status === 'authenticated' ? (
            <Link
              href="/notifications"
              aria-label={t('nav.notifications')}
              className="relative inline-flex size-9 items-center justify-center rounded-[var(--radius-sm)] text-muted hover:bg-surface-soft hover:text-text"
            >
              <IconBell className="size-5" />
              {status === 'authenticated' && unread > 0 ? (
                <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-primary ring-2 ring-bg" />
              ) : null}
            </Link>
          ) : null}

          {status === 'authenticated' && user ? (
            <UserMenu
              name={user.profile?.display_name ?? user.email}
              onSignOut={() => void signOut()}
            />
          ) : status === 'anonymous' ? (
            <Button variant="secondary" size="sm" onClick={openLogin}>
              {t('auth.signIn')}
            </Button>
          ) : (
            <div className="size-9 animate-pulse rounded-full bg-skeleton" aria-hidden="true" />
          )}
        </div>
      </div>

      {mobileOpen ? (
        <nav
          aria-label={t('nav.mainNavigation')}
          className="page-x border-t border-border bg-surface pb-4 lg:hidden"
        >
          <ul className="flex flex-col py-2">
            {NAV.map((item) => (
              <li key={item.key}>
                <Link
                  href={item.href}
                  className="flex h-12 items-center text-sm font-medium text-text"
                >
                  {t(`nav.${item.key}`)}
                </Link>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2">
            <PreferenceMenu />
            {status === 'authenticated' ? (
              <Button variant="ghost" size="sm" onClick={() => void signOut()}>
                {t('auth.signOut')}
              </Button>
            ) : null}
          </div>
        </nav>
      ) : null}
    </header>
  );
}

function UserMenu({ name, onSignOut }: { name: string; onSignOut: () => void }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const items = [
    { href: '/profile', label: t('nav.profile') },
    { href: '/collection', label: t('nav.collection') },
    { href: '/billing', label: t('nav.billing') },
    { href: '/profile/settings', label: t('nav.settings') },
  ] as const;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('nav.userMenu')}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1 rounded-full border border-border bg-surface-soft p-1 pr-1.5 text-muted hover:text-text"
      >
        <span className="inline-flex size-7 items-center justify-center rounded-full bg-surface-raised">
          <IconUser className="size-4" />
        </span>
        <IconChevronDown className="size-3.5" />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-40 mt-2 w-56 rounded-[var(--radius-md)] border border-border bg-surface-raised p-2 shadow-raised"
        >
          <p className="truncate px-2 py-1.5 text-xs text-muted">
            {t('auth.signedInAs', { name })}
          </p>
          {items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              role="menuitem"
              className="flex h-9 items-center rounded-[var(--radius-sm)] px-2 text-sm text-text hover:bg-surface-soft"
            >
              {item.label}
            </Link>
          ))}
          <button
            type="button"
            role="menuitem"
            onClick={onSignOut}
            className="mt-1 flex h-9 w-full items-center gap-2 rounded-[var(--radius-sm)] border-t border-border px-2 text-left text-sm text-muted hover:text-text"
          >
            <IconClose className="size-4" />
            {t('auth.signOut')}
          </button>
        </div>
      ) : null}
    </div>
  );
}
