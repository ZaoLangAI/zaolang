'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { StyleGalleryFormDialog } from '@/components/admin/style-gallery/style-gallery-form-dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type { StyleGalleryAdminEntry } from '@/lib/api/admin-types';

/**
 * Back office for the system style catalogue.
 *
 * Unlike the moderation-style consoles elsewhere in `/admin`, every row here
 * is operator-authored — there is no public submission queue to review — so
 * this is a plain CRUD table with its own create/edit dialog instead of a
 * detail drawer over content someone else wrote.
 */
export function StyleGalleryConsole() {
  const t = useTranslations('adminStyleGallery');
  const tAdmin = useTranslations('admin');
  const { notify } = useToast();

  const list = useAdminList<StyleGalleryAdminEntry>('/v1/admin/style-gallery', { pageSize: 200 });
  const [editing, setEditing] = useState<StyleGalleryAdminEntry | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<StyleGalleryAdminEntry | null>(null);

  const handleSaved = (_entry: StyleGalleryAdminEntry) => {
    notify(creating ? t('created') : t('updated'), 'success');
    setCreating(false);
    setEditing(null);
    list.reload();
  };

  const handleDelete = async (reason: string) => {
    if (!deleting) return;
    await adminApi.post(`/v1/admin/style-gallery/${deleting.id}/delete`, { reason, confirm: true });
    notify(t('deleted'), 'success');
    list.reload();
  };

  const columns: Array<Column<StyleGalleryAdminEntry>> = [
    {
      id: 'label',
      header: t('columnLabel'),
      render: (row) => (
        <div className="flex items-center gap-2.5">
          <span className="relative block size-10 shrink-0 overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface-soft">
            {row.cover_url ? (
              <Image src={row.cover_url} alt="" fill sizes="40px" className="object-cover" />
            ) : null}
          </span>
          <div className="min-w-0">
            <p className="truncate text-xs font-medium">{row.label_zh}</p>
            <p className="truncate text-[11px] text-muted">{row.label_en}</p>
          </div>
        </div>
      ),
    },
    {
      id: 'slug',
      header: t('columnSlug'),
      render: (row) => <span className="font-mono text-[11px] text-muted">{row.slug}</span>,
    },
    {
      id: 'sort_order',
      header: t('columnSortOrder'),
      numeric: true,
      render: (row) => <span className="text-xs">{row.sort_order}</span>,
    },
    {
      id: 'apply_count',
      header: t('columnApplyCount'),
      numeric: true,
      render: (row) => <span className="tabular text-xs">{row.apply_count}</span>,
    },
    {
      id: 'status',
      header: t('columnStatus'),
      render: (row) => (
        <Badge tone={row.is_active ? 'success' : 'neutral'}>
          {row.is_active ? t('active') : t('inactive')}
        </Badge>
      ),
    },
    {
      id: 'actions',
      header: t('columnActions'),
      render: (row) => (
        <Button
          size="sm"
          variant="ghost"
          onClick={(event) => {
            event.stopPropagation();
            setDeleting(row);
          }}
        >
          {t('delete')}
        </Button>
      ),
    },
  ];

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-end gap-2">
        <Button size="sm" variant="secondary" onClick={list.reload}>
          {tAdmin('refresh')}
        </Button>
        <Button size="sm" onClick={() => setCreating(true)}>
          {t('create')}
        </Button>
      </div>

      <div className="mt-3">
        <DataTable
          caption={t('title')}
          columns={columns}
          rows={list.rows}
          rowKey={(row) => row.id}
          loading={list.loading}
          failed={list.failed}
          onRowClick={setEditing}
        />
      </div>

      <StyleGalleryFormDialog
        open={creating}
        onClose={() => setCreating(false)}
        entry={null}
        onSaved={handleSaved}
      />
      <StyleGalleryFormDialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        entry={editing}
        onSaved={handleSaved}
      />

      <DangerConfirm
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title={t('deleteTitle')}
        description={t('deleteConfirm', { label: deleting?.label_zh ?? '' })}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={handleDelete}
      />
    </div>
  );
}
