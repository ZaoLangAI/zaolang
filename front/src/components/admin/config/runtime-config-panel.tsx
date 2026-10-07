'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { JsonDiff } from '@/components/admin/json-diff';
import { Button } from '@/components/ui/button';
import { Select, Switch, TextArea, TextInput } from '@/components/ui/field';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import {
  ANY_ENTRY_TYPE,
  CONSISTENCY_KINDS,
  type ConsistencyKind,
  type ConsistencyThresholds,
  toggledKinds,
  withDefaultThreshold,
} from '@/lib/admin/asset-consistency';
import { atLeast } from '@/lib/admin/rbac';
import { OPERATIONS, operationLabelKey } from '@/lib/admin/operations';
import { adminApi } from '@/lib/api/admin-client';
import type { ConfigValue, ConfigVersion, Page } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { formatDateTime } from '@/lib/format';

export type RuntimeConfigKind =
  | 'feature_flags'
  | 'shortform'
  | 'pricing'
  | 'royalty'
  | 'marketplace'
  | 'moderation'
  | 'asset_consistency';

// Runtime sections have different strongly validated server schemas; this
// shared editor keeps the JSON-shaped draft while each form below owns its
// field coercion.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Draft = Record<string, any>;

const FLAG_GROUPS = [
  {
    id: 'creation',
    flags: [
      'video_generation',
      'script_studio_enabled',
      'blocking_studio_enabled',
      'video_analysis_enabled',
    ],
  },
  {
    id: 'drama',
    flags: [
      'drama_studio_enabled',
      'web_editor_enabled',
      'variant_export_enabled',
      'editor_ai_enabled',
      'editor_mcp_enabled',
    ],
  },
  {
    id: 'platform',
    flags: ['public_registration', 'marketplace_enabled'],
  },
] as const;

const GROUPED_FLAGS: ReadonlySet<string> = new Set(
  FLAG_GROUPS.flatMap((group) => [...group.flags]),
);
const EDITOR_DEPENDENTS = new Set([
  'variant_export_enabled',
  'editor_ai_enabled',
  'editor_mcp_enabled',
]);

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
  const [jsonValid, setJsonValid] = useState(true);
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
    setJsonValid(true);
    setError(null);
  };

  const applyJson = (text: string) => {
    setJson(text);
    try {
      const parsed = JSON.parse(text);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
        setJsonValid(false);
        setError(t('invalidJson'));
        return;
      }
      setDraft(parsed as Draft);
      setJsonValid(true);
      setError(null);
    } catch {
      setJsonValid(false);
      setError(t('invalidJson'));
    }
  };

  const pending = jsonValid ? draft : null;
  const dirty = useMemo(
    () => jsonValid && JSON.stringify(config.value) !== JSON.stringify(draft),
    [config.value, draft, jsonValid],
  );

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
      setJsonValid(true);
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
    setJsonValid(true);
    setRollbackTo(null);
    await loadHistory();
    notify(t('rolledBack'), 'success');
  };

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-4 sm:p-5">
      <h2 className="text-sm font-semibold">{title}</h2>

      <div className="mt-4">
        <ConfigForm kind={kind} value={draft} disabled={!canEdit} onChange={updateDraft} />
      </div>

      {dirty ? <p className="mt-4 text-xs text-muted">{t('unsavedHint')}</p> : null}

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
      ) : error ? (
        <p role="alert" className="mt-3 text-xs text-danger">
          {error}
        </p>
      ) : null}

      <details className="mt-5 border-t border-border pt-4">
        <summary className="cursor-pointer text-sm font-semibold">{t('advanced')}</summary>
        <p className="mt-3 font-mono text-[11px] text-muted" title={config.key}>
          {t('schemaKey', { key: config.key, version: config.version })}
        </p>
        <div className="mt-3">
          <TextArea
            label={t('value')}
            hint={t('valueHint')}
            rows={12}
            value={json}
            disabled={!canEdit}
            className="font-mono text-xs"
            error={jsonValid ? undefined : t('invalidJson')}
            onChange={(event) => applyJson(event.target.value)}
          />
        </div>
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-semibold">{t('pendingDiff')}</h3>
          <JsonDiff before={config.value} after={pending ?? config.value} />
        </div>
      </details>

      <details className="mt-4 border-t border-border pt-4">
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
    return <FeatureFlagsForm value={value} disabled={disabled} onChange={onChange} />;
  }
  if (kind === 'royalty') {
    return <RoyaltyForm value={value} disabled={disabled} onChange={onChange} />;
  }
  if (kind === 'marketplace') {
    return <MarketplaceForm value={value} disabled={disabled} onChange={onChange} />;
  }
  if (kind === 'pricing') {
    return <PricingForm value={value} disabled={disabled} onChange={onChange} />;
  }
  if (kind === 'asset_consistency') {
    return <AssetConsistencyForm value={value} disabled={disabled} onChange={onChange} />;
  }
  return <ShortformForm value={value} disabled={disabled} onChange={onChange} />;
}

function FeatureFlagsForm({ value, disabled, onChange }: FormProps) {
  const t = useTranslations('adminConfig');
  const extras = Object.keys(value).filter(
    (key) =>
      key !== 'rollout_percentages' && typeof value[key] === 'boolean' && !GROUPED_FLAGS.has(key),
  );
  const groups = [
    ...FLAG_GROUPS.map((group) => ({
      id: group.id,
      title: t(`flagGroups.${group.id}`),
      flags: [...group.flags],
    })),
    ...(extras.length ? [{ id: 'other', title: t('flagGroups.other'), flags: extras }] : []),
  ];

  return (
    <div className="flex flex-col gap-5">
      {groups.map((group) => (
        <div key={group.id}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
            {group.title}
          </h3>
          <ul className="grid gap-3 sm:grid-cols-2">
            {group.flags.map((flag) => {
              const editorLocked = EDITOR_DEPENDENTS.has(flag) && !value.web_editor_enabled;
              const flagDisabled = disabled || editorLocked;
              const title = GROUPED_FLAGS.has(flag) ? t(`flagItems.${flag}.title`) : flag;
              const description = editorLocked
                ? t('editorDependsHint')
                : GROUPED_FLAGS.has(flag)
                  ? t(`flagItems.${flag}.description`)
                  : flag;
              return (
                <li
                  key={flag}
                  title={flag}
                  className="rounded-[var(--radius-sm)] border border-border p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <Switch
                        label={title}
                        description={description}
                        checked={Boolean(value[flag])}
                        disabled={flagDisabled}
                        onChange={(checked) => onChange({ ...value, [flag]: checked })}
                      />
                    </div>
                    <Badge tone={value[flag] ? 'success' : 'neutral'}>
                      {value[flag] ? t('flagOn') : t('flagOff')}
                    </Badge>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

function RoyaltyForm({ value, disabled, onChange }: FormProps) {
  const t = useTranslations('adminConfig');
  return (
    <div className="flex flex-col gap-3">
      <Switch
        label={t('royaltyEnabled')}
        checked={Boolean(value.enabled)}
        disabled={disabled}
        onChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <TextInput
          label={t('firstLevelRate')}
          type="number"
          min={0}
          max={50}
          step={0.01}
          disabled={disabled}
          value={Number(value.first_level_rate_bps ?? 0) / 100}
          onChange={(event) =>
            onChange({
              ...value,
              first_level_rate_bps: Math.round(Number(event.target.value) * 100),
            })
          }
        />
        <TextInput
          label={t('decayRate')}
          type="number"
          min={0}
          max={100}
          step={0.01}
          disabled={disabled}
          value={Number(value.decay_bps ?? 0) / 100}
          onChange={(event) =>
            onChange({ ...value, decay_bps: Math.round(Number(event.target.value) * 100) })
          }
        />
        <TextInput
          label={t('totalCap')}
          type="number"
          min={0}
          max={100}
          step={0.01}
          disabled={disabled}
          value={Number(value.total_cap_bps ?? 0) / 100}
          onChange={(event) =>
            onChange({ ...value, total_cap_bps: Math.round(Number(event.target.value) * 100) })
          }
        />
        <TextInput
          label={t('maxLevels')}
          type="number"
          min={1}
          disabled={disabled}
          value={value.max_levels ?? 1}
          onChange={(event) => onChange({ ...value, max_levels: Number(event.target.value) })}
        />
        <TextInput
          label={t('minPayout')}
          type="number"
          min={1}
          disabled={disabled}
          value={value.min_payout ?? 1}
          onChange={(event) => onChange({ ...value, min_payout: Number(event.target.value) })}
        />
      </div>
    </div>
  );
}

function MarketplaceForm({ value, disabled, onChange }: FormProps) {
  const t = useTranslations('adminConfig');
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <TextInput
        label={t('platformFee')}
        hint={t('platformFeeHint')}
        type="number"
        min={0}
        max={100}
        step={0.01}
        disabled={disabled}
        value={Number(value.platform_fee_bps ?? 0) / 100}
        onChange={(event) =>
          onChange({
            ...value,
            platform_fee_bps: Math.round(Number(event.target.value) * 100),
          })
        }
      />
      <TextInput
        label={t('maxAccessCredits')}
        type="number"
        min={1}
        disabled={disabled}
        value={value.max_access_credits ?? 1}
        onChange={(event) => onChange({ ...value, max_access_credits: Number(event.target.value) })}
      />
    </div>
  );
}

/** Mode, scope, per-kind default (`"*"`) thresholds and budgets. A
 * threshold per image type is rarer and stays in the Advanced JSON. */
function AssetConsistencyForm({ value, disabled, onChange }: FormProps) {
  const t = useTranslations('adminConfig');
  const kinds = (value.kinds ?? []) as string[];
  const thresholds = (value.thresholds ?? {}) as ConsistencyThresholds;
  const kindLabel = (kind: ConsistencyKind) =>
    kind === 'character'
      ? t('consistencyKindCharacter')
      : kind === 'scene'
        ? t('consistencyKindScene')
        : t('consistencyKindProp');

  return (
    <div className="flex flex-col gap-4">
      <Select
        label={t('consistencyMode')}
        hint={t('consistencyModeHint')}
        disabled={disabled}
        value={value.mode ?? 'off'}
        onChange={(event) => onChange({ ...value, mode: event.target.value })}
        options={[
          { value: 'off', label: t('consistencyModeOff') },
          { value: 'shadow', label: t('consistencyModeShadow') },
          { value: 'enforce', label: t('consistencyModeEnforce') },
        ]}
      />
      <FieldGroup title={t('consistencyKinds')}>
        {CONSISTENCY_KINDS.map((kind) => (
          <Switch
            key={kind}
            label={kindLabel(kind)}
            checked={kinds.includes(kind)}
            disabled={disabled}
            onChange={(checked) =>
              onChange({ ...value, kinds: toggledKinds(kinds, kind, checked) })
            }
          />
        ))}
      </FieldGroup>
      <div>
        <FieldGroup title={t('consistencyThresholds')}>
          {CONSISTENCY_KINDS.map((kind) => (
            <TextInput
              key={kind}
              label={kindLabel(kind)}
              type="number"
              min={0}
              max={100}
              disabled={disabled}
              value={thresholds[kind]?.[ANY_ENTRY_TYPE] ?? ''}
              onChange={(event) =>
                onChange({
                  ...value,
                  thresholds: withDefaultThreshold(thresholds, kind, event.target.value),
                })
              }
            />
          ))}
        </FieldGroup>
        <p className="mt-2 text-xs text-muted">{t('consistencyThresholdsHint')}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextInput
          label={t('consistencyMaxImagePx')}
          type="number"
          min={512}
          max={2048}
          step={64}
          disabled={disabled}
          value={value.max_image_px ?? 1024}
          onChange={(event) => onChange({ ...value, max_image_px: Number(event.target.value) })}
        />
        <TextInput
          label={t('consistencyMaxOutputs')}
          type="number"
          min={1}
          max={8}
          disabled={disabled}
          value={value.max_outputs_per_job ?? 8}
          onChange={(event) =>
            onChange({ ...value, max_outputs_per_job: Number(event.target.value) })
          }
        />
      </div>
    </div>
  );
}

const TIERS = ['preview', 'standard', 'cinematic'] as const;

function PricingForm({ value, disabled, onChange }: FormProps) {
  const t = useTranslations('adminConfig');
  const tProviders = useTranslations('adminProviders');
  const pricing = (value.tier_pricing ?? {}) as Record<string, Record<string, number>>;
  const surcharge = (value.video_per_second_surcharge ?? {}) as Record<string, number>;
  const tierLabel = (tier: (typeof TIERS)[number]) =>
    tier === 'preview'
      ? t('tierPreview')
      : tier === 'standard'
        ? t('tierStandard')
        : t('tierCinematic');

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr>
            <th className="p-2 text-left">{t('operation')}</th>
            {TIERS.map((tier) => (
              <th key={tier} className="p-2 text-left">
                {tierLabel(tier)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {OPERATIONS.map((operation) => {
            const labelKey = operationLabelKey(operation);
            return (
              <tr key={operation} className="border-t border-border">
                <th className="p-2 text-left text-xs font-medium" title={operation}>
                  {labelKey ? tProviders(labelKey) : operation}
                </th>
                {TIERS.map((tier) => (
                  <td key={tier} className="p-2">
                    <input
                      className="h-9 w-24 rounded border border-border bg-surface-soft px-2"
                      type="number"
                      min={1}
                      disabled={disabled}
                      aria-label={`${labelKey ? tProviders(labelKey) : operation} ${tierLabel(tier)}`}
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
            );
          })}
          <tr className="border-t border-border">
            <th className="p-2 text-left">{t('videoSurcharge')}</th>
            {TIERS.map((tier) => (
              <td key={tier} className="p-2">
                <input
                  className="h-9 w-24 rounded border border-border bg-surface-soft px-2"
                  type="number"
                  min={0}
                  disabled={disabled}
                  aria-label={`${t('videoSurcharge')} ${tierLabel(tier)}`}
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
          label={t('videoBaseSeconds')}
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

const KNOWN_PROFILES = ['douyin_vertical', 'douyin_landscape'] as const;

function profileLabel(t: ReturnType<typeof useTranslations>, key: string): string {
  return (KNOWN_PROFILES as readonly string[]).includes(key) ? t(`profiles.${key}`) : key;
}

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
        label={t('defaultProfile')}
        hint={t('defaultProfileHint')}
        disabled={disabled}
        value={value.default_profile ?? ''}
        onChange={(event) => onChange({ ...value, default_profile: event.target.value })}
        options={Object.keys(profiles).map((key) => ({
          value: key,
          label: profileLabel(t, key),
        }))}
      />
      {Object.entries(profiles).map(([key, profile]) => (
        <fieldset key={key} className="rounded border border-border p-3">
          <legend className="px-1 text-xs font-medium" title={key}>
            {profileLabel(t, key)}
          </legend>
          <div className="flex flex-col gap-4">
            <FieldGroup title={t('groupFrame')}>
              <TextInput
                label={t('aspectRatio')}
                disabled={disabled}
                value={profile.aspect_ratio ?? '9:16'}
                onChange={(event) => updateProfile(key, { aspect_ratio: event.target.value })}
              />
              <TextInput
                label={t('width')}
                type="number"
                min={240}
                max={7680}
                disabled={disabled}
                value={profile.width ?? 240}
                onChange={(event) => updateProfile(key, { width: Number(event.target.value) })}
              />
              <TextInput
                label={t('height')}
                type="number"
                min={240}
                max={7680}
                disabled={disabled}
                value={profile.height ?? 240}
                onChange={(event) => updateProfile(key, { height: Number(event.target.value) })}
              />
            </FieldGroup>
            <FieldGroup title={t('groupDuration')}>
              <TextInput
                label={t('minDuration')}
                type="number"
                min={1}
                max={30}
                disabled={disabled}
                value={profile.min_duration_seconds ?? 1}
                onChange={(event) =>
                  updateProfile(key, { min_duration_seconds: Number(event.target.value) })
                }
              />
              <TextInput
                label={t('maxDuration')}
                type="number"
                min={1}
                max={30}
                disabled={disabled}
                value={profile.max_duration_seconds ?? 1}
                onChange={(event) =>
                  updateProfile(key, { max_duration_seconds: Number(event.target.value) })
                }
              />
            </FieldGroup>
            <FieldGroup title={t('groupCopy')}>
              <TextInput
                label={t('maxTitleLength')}
                type="number"
                min={1}
                max={200}
                disabled={disabled}
                value={profile.max_title_length ?? 1}
                onChange={(event) =>
                  updateProfile(key, { max_title_length: Number(event.target.value) })
                }
              />
              <TextInput
                label={t('maxHashtags')}
                type="number"
                min={0}
                max={30}
                disabled={disabled}
                value={profile.max_hashtags ?? 0}
                onChange={(event) =>
                  updateProfile(key, { max_hashtags: Number(event.target.value) })
                }
              />
            </FieldGroup>
            <FieldGroup title={t('groupSafeArea')}>
              <TextInput
                label={t('safeAreaTop')}
                type="number"
                min={0}
                max={100}
                disabled={disabled}
                value={profile.safe_area_top_pct ?? 0}
                onChange={(event) =>
                  updateProfile(key, { safe_area_top_pct: Number(event.target.value) })
                }
              />
              <TextInput
                label={t('safeAreaBottom')}
                type="number"
                min={0}
                max={100}
                disabled={disabled}
                value={profile.safe_area_bottom_pct ?? 0}
                onChange={(event) =>
                  updateProfile(key, { safe_area_bottom_pct: Number(event.target.value) })
                }
              />
              <TextInput
                label={t('safeAreaRight')}
                type="number"
                min={0}
                max={100}
                disabled={disabled}
                value={profile.safe_area_right_pct ?? 0}
                onChange={(event) =>
                  updateProfile(key, { safe_area_right_pct: Number(event.target.value) })
                }
              />
            </FieldGroup>
          </div>
          <Switch
            label={t('requireAiDisclosure')}
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
            hint={t('newProfileKeyHint')}
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

function FieldGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-muted">{title}</p>
      <div className="grid gap-3 sm:grid-cols-3">{children}</div>
    </div>
  );
}
