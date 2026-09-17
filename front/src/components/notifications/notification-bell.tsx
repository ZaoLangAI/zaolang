'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { useNotificationCenter } from '@/components/notifications/notification-center-provider';
import {
  GROUPS,
  notificationText,
  notificationVisual,
  targetHref,
} from '@/components/notifications/notification-format';
import { Button } from '@/components/ui/button';
import { IconBell } from '@/components/ui/icons';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { Notification } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';

/**
 * The top-bar bell: a popover with the 5 most recent notifications, live-kept
 * by `NotificationCenterProvider`, plus a link to the full `/notifications`
 * page. Hand-rolled rather than `components/ui/dropdown-menu.tsx`'s
 * `DropdownMenu`, matching the top bar's existing icon-trigger popovers
 * (`CreateMenu` / `UserMenu` in `top-bar.tsx`) rather than that component's
 * labelled-chip-with-chevron trigger, which doesn't fit an icon-only bell.
 */
export function NotificationBell() {
  const t = useTranslations('notificationsPage');
  const tBody = useTranslations('notificationBody');
  const locale = useLocale() as Locale;
  const { unreadCount, recent, markAllRead, markOne } = useNotificationCenter();

  const [open, setOpen] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
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

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('title')}
        onClick={() => setOpen((value) => !value)}
        className="relative inline-flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-sm)] text-muted hover:bg-surface-soft hover:text-text"
      >
        <IconBell className="size-5" />
        {unreadCount > 0 ? (
          <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-primary ring-2 ring-bg" />
        ) : null}
      </button>

      {open ? (
        <div
          role="menu"
          aria-label={t('title')}
          className="absolute right-0 z-40 mt-2 w-80 rounded-[var(--radius-md)] border border-border bg-surface-raised p-2 shadow-raised"
        >
          <div className="flex items-center justify-between gap-2 px-2 pb-1 pt-1">
            <p className="min-w-0 text-sm font-medium text-text">{t('title')}</p>
            <div className="flex shrink-0 items-center gap-2">
              {unreadCount > 0 ? (
                <span className="tabular text-xs text-muted">
                  {t('unreadCount', { count: unreadCount })}
                </span>
              ) : null}
              <Button
                variant="link"
                size="sm"
                loading={markingAll}
                disabled={unreadCount === 0}
                className="h-auto px-0 text-xs"
                onClick={() => {
                  setMarkingAll(true);
                  void markAllRead().finally(() => setMarkingAll(false));
                }}
              >
                {t('markAllRead')}
              </Button>
            </div>
          </div>

          {recent.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-muted">{t('emptyHint')}</p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {recent.map((item) => (
                <BellItem
                  key={item.id}
                  item={item}
                  locale={locale}
                  t={t}
                  tBody={tBody}
                  onOpen={() => {
                    void markOne(item.id);
                    setOpen(false);
                  }}
                />
              ))}
            </ul>
          )}

          <div className="mt-1 border-t border-border pt-1">
            <Link
              href="/notifications"
              onClick={() => setOpen(false)}
              className="flex h-9 w-full items-center justify-center rounded-[var(--radius-sm)] text-sm text-primary hover:bg-surface-soft"
            >
              {t('viewAll')}
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BellItem({
  item,
  locale,
  t,
  tBody,
  onOpen,
}: {
  item: Notification;
  locale: Locale;
  t: ReturnType<typeof useTranslations>;
  tBody: ReturnType<typeof useTranslations>;
  onOpen: () => void;
}) {
  const group = GROUPS[item.type as keyof typeof GROUPS] ?? GROUPS.system;
  const visual = notificationVisual(item);
  const Icon = visual.icon;
  const Badge = visual.badge;
  const href = targetHref(item);

  const content = (
    <div className={cn('flex w-full gap-2.5 rounded-[var(--radius-sm)] px-2 py-2 text-left', !item.read && 'bg-primary/6')}>
      <span
        className={cn(
          'relative mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-surface-soft',
          visual.tone,
        )}
      >
        <Icon className="size-3.5" />
        {Badge ? (
          <span className="absolute -bottom-0.5 -right-0.5 grid size-3 place-items-center rounded-full bg-surface">
            <Badge className="size-2" />
          </span>
        ) : null}
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 text-[11px] text-muted">
          {t(group.key)}
          {!item.read ? (
            <span aria-hidden="true" className="inline-block size-1 rounded-full bg-primary" />
          ) : null}
        </p>
        <p className="mt-0.5 line-clamp-2 text-xs text-text">{notificationText(item, tBody)}</p>
        <p className="mt-0.5 text-[11px] text-muted">
          {formatRelative(item.updated_at ?? item.created_at, locale)}
        </p>
      </div>
    </div>
  );

  return (
    <li>
      {href ? (
        <Link href={href} role="menuitem" onClick={onOpen} className="block hover:bg-surface-soft">
          {content}
        </Link>
      ) : (
        <button type="button" role="menuitem" onClick={onOpen} className="block w-full hover:bg-surface-soft">
          {content}
        </button>
      )}
    </li>
  );
}
