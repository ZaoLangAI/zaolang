'use client';

import { useLocale, useTranslations } from 'next-intl';

import { Link, usePathname } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { Tag } from '@/lib/api/types';
import { cn } from '@/lib/cn';

/** Tag labels ship in all three languages so one cached response serves every locale. */
export function tagLabel(tag: Tag, locale: Locale): string {
  if (locale === 'en') return tag.label_en;
  if (locale === 'ja') return tag.label_ja;
  return tag.label_zh;
}

const SORT_MODES = ['recent', 'popular', 'remixed'] as const;
type SortMode = (typeof SORT_MODES)[number];

const SORT_LABEL: Record<SortMode, 'sortRecent' | 'sortPopular' | 'sortRemixed'> = {
  recent: 'sortRecent',
  popular: 'sortPopular',
  remixed: 'sortRemixed',
};

function discoverQuery(base: Record<string, string | undefined>) {
  const query: Record<string, string> = {};
  for (const [key, value] of Object.entries(base)) {
    if (value) query[key] = value;
  }
  return Object.keys(query).length > 0 ? query : undefined;
}

/** Drop the default `popular` so a reset link stays `/discover`, not `?sort=popular`. */
function feedQuery({ q, tag, sort }: { q?: string; tag?: string; sort?: string }) {
  return discoverQuery({
    q,
    tag,
    sort: sort && sort !== 'popular' ? sort : undefined,
  });
}

export function TagFilter({
  tags,
  active,
  q,
  sort,
}: {
  tags: Tag[];
  active?: string;
  q?: string;
  sort?: string;
}) {
  const t = useTranslations('discover');
  const locale = useLocale() as Locale;
  const pathname = usePathname();

  if (tags.length === 0) return null;

  const allQuery = feedQuery({ q, sort });

  return (
    <nav aria-label={t('filterTags')} className="no-scrollbar flex gap-2 overflow-x-auto pb-1">
      <Chip href={allQuery ? { pathname, query: allQuery } : pathname} active={!active}>
        {t('allTags')}
      </Chip>
      {tags.map((tag) => (
        <Chip
          key={tag.slug}
          href={{ pathname, query: feedQuery({ q, sort, tag: tag.slug })! }}
          active={active === tag.slug}
        >
          {tagLabel(tag, locale)}
        </Chip>
      ))}
    </nav>
  );
}

export function DiscoverSort({ q, tag, sort }: { q?: string; tag?: string; sort?: string }) {
  const t = useTranslations('discover');
  const pathname = usePathname();
  const active = sort ?? 'popular';

  return (
    <nav aria-label={t('sort')} className="no-scrollbar flex gap-2 overflow-x-auto pb-1">
      {SORT_MODES.map((mode) => {
        const query = feedQuery({ q, tag, sort: mode });
        return (
          <Chip
            key={mode}
            href={query ? { pathname, query } : pathname}
            active={active === mode}
          >
            {t(SORT_LABEL[mode])}
          </Chip>
        );
      })}
    </nav>
  );
}

function Chip({
  href,
  active,
  children,
}: {
  href: React.ComponentProps<typeof Link>['href'];
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? 'true' : undefined}
      scroll={false}
      className={cn(
        'shrink-0 rounded-full border px-3.5 py-1.5 text-xs transition-colors',
        active
          ? 'border-primary bg-primary/12 text-primary'
          : 'border-border text-muted hover:border-border-strong hover:text-text',
      )}
    >
      {children}
    </Link>
  );
}
