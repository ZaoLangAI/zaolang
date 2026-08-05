'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { CreateSkillDialog } from '@/components/skills/create-skill-dialog';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextInput } from '@/components/ui/field';
import { IconCheck, IconCopy, IconSparkle } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import type { ReusableParams, StylePreset, WorkVersionSummary } from '@/lib/api/types';
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
  const { requireAuth } = useSession();
  const { notify } = useToast();
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveSkillOpen, setSaveSkillOpen] = useState(false);

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

  const presetParams: Record<string, unknown> = {};
  if (params.prompt) presetParams.prompt = params.prompt;
  if (typeof extra.aspect_ratio === 'string') presetParams.aspect_ratio = extra.aspect_ratio;
  if ((params.style_tags ?? []).length > 0) presetParams.style_tags = params.style_tags;

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t('reusable')}</h2>
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => requireAuth({ label: tPage('savePreset'), run: () => setSaveOpen(true) })}
            className="flex items-center gap-1 text-xs text-primary hover:underline"
          >
            <IconSparkle className="size-3.5" />
            {tPage('savePreset')}
          </button>
          <button
            type="button"
            onClick={() =>
              requireAuth({ label: tPage('saveSkill'), run: () => setSaveSkillOpen(true) })
            }
            className="flex items-center gap-1 text-xs text-primary hover:underline"
          >
            <IconSparkle className="size-3.5" />
            {tPage('saveSkill')}
          </button>
        </div>
      </div>
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

      <SavePresetDialog
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        params={presetParams}
        derivedFromWorkVersionId={version?.id}
      />

      <CreateSkillDialog
        open={saveSkillOpen}
        onClose={() => setSaveSkillOpen(false)}
        initialParams={presetParams}
        onCreated={() => {
          setSaveSkillOpen(false);
          notify(tPage('saveSkillSuccess'), 'success');
        }}
      />
    </section>
  );
}

function SavePresetDialog({
  open,
  onClose,
  params,
  derivedFromWorkVersionId,
}: {
  open: boolean;
  onClose: () => void;
  params: Record<string, unknown>;
  derivedFromWorkVersionId?: string;
}) {
  const tPage = useTranslations('workPage');
  const tActions = useTranslations('actions');
  const { notify } = useToast();

  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    onClose();
    setName('');
    setError(null);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.post<StylePreset>('/v1/style-presets', {
        name: name.trim(),
        params,
        derived_from_work_version_id: derivedFromWorkVersionId ?? null,
        is_public: false,
      });
      notify(tPage('savePresetSuccess'), 'success');
      close();
    } catch {
      setError(tPage('savePresetFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} title={tPage('savePresetTitle')} size="sm">
      <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
        {error ? <ErrorNotice title={error} /> : null}
        <TextInput
          label={tPage('savePresetNameLabel')}
          required
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <div className="flex items-center justify-end gap-3">
          <Button variant="ghost" onClick={close}>
            {tActions('cancel')}
          </Button>
          <Button type="submit" loading={submitting} disabled={name.trim().length === 0}>
            {tActions('save')}
          </Button>
        </div>
      </form>
    </Dialog>
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
