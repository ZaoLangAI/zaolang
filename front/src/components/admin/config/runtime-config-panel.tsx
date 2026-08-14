'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { JsonDiff } from '@/components/admin/json-diff';
import { Button } from '@/components/ui/button';
import { Select, Switch, TextArea, TextInput } from '@/components/ui/field';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { OPERATIONS } from '@/lib/admin/operations';
import { adminApi } from '@/lib/api/admin-client';
import type { ConfigValue, ConfigVersion, Page } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { formatDateTime } from '@/lib/format';

export type RuntimeConfigKind =
  'feature_flags' | 'shortform' | 'pricing' | 'royalty' | 'moderation';

// Runtime sections have different strongly validated server schemas; this
// shared editor keeps the JSON-shaped draft while each form below owns its
// field coercion.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Draft = Record<string, any>;

export function RuntimeConfigPanel({
  initial,
  kind,
  title,
}: {
  initial: ConfigValue;
  kind: RuntimeConfigKind;
  title: string;
}) {
  const t = useTranslations('adminConfig');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const { role } = useAdminSession();
  const { notify } = useToast();
  const canEdit = atLeast(role, 'admin');

  const [config, setConfig] = useState(initial);
  const [draft, setDraft] = useState<Draft>(initial.value as Draft);
  const [json, setJson] = useState(JSON.stringify(initial.value, null, 2));
  const [mode, setMode] = useState<'form' | 'json'>('form');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState<ConfigVersion[]>([]);
  const [rollbackTo, setRollbackTo] = useState<ConfigVersion | null>(null);

  const loadHistory = async () => {
    const page = await adminApi.get<Page<ConfigVersion>>(`/v1/admin/config/${config.key}/history`);
    setHistory(page.items);
  };

  useEffect(() => {
    let cancelled = false;
    void adminApi
      .get<Page<ConfigVersion>>(`/v1/admin/config/${config.key}/history`)
      .then((page) => {
        if (!cancelled) setHistory(page.items);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [config.key]);

  const updateDraft = (next: Draft) => {
    setDraft(next);
    setJson(JSON.stringify(next, null, 2));
    setError(null);
  };

  const switchMode = (next: 'form' | 'json') => {
    if (next === mode) return;
    if (next === 'form') {
      try {
        const parsed = JSON.parse(json);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error();
        setDraft(parsed as Draft);
      } catch {
        setError(t('invalidJson'));
        return;
      }
    } else {
      setJson(JSON.stringify(draft, null, 2));
    }
    setError(null);
    setMode(next);
  };

  const parsedDraft = (): Draft | null => {
    if (mode === 'form') return draft;
    try {
      const parsed = JSON.parse(json);
      return parsed && !Array.isArray(parsed) && typeof parsed === 'object'
        ? (parsed as Draft)
        : null;
    } catch {
      return null;
    }
  };
  const pending = parsedDraft();

  const save = async () => {
    if (!pending) {
      setError(t('invalidJson'));
      return;
    }
    if (!note.trim()) {
      setError(t('noteRequired'));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await adminApi.put<ConfigValue>(`/v1/admin/config/${config.key}`, {
        value: pending,
        note: note.trim(),
      });
      setConfig(updated);
      setDraft(updated.value as Draft);
      setJson(JSON.stringify(updated.value, null, 2));
      setNote('');
      await loadHistory();
      notify(t('saved'), 'success');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setSaving(false);
    }
  };

  const rollback = async (reason: string) => {
    if (!rollbackTo) return;
    const updated = await adminApi.post<ConfigValue>(`/v1/admin/config/${config.key}/rollback`, {
      target_version: rollbackTo.version,
      reason,
      confirm: true,
    });
    setConfig(updated);
    setDraft(updated.value as Draft);
    setJson(JSON.stringify(updated.value, null, 2));
    setRollbackTo(null);
    await loadHistory();
    notify(t('rolledBack'), 'success');
  };

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="mt-0.5 font-mono text-[11px] text-muted">
            {config.key} · v{config.version}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={mode === 'form' ? 'secondary' : 'ghost'}
            onClick={() => switchMode('form')}
          >
            {t('formMode')}
          </Button>
          <Button
            size="sm"
            variant={mode === 'json' ? 'secondary' : 'ghost'}
            onClick={() => switchMode('json')}
          >
            JSON
          </Button>
        </div>
      </div>

      {mode === 'json' ? (
        <TextArea
          label={t('value')}
          rows={14}
          value={json}
          disabled={!canEdit}
          className="font-mono text-xs"
          error={error ?? undefined}
          onChange={(event) => {
            setJson(event.target.value);
            setError(null);
          }}
        />
      ) : (
        <ConfigForm kind={kind} value={draft} disabled={!canEdit} onChange={updateDraft} />
      )}

      <div className="mt-5">
        <h3 className="mb-2 text-sm font-semibold">{t('pendingDiff')}</h3>
        <JsonDiff before={config.value} after={pending ?? config.value} />
      </div>

      {canEdit ? (
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <TextInput
            label={t('note')}
            required
            value={note}
            onChange={(event) => setNote(event.target.value)}
            className="min-w-[240px] flex-1"
            error={error ?? undefined}
          />
          <Button size="sm" loading={saving} disabled={!pending} onClick={() => void save()}>
            {tAdmin('save')}
          </Button>
        </div>
      ) : null}

      <details className="mt-5 border-t border-border pt-4">
        <summary className="cursor-pointer text-sm font-semibold">{t('history')}</summary>
        <ul className="mt-3 flex flex-col gap-2">
          {history.map((version) => (
            <li
              key={version.version}
              className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-sm)] bg-surface-soft px-3 py-2"
            >
              <span className="text-xs">
                v{version.version}{' '}
                {version.is_active ? <Badge tone="success">{t('activeVersion')}</Badge> : null}
                <span className="ml-2 text-muted">
                  {formatDateTime(version.created_at, locale)}
                  {version.note ? ` · ${version.note}` : ''}
                </span>
              </span>
              {canEdit && !version.is_active ? (
                <Button size="sm" variant="ghost" onClick={() => setRollbackTo(version)}>
                  {t('rollback')}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      </details>

      <DangerConfirm
        open={rollbackTo !== null}
        onClose={() => setRollbackTo(null)}
        title={t('rollback')}
        description={t('rollbackHint', { version: rollbackTo?.version ?? 0 })}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={rollback}
      />
    </section>
  );
}

function ConfigForm({
  kind,
  value,
  disabled,
  onChange,
}: {
  kind: RuntimeConfigKind;
  value: Draft;
  disabled: boolean;
  onChange: (next: Draft) => void;
}) {
  const t = useTranslations('adminConfig');
  if (kind === 'moderation') {
    return (
      <TextArea
        label={t('blockedKeywords')}
        hint={t('blockedKeywordsHint')}
        rows={8}
        disabled={disabled}
        value={(value.blocked_keywords ?? []).join('\n')}
        onChange={(event) =>
          onChange({
            ...value,
            blocked_keywords: event.target.value
              .split('\n')
              .map((item) => item.trim())
              .filter(Boolean),
          })
        }
      />
    );
  }

  if (kind === 'feature_flags') {
    const rollout = (value.rollout_percentages ?? {}) as Record<string, number>;
    return (
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          'video_generation',
          'public_registration',
          'shortform_studio',
          'drama_studio_enabled',
          'web_editor_enabled',
          'variant_export_enabled',
          'editor_ai_enabled',
          'editor_mcp_enabled',
        ].map((flag) => (
          <div key={flag} className="rounded-[var(--radius-sm)] border border-border p-3">
            <Switch
              label={flag}
              checked={Boolean(value[flag])}
              disabled={disabled}
              onChange={(checked) => onChange({ ...value, [flag]: checked })}
            />
            {flag !== 'public_registration' ? (
              <TextInput
                label={t('rolloutPercent')}
                type="number"
                min={0}
                max={100}
                disabled={disabled || !value[flag]}
                value={rollout[flag] ?? 100}
                onChange={(event) =>
                  onChange({
                    ...value,
                    rollout_percentages: { ...rollout, [flag]: Number(event.target.value) },
                  })
                }
              />
            ) : null}
          </div>
        ))}
      </div>
    );
  }

  if (kind === 'royalty') {
    return (
      <div className="flex flex-col gap-3">
        <Switch
          label="enabled"
          checked={Boolean(value.enabled)}
          disabled={disabled}
          onChange={(enabled) => onChange({ ...value, enabled })}
        />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(['first_level_rate_bps', 'decay_bps', 'total_cap_bps'] as const).map((field) => (
            <TextInput
              key={field}
              label={`${field.replace('_bps', '')} (%)`}
              type="number"
              min={0}
              max={field === 'first_level_rate_bps' ? 50 : 100}
              step={0.01}
              disabled={disabled}
              value={Number(value[field] ?? 0) / 100}
              onChange={(event) =>
                onChange({ ...value, [field]: Math.round(Number(event.target.value) * 100) })
              }
            />
          ))}
          {(['max_levels', 'min_payout'] as const).map((field) => (
            <TextInput
              key={field}
              label={field}
              type="number"
              min={1}
              disabled={disabled}
              value={value[field] ?? 1}
              onChange={(event) => onChange({ ...value, [field]: Number(event.target.value) })}
            />
          ))}
        </div>
      </div>
    );
  }

  if (kind === 'pricing')
    return <PricingForm value={value} disabled={disabled} onChange={onChange} />;
  return <ShortformForm value={value} disabled={disabled} onChange={onChange} />;
}

const TIERS = ['preview', 'standard', 'cinematic'] as const;

function PricingForm({ value, disabled, onChange }: FormProps) {
  const t = useTranslations('adminConfig');
  const pricing = (value.tier_pricing ?? {}) as Record<string, Record<string, number>>;
  const surcharge = (value.video_per_second_surcharge ?? {}) as Record<string, number>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr>
            <th className="p-2 text-left">{t('operation')}</th>
            {TIERS.map((tier) => (
              <th key={tier} className="p-2 text-left">
                {tier}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {OPERATIONS.map((operation) => (
            <tr key={operation} className="border-t border-border">
              <th className="p-2 text-left font-mono text-xs">{operation}</th>
              {TIERS.map((tier) => (
                <td key={tier} className="p-2">
                  <input
                    className="h-9 w-24 rounded border border-border bg-surface-soft px-2"
                    type="number"
                    min={1}
                    disabled={disabled}
                    value={pricing[operation]?.[tier] ?? 1}
                    onChange={(event) =>
                      onChange({
                        ...value,
                        tier_pricing: {
                          ...pricing,
                          [operation]: {
                            ...(pricing[operation] ?? {}),
                            [tier]: Number(event.target.value),
                          },
                        },
                      })
                    }
                  />
                </td>
              ))}
            </tr>
          ))}
          <tr className="border-t border-border">
            <th className="p-2 text-left">{t('videoSurcharge')}</th>
            {TIERS.map((tier) => (
              <td key={tier} className="p-2">
                <input
                  className="h-9 w-24 rounded border border-border bg-surface-soft px-2"
                  type="number"
                  min={0}
                  disabled={disabled}
                  value={surcharge[tier] ?? 0}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      video_per_second_surcharge: {
                        ...surcharge,
                        [tier]: Number(event.target.value),
                      },
                    })
                  }
                />
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      <div className="mt-3 max-w-xs">
        <TextInput
          label="video_base_seconds"
          type="number"
          min={0}
          max={60}
          disabled={disabled}
          value={value.video_base_seconds ?? 4}
          onChange={(event) =>
            onChange({ ...value, video_base_seconds: Number(event.target.value) })
          }
        />
      </div>
    </div>
  );
}

interface FormProps {
  value: Draft;
  disabled: boolean;
  onChange: (next: Draft) => void;
}

const SHORTFORM_FIELDS: Array<[string, number, number]> = [
  ['width', 240, 7680],
  ['height', 240, 7680],
  ['min_duration_seconds', 1, 30],
  ['max_duration_seconds', 1, 30],
  ['max_title_length', 1, 200],
  ['max_hashtags', 0, 30],
  ['safe_area_top_pct', 0, 100],
  ['safe_area_bottom_pct', 0, 100],
  ['safe_area_right_pct', 0, 100],
];

function ShortformForm({ value, disabled, onChange }: FormProps) {
  const t = useTranslations('adminConfig');
  const profiles = (value.profiles ?? {}) as Record<string, Draft>;
  const [newKey, setNewKey] = useState('');
  const updateProfile = (key: string, patch: Draft) =>
    onChange({ ...value, profiles: { ...profiles, [key]: { ...profiles[key], ...patch } } });
  const add = () => {
    const key = newKey.trim();
    if (!key || profiles[key]) return;
    onChange({
      ...value,
      profiles: {
        ...profiles,
        [key]: {
          aspect_ratio: '9:16',
          width: 1080,
          height: 1920,
          min_duration_seconds: 5,
          max_duration_seconds: 30,
          max_title_length: 55,
          max_hashtags: 5,
          safe_area_top_pct: 12,
          safe_area_bottom_pct: 22,
          safe_area_right_pct: 18,
          require_ai_disclosure: true,
        },
      },
    });
    setNewKey('');
  };
  return (
    <div className="flex flex-col gap-4">
      <Select
        label="default_profile"
        disabled={disabled}
        value={value.default_profile ?? ''}
        onChange={(event) => onChange({ ...value, default_profile: event.target.value })}
        options={Object.keys(profiles).map((key) => ({ value: key, label: key }))}
      />
      <div className="grid gap-3 rounded-[var(--radius-sm)] border border-border p-3 sm:grid-cols-3">
        <Switch
          label="enable_clarifying_questions"
          checked={value.enable_clarifying_questions ?? true}
          disabled={disabled}
          onChange={(checked) => onChange({ ...value, enable_clarifying_questions: checked })}
        />
        <Switch
          label="enable_preview_picker"
          checked={value.enable_preview_picker ?? true}
          disabled={disabled}
          onChange={(checked) => onChange({ ...value, enable_preview_picker: checked })}
        />
        <TextInput
          label="preview_candidate_count"
          type="number"
          min={2}
          max={3}
          disabled={disabled || !value.enable_preview_picker}
          value={value.preview_candidate_count ?? 3}
          onChange={(event) =>
            onChange({ ...value, preview_candidate_count: Number(event.target.value) })
          }
        />
      </div>
      {Object.entries(profiles).map(([key, profile]) => (
        <fieldset key={key} className="rounded border border-border p-3">
          <legend className="px-1 font-mono text-xs">{key}</legend>
          <div className="grid gap-3 sm:grid-cols-3">
            <TextInput
              label="aspect_ratio"
              disabled={disabled}
              value={profile.aspect_ratio ?? '9:16'}
              onChange={(event) => updateProfile(key, { aspect_ratio: event.target.value })}
            />
            {SHORTFORM_FIELDS.map(([field, min, max]) => (
              <TextInput
                key={field}
                label={field}
                type="number"
                min={min}
                max={max}
                disabled={disabled}
                value={profile[field] ?? min}
                onChange={(event) => updateProfile(key, { [field]: Number(event.target.value) })}
              />
            ))}
          </div>
          <Switch
            label="require_ai_disclosure"
            checked={Boolean(profile.require_ai_disclosure)}
            disabled={disabled}
            onChange={(checked) => updateProfile(key, { require_ai_disclosure: checked })}
          />
          {!disabled ? (
            <Button
              size="sm"
              variant="ghost"
              disabled={Object.keys(profiles).length === 1 || value.default_profile === key}
              onClick={() => {
                const next = { ...profiles };
                delete next[key];
                onChange({ ...value, profiles: next });
              }}
            >
              {t('removeProfile')}
            </Button>
          ) : null}
        </fieldset>
      ))}
      {!disabled ? (
        <div className="flex items-end gap-2">
          <TextInput
            label={t('newProfileKey')}
            value={newKey}
            onChange={(event) => setNewKey(event.target.value)}
          />
          <Button size="sm" variant="secondary" onClick={add}>
            {t('addProfile')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
