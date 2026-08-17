'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type { Notification } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';

import { GROUPS, notificationText, notificationVisual, targetHref } from './notification-format';

const NOTIFICATIONS_CHANGED = 'zl-notifications-changed';

export function NotificationList({ initial }: { initial: Notification[] }) {
  const t = useTranslations('notificationsPage');
  const tBody = useTranslations('notificationBody');
  const locale = useLocale() as Locale;
  const { notify } = useToast();

  const [items, setItems] = useState(initial);
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  const [busy, setBusy] = useState(false);

  const unread = items.filter((item) => !item.read).length;
  const shown = filter === 'unread' ? items.filter((item) => !item.read) : items;

  const markAll = async () => {
    setBusy(true);
    try {
      await api.post('/v1/notifications/read');
      setItems((current) => current.map((item) => ({ ...item, read: true })));
      window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
      notify(t('allRead'), 'success');
    } finally {
      setBusy(false);
    }
  };

  const markOne = async (id: string) => {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, read: true } : item)));
    await api.post('/v1/notifications/read', undefined, { query: { notification_id: id } });
    window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
  };

  if (items.length === 0) {
    return <EmptyState title={t('empty')} description={t('emptyHint')} />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label={t('title')} className="flex gap-2">
          {(['all', 'unread'] as const).map((id) => (
            <button
              key={id}
              role="tab"
              type="button"
              aria-selected={filter === id}
              onClick={() => setFilter(id)}
              className={cn(
                'rounded-full border px-3.5 py-1.5 text-xs transition-colors',
                filter === id
                  ? 'border-primary bg-primary/12 text-primary'
                  : 'border-border text-muted hover:text-text',
              )}
            >
              {id === 'all' ? t('filterAll') : t('filterUnread')}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <span className="tabular text-xs text-muted">{t('unreadCount', { count: unread })}</span>
          <Button
            size="sm"
            variant="secondary"
            loading={busy}
            disabled={unread === 0}
            onClick={() => void markAll()}
          >
            {t('markAllRead')}
          </Button>
        </div>
      </div>

      {shown.length === 0 ? (
        <EmptyState title={t('empty')} description={t('emptyHint')} />
      ) : (
        <ul className="divide-y divide-border overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface">
          {shown.map((item) => {
            const group = GROUPS[item.type as keyof typeof GROUPS] ?? GROUPS.system;
            const visual = notificationVisual(item);
            const Icon = visual.icon;
            const Badge = visual.badge;
            const href = targetHref(item);

            return (
              <li
                key={item.id}
                className={cn('flex gap-3 px-5 py-4', !item.read && 'bg-primary/4')}
              >
                <span
                  className={cn(
                    'relative mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-surface-soft',
                    visual.tone,
                  )}
                >
                  <Icon className="size-4" />
                  {Badge ? (
                    <span className="absolute -bottom-0.5 -right-0.5 grid size-3.5 place-items-center rounded-full bg-surface">
                      <Badge className="size-2.5" />
                    </span>
                  ) : null}
                </span>

                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-xs text-muted">
                    {t(group.key)}
                    {!item.read ? (
                      <span
                        aria-hidden="true"
                        className="inline-block size-1.5 rounded-full bg-primary"
                      />
                    ) : null}
                  </p>
                  <p className="mt-1 text-sm">{notificationText(item, tBody)}</p>
                  <p className="mt-1 text-xs text-muted">
                    {formatRelative(item.updated_at ?? item.created_at, locale)}
                  </p>
                </div>

                {href ? (
                  <Link
                    href={href}
                    onClick={() => void markOne(item.id)}
                    className="shrink-0 self-center text-xs text-primary hover:underline"
                  >
                    {t('open')}
                  </Link>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export { NOTIFICATIONS_CHANGED };
