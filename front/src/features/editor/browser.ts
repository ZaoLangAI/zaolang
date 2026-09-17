import { randomUuid } from '@/lib/random-id';

export function isDesktopChromeOrEdge(): boolean {
  const ua = navigator.userAgent;
  if (/Mobile|Android|iPhone|iPad/i.test(ua)) return false;
  return /Chrome\/|Edg\//.test(ua);
}

export function browserInstanceId(): string {
  const key = 'zl_editor_browser';
  const existing = sessionStorage.getItem(key);
  if (existing) return existing;
  const created = randomUuid();
  sessionStorage.setItem(key, created);
  return created;
}
