'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { Button } from '@/components/ui/button';
import { IconChevronDown, IconPlus } from '@/components/ui/icons';
import { useRouter } from '@/i18n/navigation';

/**
 * 顶部「创作」入口：从直接跳转的按钮改为下拉，承载「创作作品」与
 * 「发表学习内容」两个目标。展开态/外部点击关闭/Escape 关闭均照抄
 * `top-bar.tsx` 里 `UserMenu` 的既有模式，保持顶栏交互一致。
 */
export function CreateMenu() {
  const t = useTranslations();
  const router = useRouter();
  const { requireAuth } = useSession();
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
    {
      key: 'createWork',
      label: t('nav.createWork'),
      onSelect: () => router.push('/create'),
    },
    {
      key: 'learnPublish',
      label: t('nav.learnPublish'),
      // 发表学习内容需要登录身份，未登录时先弹登录框，登录后自动补跳转。
      onSelect: () =>
        requireAuth({ label: t('nav.learnPublish'), run: () => router.push('/learn/publish') }),
    },
  ] as const;

  return (
    <div ref={ref} className="relative shrink-0">
      <Button
        size="sm"
        className="shrink-0"
        icon={<IconPlus className="size-4" />}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {/* Hidden, not removed: below `sm` this is an icon-only button, and
            `display: none` would leave it with no accessible name at all. */}
        <span className="sr-only whitespace-nowrap sm:not-sr-only">{t('actions.create')}</span>
        <IconChevronDown className="size-3.5 shrink-0" aria-hidden="true" />
      </Button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-40 mt-2 w-56 rounded-[var(--radius-md)] border border-border bg-surface-raised p-2 shadow-raised"
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className="flex h-9 w-full items-center rounded-[var(--radius-sm)] px-2 text-left text-sm text-text hover:bg-surface-soft"
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
