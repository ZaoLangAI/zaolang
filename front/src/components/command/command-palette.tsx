'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { IconSearch } from '@/components/ui/icons';
import { useRouter } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import type { Locale } from '@/i18n/routing';
import type { Page, WorkSummary } from '@/lib/api/types';
import { cn } from '@/lib/cn';

interface Command {
  id: string;
  group: string;
  label: string;
  hint?: string;
  run: () => void;
}

/**
 * Global Cmd+K palette, implemented as a combobox.
 *
 * ARIA's combobox pattern is what makes an input-plus-listbox comprehensible
 * to a screen reader: the input keeps focus and `aria-activedescendant` moves
 * the virtual cursor, so arrow keys read out options without stealing focus.
 */
export function CommandPalette() {
  const t = useTranslations('commandPalette');
  const tNav = useTranslations('nav');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { status, openLogin } = useSession();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [works, setWorks] = useState<WorkSummary[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const restoreTo = useRef<HTMLElement | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    setQuery('');
    setActive(0);
    setWorks([]);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const isPaletteShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k';
      // `/` is the design's search shortcut, but only when the user is not
      // already typing somewhere.
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === 'INPUT' ||
        target?.tagName === 'TEXTAREA' ||
        target?.isContentEditable === true;

      if (isPaletteShortcut || (event.key === '/' && !typing)) {
        event.preventDefault();
        setOpen(true);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  // Focus moves into the palette on open and back to whatever the user was on
  // when it closes, so dismissing it never strands focus on the body.
  useEffect(() => {
    if (!open) return;
    restoreTo.current = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => restoreTo.current?.focus();
  }, [open]);

  const trimmed = query.trim();
  const searchable = trimmed.length >= 2;

  // Debounced so typing a title does not fire a request per keystroke.
  useEffect(() => {
    if (!open || !searchable) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void api
        .get<Page<WorkSummary>>('/v1/works', {
          query: { q: trimmed, limit: 5 },
          signal: controller.signal,
        })
        .then((page) => {
          setWorks(page.items);
          setActive(0);
        })
        .catch(() => undefined);
    }, 180);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [open, searchable, trimmed]);

  const go = useCallback(
    (path: string) => {
      close();
      router.push(path);
    },
    [close, router],
  );

  const commands = useMemo<Command[]>(() => {
    const navigate: Command[] = [
      { id: 'discover', label: tNav('discover'), path: '/discover' },
      { id: 'create', label: tNav('create'), path: '/create' },
      { id: 'learn', label: tNav('learn'), path: '/learn' },
      { id: 'collection', label: tNav('collection'), path: '/collection' },
      { id: 'profile', label: tNav('profile'), path: '/profile' },
      { id: 'billing', label: tNav('billing'), path: '/billing' },
      { id: 'notifications', label: tNav('notifications'), path: '/notifications' },
      { id: 'settings', label: tNav('settings'), path: '/profile/settings' },
    ].map(({ id, label, path }) => ({
      id,
      group: t('groupNavigate'),
      label,
      run: () => {
        // Protected destinations still need a session; opening the login
        // dialog beats landing the user on an empty page.
        if (
          status !== 'authenticated' &&
          ['collection', 'profile', 'billing', 'notifications', 'settings'].includes(id)
        ) {
          close();
          openLogin();
          return;
        }
        go(path);
      },
    }));

    const workResults: Command[] = (searchable ? works : []).map((work) => ({
      id: `work-${work.id}`,
      group: t('groupWorks'),
      label: work.title,
      hint: work.author.display_name,
      run: () => go(`/work/${work.id}`),
    }));

    const search: Command[] = trimmed
      ? [
          {
            id: 'search',
            group: t('groupNavigate'),
            label: t('searchFor', { query: trimmed }),
            run: () => go(`/discover?q=${encodeURIComponent(trimmed)}`),
          },
        ]
      : [];

    const needle = trimmed.toLowerCase();
    const filteredNavigate = needle
      ? navigate.filter((command) => command.label.toLowerCase().includes(needle))
      : navigate;

    return [...search, ...filteredNavigate, ...workResults];
  }, [close, go, openLogin, searchable, status, t, tNav, trimmed, works]);

  if (!open) return null;

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      close();
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((index) => (commands.length ? (index + 1) % commands.length : 0));
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((index) => (commands.length ? (index - 1 + commands.length) % commands.length : 0));
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      commands[active]?.run();
    }
  };

  // Grouped for display, but the flat `commands` order stays authoritative for
  // arrow keys and `aria-activedescendant`, so what the eye sees and what the
  // keyboard visits cannot drift apart.
  const groups: { name: string; items: { command: Command; index: number }[] }[] = [];
  commands.forEach((command, index) => {
    const current = groups.at(-1);
    if (current?.name === command.group) {
      current.items.push({ command, index });
    } else {
      groups.push({ name: command.group, items: [{ command, index }] });
    }
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]"
      style={{ background: 'var(--overlay)' }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      {/* A search landmark: the palette is grafted onto the page root, so
          without one its contents sit outside every landmark. */}
      <div
        role="search"
        aria-label={t('open')}
        className="w-full max-w-xl overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface-raised shadow-raised"
      >
        <div className="flex items-center gap-3 border-b border-border px-4">
          <IconSearch className="size-4 shrink-0 text-muted" />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded="true"
            aria-controls={listboxId}
            aria-activedescendant={commands[active] ? `${listboxId}-${active}` : undefined}
            aria-label={t('placeholder')}
            autoComplete="off"
            className="h-13 w-full bg-transparent text-sm text-text outline-none placeholder:text-muted"
            placeholder={t('placeholder')}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
          />
        </div>

        {/* A listbox may only own options and groups, so the rows cannot be
            wrapped in list items and the empty state lives outside it. */}
        <div
          id={listboxId}
          role="listbox"
          aria-label={t('open')}
          className="max-h-[52vh] overflow-y-auto p-2"
        >
          {groups.map((group) => (
            <div key={group.name} role="group" aria-label={group.name}>
              <p
                aria-hidden="true"
                className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-muted"
              >
                {group.name}
              </p>
              {group.items.map(({ command, index }) => (
                <div
                  key={command.id}
                  id={`${listboxId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  onMouseEnter={() => setActive(index)}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    command.run();
                  }}
                  className={cn(
                    'flex cursor-pointer items-center justify-between gap-3 rounded-[var(--radius-sm)] px-3 py-2.5 text-sm',
                    index === active ? 'bg-primary/12 text-primary' : 'text-text',
                  )}
                >
                  <span className="truncate">{command.label}</span>
                  {command.hint ? (
                    <span className="shrink-0 text-xs text-muted">{command.hint}</span>
                  ) : null}
                </div>
              ))}
            </div>
          ))}
        </div>

        {commands.length === 0 ? (
          <p role="status" className="px-3 py-8 text-center text-sm text-muted">
            {t('empty')}
          </p>
        ) : null}

        <p className="border-t border-border px-4 py-2 text-[11px] text-muted">
          {t('hint')}
          {commands.length ? ` · ${t('resultsCount', { count: commands.length })}` : ''}
          {` · ${new Intl.DisplayNames([locale], { type: 'language' }).of(locale) ?? locale}`}
        </p>
      </div>
    </div>
  );
}
