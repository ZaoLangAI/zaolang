'use client';

import { useLocale, useTranslations } from 'next-intl';

import { useNotificationCenter } from '@/components/notifications/notification-center-provider';
import {
  notificationText,
  notificationVisual,
  targetHref,
} from '@/components/notifications/notification-format';
import { IconClose } from '@/components/ui/icons';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';

/**
 * Right-side live toasts for generation-job / drama-export status changes.
 *
 * Separate from `components/ui/toast.tsx`'s bottom-center `ToastProvider`,
 * which stays reserved for one-off success/error messages from an action the
 * user just took. These toasts are keyed by `target_id` in
 * `NotificationCenterProvider` — a later status update for the same job or
 * export replaces the card in place and pushes its auto-dismiss timer back
 * out, rather than stacking a second popup for the same piece of work.
 */
export function NotificationToastStack() {
  const t = useTranslations('notificationsPage');
  const tBody = useTranslations('notificationBody');
  const locale = useLocale() as Locale;
  const { toasts, dismissToast, markOne } = useNotificationCenter();

  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed right-4 top-20 z-50 flex w-full max-w-sm flex-col gap-2"
    >
      {toasts.map(({ key, notification }) => {
        const visual = notificationVisual(notification);
        const Icon = visual.icon;
        const Badge = visual.badge;
        const href = targetHref(notification);

        return (
          <div
            key={key}
            role="status"
            className="pointer-events-auto flex items-start gap-3 rounded-[var(--radius-md)] border border-border bg-surface-raised p-4 shadow-raised"
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
              <p className="text-sm">{notificationText(notification, tBody)}</p>
              <p className="mt-1 text-xs text-muted">
                {formatRelative(notification.updated_at ?? notification.created_at, locale)}
              </p>
              {href ? (
                <Link
                  href={href}
                  onClick={() => {
                    void markOne(notification.id);
                    dismissToast(key);
                  }}
                  className="mt-1.5 inline-block text-xs text-primary hover:underline"
                >
                  {t('open')}
                </Link>
              ) : null}
            </div>

            <button
              type="button"
              onClick={() => dismissToast(key)}
              aria-label={t('dismiss')}
              className="shrink-0 text-muted hover:text-text"
            >
              <IconClose className="size-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
