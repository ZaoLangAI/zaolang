'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import { tagLabel } from '@/components/discover/tag-filter';
import { IconClock, IconClose, IconSearch, IconSparkle } from '@/components/ui/icons';
import { usePathname, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { Page, Tag } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';
import {
  addSearchHistory,
  clearSearchHistory,
  readSearchHistory,
  removeSearchHistory,
} from '@/lib/search-history';

/** Trending keywords are the same tag list `TagFilter` shows, already ranked by usage. */
const HOT_KEYWORD_LIMIT = 8;

/**
 * The top bar's search box, with a dropdown of recent and trending searches.
 *
 * Split out of `TopBar` because the suggestions add a second piece of state
 * (the open dropdown) and a fetch that only the search box itself needs.
 */
export function SearchBox() {
  const t = useTranslations('search');
  const tActions = useTranslations('actions');
  const locale = useLocale() as Locale;
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const containerRef = useRef<HTMLDivElement>(null);

  const routeQuery = pathname === '/discover' ? (searchParams.get('q') ?? '') : '';
  const [query, setQuery] = useState(routeQuery);
  const [mirroredQuery, setMirroredQuery] = useState({ pathname, q: routeQuery });
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<string[]>([]);

  // Mirror discover's `q` into the search box (and clear it off-route) so
  // Cmd+K / shared links land with the keyword already filled.
  if (mirroredQuery.pathname !== pathname || mirroredQuery.q !== routeQuery) {
    setMirroredQuery({ pathname, q: routeQuery });
    setQuery(routeQuery);
  }

  const hotTags = useResource<Page<Tag>>(open ? `/v1/tags?limit=${HOT_KEYWORD_LIMIT}` : null);

  // Read the (possibly changed) history fresh each time the dropdown opens,
  // adjusted during render rather than in an effect so it is never a frame
  // stale.
  const [trackedOpen, setTrackedOpen] = useState(false);
  if (open !== trackedOpen) {
    setTrackedOpen(open);
    if (open) setHistory(readSearchHistory());
  }

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const runSearch = (value: string) => {
    const trimmed = value.trim();
    setQuery(trimmed);
    setOpen(false);
    if (trimmed) setHistory(addSearchHistory(trimmed));

    const params = new URLSearchParams();
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

  const hotItems = hotTags.data?.items ?? [];
  const showSuggestions = open && (history.length > 0 || hotItems.length > 0);

  return (
    <div ref={containerRef} className="relative mx-auto hidden w-full min-w-0 max-w-md md:block">
      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          runSearch(query);
        }}
        className="flex h-10 w-full items-center gap-2 rounded-full border border-border bg-surface-soft px-4"
      >
        <IconSearch className="size-4 shrink-0 text-muted" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => setOpen(true)}
          placeholder={tActions('search')}
          aria-label={tActions('search')}
          className="w-full bg-transparent text-sm outline-none placeholder:text-muted"
        />
        <kbd
          aria-hidden="true"
          className="hidden rounded border border-border px-1.5 text-[11px] text-muted lg:block"
        >
          /
        </kbd>
      </form>

      {showSuggestions ? (
        <div className="absolute inset-x-0 top-[calc(100%+8px)] z-40 rounded-[var(--radius-md)] border border-border bg-surface-raised p-3 shadow-raised">
          {history.length > 0 ? (
            <div className="mb-3">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <p className="flex items-center gap-1.5 text-xs font-medium text-muted">
                  <IconClock className="size-3.5" aria-hidden="true" />
                  {t('recentSearches')}
                </p>
                <button
                  type="button"
                  onClick={() => setHistory(clearSearchHistory())}
                  className="text-xs text-muted hover:text-text"
                >
                  {t('clearHistory')}
                </button>
              </div>
              <ul className="flex flex-wrap gap-1.5">
                {history.map((item) => (
                  <li
                    key={item}
                    className="inline-flex items-center gap-1 rounded-full border border-border py-1 pl-3 pr-1.5 text-xs text-muted hover:border-primary/40 hover:text-text"
                  >
                    <button
                      type="button"
                      onClick={() => runSearch(item)}
                      className="max-w-40 truncate"
                    >
                      {item}
                    </button>
                    <button
                      type="button"
                      aria-label={t('removeHistoryItem', { query: item })}
                      onClick={() => setHistory(removeSearchHistory(item))}
                      className="rounded-full p-0.5 text-muted hover:text-text"
                    >
                      <IconClose className="size-3" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {hotItems.length > 0 ? (
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted">
                <IconSparkle className="size-3.5" aria-hidden="true" />
                {t('hotSearches')}
              </p>
              <ul className="flex flex-wrap gap-1.5">
                {hotItems.map((tag) => (
                  <li key={tag.slug}>
                    <button
                      type="button"
                      onClick={() => runSearch(tagLabel(tag, locale))}
                      className="rounded-full border border-border px-3 py-1 text-xs text-muted hover:border-primary/40 hover:text-text"
                    >
                      {tagLabel(tag, locale)}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
