'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { IconCheck, IconCopy } from '@/components/ui/icons';
import type { ReusableParams, WorkVersionSummary } from '@/lib/api/types';
import { formatDate } from '@/lib/format';
import { useLocale } from 'next-intl';
import type { Locale } from '@/i18n/routing';

/**
 * "Reusable assets and parameters" from the design.
 *
 * Only what the licence actually permits is present — the backend returns an
 * empty payload for a view-only work — so the panel never advertises something
 * the viewer is not allowed to take.
 */
export function ReusableParamsList({
  params,
  version,
}: {
  params: ReusableParams;
  version?: WorkVersionSummary | null;
}) {
  const t = useTranslations('work');
  const tPage = useTranslations('workPage');
  const locale = useLocale() as Locale;

  const extra = params.extra ?? {};
  const rows = [
    { key: 'prompt', label: t('prompt'), value: params.prompt, copy: params.prompt },
    {
      key: 'base',
      label: t('baseParams'),
      value: describeBase(extra),
      copy: JSON.stringify(extra, null, 2),
    },
    {
      key: 'style',
      label: t('modelStyle'),
      value: (params.style_tags ?? []).join(' · '),
      copy: (params.style_tags ?? []).join(', '),
    },
    {
      key: 'workflow',
      label: t('workflowVersion'),
      value: version
        ? `v${version.version_number} · ${formatDate(version.created_at, locale)}`
        : params.workflow_version_id,
      copy: params.workflow_version_id,
    },
  ].filter((row) => row.value);

  if (rows.length === 0) return null;

  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold">{t('reusable')}</h2>
      <ul className="divide-y divide-border overflow-hidden rounded-[var(--radius-sm)] border border-border">
        {rows.map((row) => (
          <li key={row.key} className="flex items-center gap-3 bg-surface-soft px-3 py-2.5">
            <span className="w-20 shrink-0 text-xs text-amber">{row.label}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-muted" title={String(row.value)}>
              {row.value}
            </span>
            <CopyButton value={String(row.copy ?? row.value)} label={tPage('copyParams')} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function describeBase(extra: Record<string, unknown>): string {
  const parts: string[] = [];
  if (typeof extra.duration_seconds === 'number') parts.push(`${extra.duration_seconds}s`);
  if (typeof extra.resolution === 'string') parts.push(extra.resolution);
  if (typeof extra.fps === 'number') parts.push(`${extra.fps}fps`);
  if (typeof extra.aspect_ratio === 'string') parts.push(extra.aspect_ratio);
  return parts.join(' | ');
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const tActions = useTranslations('actions');
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      aria-label={copied ? tActions('copied') : label}
      onClick={() => {
        void navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      }}
      className="shrink-0 text-muted transition-colors hover:text-text"
    >
      {copied ? <IconCheck className="size-4 text-success" /> : <IconCopy className="size-4" />}
    </button>
  );
}
