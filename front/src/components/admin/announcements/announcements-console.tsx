'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { Button } from '@/components/ui/button';
import { Select, Switch, TextArea, TextInput } from '@/components/ui/field';
import { Badge, EmptyState } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type { Announcement } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { formatDateTime } from '@/lib/format';

const KINDS = ['notice', 'maintenance', 'incident'] as const;

export function AnnouncementsConsole({ initial }: { initial: Announcement[] }) {
  const t = useTranslations('adminAnnouncements');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();

  const [items, setItems] = useState(initial);
  const [kind, setKind] = useState<(typeof KINDS)[number]>('notice');
  const [titleZh, setTitleZh] = useState('');
  const [titleEn, setTitleEn] = useState('');
  const [bodyZh, setBodyZh] = useState('');
  const [bodyEn, setBodyEn] = useState('');
  const [publish, setPublish] = useState(true);
  const [broadcast, setBroadcast] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const canPublish = atLeast(role, 'operator');
  const complete = Boolean(titleZh && titleEn && bodyZh && bodyEn);

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const created = await adminApi.post<Announcement>('/v1/admin/announcements', {
        kind,
        title_zh: titleZh,
        title_en: titleEn,
        body_zh: bodyZh,
        body_en: bodyEn,
        is_published: publish,
        broadcast,
      });
      setItems((current) => [created, ...current]);
      setTitleZh('');
      setTitleEn('');
      setBodyZh('');
      setBodyEn('');
      setBroadcast(false);
      notify(t('created'), 'success');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,380px)]">
      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('published')}</h2>
        {items.length === 0 ? (
          <EmptyState title={tAdmin('empty')} description={t('subtitle')} />
        ) : (
          <ul className="flex flex-col gap-3">
            {items.map((item) => (
              <li
                key={item.id}
                className="rounded-[var(--radius-md)] border border-border bg-surface p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    tone={
                      item.kind === 'incident'
                        ? 'danger'
                        : item.kind === 'maintenance'
                          ? 'amber'
                          : 'neutral'
                    }
                  >
                    {t(`kind_${item.kind}` as 'kind_notice')}
                  </Badge>
                  {item.is_published ? (
                    <Badge tone="success">{t('statusPublished')}</Badge>
                  ) : (
                    <Badge tone="neutral">{t('statusDraft')}</Badge>
                  )}
                  <span className="tabular ml-auto text-[11px] text-muted">
                    {formatDateTime(item.starts_at, locale)}
                  </span>
                </div>
                <h3 className="mt-2 text-sm font-medium">
                  {locale === 'zh-CN' ? item.title_zh : item.title_en}
                </h3>
                <p className="mt-1 whitespace-pre-line text-xs text-muted">
                  {locale === 'zh-CN' ? item.body_zh : item.body_en}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {canPublish ? (
        <section className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <h2 className="mb-3 text-sm font-semibold">{t('compose')}</h2>
          <div className="flex flex-col gap-3">
            <Select
              label={t('kind')}
              value={kind}
              onChange={(event) => setKind(event.target.value as (typeof KINDS)[number])}
              options={KINDS.map((value) => ({
                value,
                label: t(`kind_${value}` as 'kind_notice'),
              }))}
            />
            <TextInput
              label={t('titleZh')}
              value={titleZh}
              onChange={(e) => setTitleZh(e.target.value)}
            />
            <TextInput
              label={t('titleEn')}
              value={titleEn}
              onChange={(e) => setTitleEn(e.target.value)}
            />
            <TextArea
              label={t('bodyZh')}
              value={bodyZh}
              onChange={(e) => setBodyZh(e.target.value)}
              rows={4}
            />
            <TextArea
              label={t('bodyEn')}
              value={bodyEn}
              onChange={(e) => setBodyEn(e.target.value)}
              rows={4}
            />

            <Switch label={t('publishNow')} checked={publish} onChange={setPublish} />
            <Switch
              label={t('broadcast')}
              description={t('broadcastHint')}
              checked={broadcast}
              disabled={!publish}
              onChange={setBroadcast}
            />

            {error ? (
              <p role="alert" className="text-xs text-danger">
                {error}
              </p>
            ) : null}

            <Button size="sm" disabled={!complete} loading={saving} onClick={() => void submit()}>
              {t('create')}
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
