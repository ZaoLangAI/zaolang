'use client';

import { useLocale, useTranslations } from 'next-intl';

import { DataTable, type Column } from '@/components/admin/data-table';
import type { Locale } from '@/i18n/routing';
import { useAdminList } from '@/lib/admin/use-admin-list';
import type { components } from '@/lib/api/schema';
import { formatDateTime } from '@/lib/format';

type DuplicateGroup = components['schemas']['FingerprintDuplicateGroup'];

/** Exact perceptual-hash collisions, which is what a reused upload looks like. */
export function DuplicateGroups() {
  const t = useTranslations('adminModeration');
  const locale = useLocale() as Locale;

  const list = useAdminList<DuplicateGroup>('/v1/admin/fingerprints/duplicates');

  const columns: Array<Column<DuplicateGroup>> = [
    {
      id: 'fingerprint',
      header: 'pHash',
      render: (group) => <span className="font-mono text-xs">{group.fingerprint}</span>,
    },
    {
      id: 'assets',
      header: t('colSubject'),
      render: (group) => (
        <span className="font-mono text-[11px] text-muted">{group.asset_ids.join(', ')}</span>
      ),
    },
    {
      id: 'owners',
      header: t('colStatus'),
      render: (group) => (
        <span className="font-mono text-[11px] text-muted">{group.owner_user_ids.join(', ')}</span>
      ),
    },
    {
      id: 'first',
      header: t('colScore'),
      render: (group) => (
        <span className="tabular whitespace-nowrap text-xs text-muted">
          {formatDateTime(group.first_seen_at, locale)}
        </span>
      ),
    },
  ];

  return (
    <section>
      <h2 className="text-sm font-semibold">{t('duplicates')}</h2>
      <p className="mb-3 mt-1 text-xs text-muted">{t('duplicatesHint')}</p>
      <DataTable
        caption={t('duplicates')}
        columns={columns}
        rows={list.rows}
        rowKey={(group) => group.fingerprint}
        loading={list.loading}
        failed={list.failed}
      />
    </section>
  );
}
