'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { useTranslations } from 'next-intl';

import { useSession } from '@/components/auth/session-provider';
import { isCreationNotification } from '@/components/notifications/notification-format';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import type { Notification } from '@/lib/api/types';
import { useNotificationStream } from '@/lib/use-notification-stream';

const RECENT_LIMIT = 5;
export const TOAST_DURATION_MS = 5_000;
export const NOTIFICATIONS_CHANGED = 'zl-notifications-changed';

export interface NotificationToastEntry {
  /** `target_id` for a creation notification — stable across its status updates. */
  key: string;
  notification: Notification;
  expiresAt: number;
}

interface NotificationCenterValue {
  unreadCount: number;
  recent: Notification[];
  toasts: NotificationToastEntry[];
  markAllRead: () => Promise<void>;
  markOne: (id: string) => Promise<void>;
  dismissToast: (key: string) => void;
}

const NotificationCenterContext = createContext<NotificationCenterValue | null>(null);

export function NotificationCenterProvider({ children }: { children: React.ReactNode }) {
  const { status } = useSession();
  const authenticated = status === 'authenticated';
  const { notify } = useToast();
  const tStates = useTranslations('states');

  const [unreadCount, setUnreadCount] = useState(0);
  const [recent, setRecent] = useState<Notification[]>([]);
  const [toasts, setToasts] = useState<NotificationToastEntry[]>([]);

  // Best-effort per-id read-state ledger, seeded from the initial fetch and
  // kept current by every stream event. `unreadCount` starts from the
  // authoritative REST count on load/reconnect; this only interprets the
  // delta a live event implies, so a bump on a notification currently past
  // the "recent 5" window is still counted correctly.
  const readState = useRef(new Map<string, boolean>());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const loadSnapshot = useCallback(async () => {
    const [count, list] = await Promise.all([
      api.get<{ count: number }>('/v1/notifications/unread-count'),
      api.get<{ items: Notification[] }>('/v1/notifications', { query: { limit: RECENT_LIMIT } }),
    ]);
    setUnreadCount(count.count);
    setRecent(list.items);
    readState.current = new Map(list.items.map((item) => [item.id, item.read]));
  }, []);

  // Resets local state in the same render that notices the sign-out, rather
  // than an effect that would first commit stale state and only clear it a
  // render later (https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes).
  const [wasAuthenticated, setWasAuthenticated] = useState(authenticated);
  if (authenticated !== wasAuthenticated) {
    setWasAuthenticated(authenticated);
    if (!authenticated) {
      setUnreadCount(0);
      setRecent([]);
      setToasts([]);
    }
  }

  // Refs may not be written during render, so the ledger/timer cleanup for a
  // sign-out lives here instead of alongside the state resets above.
  useEffect(() => {
    if (authenticated) return;
    readState.current = new Map();
    for (const timer of timers.current.values()) clearTimeout(timer);
    timers.current.clear();
  }, [authenticated]);

  useEffect(() => {
    if (!authenticated) return;
    void (async () => {
      await loadSnapshot().catch(() => undefined);
    })();
  }, [authenticated, loadSnapshot]);

  useEffect(() => {
    const onChanged = () => void loadSnapshot().catch(() => undefined);
    window.addEventListener(NOTIFICATIONS_CHANGED, onChanged);
    return () => window.removeEventListener(NOTIFICATIONS_CHANGED, onChanged);
  }, [loadSnapshot]);

  const scheduleToastExpiry = useCallback((key: string, expiresAt: number) => {
    const existing = timers.current.get(key);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(
      () => {
        timers.current.delete(key);
        setToasts((current) => current.filter((toast) => toast.key !== key));
      },
      Math.max(0, expiresAt - Date.now()),
    );
    timers.current.set(key, timer);
  }, []);

  const dismissToast = useCallback((key: string) => {
    const existing = timers.current.get(key);
    if (existing) {
      clearTimeout(existing);
      timers.current.delete(key);
    }
    setToasts((current) => current.filter((toast) => toast.key !== key));
  }, []);

  const handleEvent = useCallback(
    (notification: Notification) => {
      const previousRead = readState.current.get(notification.id);
      readState.current.set(notification.id, notification.read);
      if (!notification.read && previousRead !== false) {
        setUnreadCount((count) => count + 1);
      } else if (notification.read && previousRead === false) {
        setUnreadCount((count) => Math.max(0, count - 1));
      }

      setRecent((current) => {
        const merged = [notification, ...current.filter((item) => item.id !== notification.id)];
        merged.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
        return merged.slice(0, RECENT_LIMIT);
      });

      if (isCreationNotification(notification) && notification.target_id) {
        const key = notification.target_id;
        const expiresAt = Date.now() + TOAST_DURATION_MS;
        setToasts((current) => {
          const exists = current.some((toast) => toast.key === key);
          const next: NotificationToastEntry = { key, notification, expiresAt };
          return exists
            ? current.map((toast) => (toast.key === key ? next : toast))
            : [...current, next];
        });
        scheduleToastExpiry(key, expiresAt);
      }
    },
    [scheduleToastExpiry],
  );

  useNotificationStream(authenticated, handleEvent);

  useEffect(() => {
    const timerMap = timers.current;
    return () => {
      for (const timer of timerMap.values()) clearTimeout(timer);
      timerMap.clear();
    };
  }, []);

  const markAllRead = useCallback(async () => {
    setRecent((current) => current.map((item) => ({ ...item, read: true })));
    for (const [id] of readState.current) readState.current.set(id, true);
    setUnreadCount(0);
    try {
      await api.post('/v1/notifications/read');
      window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
    } catch (error) {
      await loadSnapshot().catch(() => undefined);
      notify(tStates('error'), 'error');
      throw error;
    }
  }, [loadSnapshot, notify, tStates]);

  const markOne = useCallback(async (id: string) => {
    setRecent((current) =>
      current.map((item) => (item.id === id ? { ...item, read: true } : item)),
    );
    const wasUnread = readState.current.get(id) === false;
    readState.current.set(id, true);
    if (wasUnread) setUnreadCount((count) => Math.max(0, count - 1));
    await api.post('/v1/notifications/read', undefined, { query: { notification_id: id } });
    window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
  }, []);

  const value = useMemo<NotificationCenterValue>(
    () => ({ unreadCount, recent, toasts, markAllRead, markOne, dismissToast }),
    [unreadCount, recent, toasts, markAllRead, markOne, dismissToast],
  );

  return (
    <NotificationCenterContext.Provider value={value}>
      {children}
    </NotificationCenterContext.Provider>
  );
}

export function useNotificationCenter(): NotificationCenterValue {
  const context = useContext(NotificationCenterContext);
  if (!context) {
    throw new Error('useNotificationCenter must be used inside NotificationCenterProvider');
  }
  return context;
}
