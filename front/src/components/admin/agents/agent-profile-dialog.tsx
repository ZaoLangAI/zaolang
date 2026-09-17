'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, Switch, TextArea, TextInput } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { adminApi } from '@/lib/api/admin-client';
import type {
  AgentCategory,
  AgentProfile,
  LlmProviderEndpoint,
  LlmProviderPool,
  Page,
  RolePreset,
} from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { OPERATIONS, operationLabelKey } from '@/lib/admin/operations';

/**
 * Creates or edits one agent — never its prompts, which are versioned
 * separately in `AgentSkillEditorDialog`.
 *
 * An agent's role is fixed before this dialog ever opens: creation starts
 * from the arrow next to a role's heading in `AgentSkillsPanel`, which passes
 * it in as `initialRole`. A role only ever runs if some workflow node type
 * invokes it, so letting an operator type one here would produce an agent
 * that never executes. Several agents may share a role; a workflow node
 * picks between them.
 *
 * The role also fixes `category`, which decides which half of the form
 * applies only semantically: `judgment` and `assist` agents both pin one
 * LLM endpoint (plus a backup) the same way — `assist` is just the semantic
 * label for a role that generates/polishes content rather than handing down
 * a verdict (`copy` is the only one today).
 *
 * `role` stays fixed after creation too, because a graph binds an agent for a
 * specific stage, and changing the role underneath it would run the wrong
 * kind of agent there. The backend rejects it too (`AgentProfileUpdateRequest`
 * has no `role`).
 */
export function AgentProfileDialog({
  profile,
  initialRole,
  onClose,
  onSaved,
}: {
  profile?: AgentProfile;
  /** Which role's arrow was clicked. Ignored once `profile` is set — an
   * existing agent's role never changes. */
  initialRole?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations('adminAgents');
  const tAdmin = useTranslations('admin');
  const tProviders = useTranslations('adminProviders');
  const { notify } = useToast();

  const isEdit = profile !== undefined;
  const [presets, setPresets] = useState<RolePreset[] | null>(null);
  const [endpoints, setEndpoints] = useState<LlmProviderEndpoint[] | null>(null);

  const role = profile?.role ?? initialRole ?? '';
  const [key, setKey] = useState(profile?.key ?? '');
  const [displayName, setDisplayName] = useState(profile?.display_name ?? '');
  const [description, setDescription] = useState(profile?.description ?? '');
  const [manualOperations, setManualOperations] = useState<string[]>(profile?.operations ?? []);
  const [isDefault, setIsDefault] = useState(profile?.is_default ?? false);
  const [defaultEndpointId, setDefaultEndpointId] = useState(profile?.default_endpoint_id ?? '');
  const [backupEndpointId, setBackupEndpointId] = useState(profile?.backup_endpoint_id ?? '');
  const [reasoningModel, setReasoningModel] = useState(
    profile?.reasoning_model === null || profile?.reasoning_model === undefined
      ? ''
      : String(profile.reasoning_model),
  );
  const [assetKindDefault, setAssetKindDefault] = useState(profile?.default_for_asset_kind ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Needed in both modes: creating reads the role's category/description from
  // it, editing reads the role's display name and description.
  useEffect(() => {
    void adminApi
      .get<Page<RolePreset>>('/v1/admin/agent-node-presets')
      .then((page) => setPresets(page.items))
      .catch(() => setPresets([]));
  }, []);

  useEffect(() => {
    void adminApi
      .get<LlmProviderPool>('/v1/admin/llm-providers')
      .then((pool) => setEndpoints(pool.endpoints ?? []))
      .catch(() => setEndpoints([]));
  }, []);

  const preset = presets?.find((item) => item.role === role);
  const category: AgentCategory = profile?.category ?? preset?.category ?? 'judgment';
  const operations = manualOperations;

  const generalEndpoints = (endpoints ?? []).filter(
    (endpoint) => endpoint.kind === 'general' && endpoint.enabled,
  );
  const selectedDefault = generalEndpoints.find((endpoint) => endpoint.id === defaultEndpointId);
  const selectedBackup = generalEndpoints.find((endpoint) => endpoint.id === backupEndpointId);

  const toggleOperation = (operation: string) =>
    setManualOperations((current) =>
      current.includes(operation)
        ? current.filter((item) => item !== operation)
        : [...current, operation],
    );

  const keyValid = /^[a-z0-9][a-z0-9-]*$/.test(key);
  const providerRequired = !isEdit || profile?.is_default;
  const bindingsValid = !providerRequired || Boolean(defaultEndpointId);
  const canSave =
    displayName.trim().length > 0 && role.length > 0 && (isEdit || keyValid) && bindingsValid;

  /** `""` clears a pin server-side; `undefined` leaves it alone. Sending the
   * unchanged value back is harmless and keeps the two branches symmetric.
   *
   * No `model`: an endpoint now serves exactly one model, so the agent binds
   * endpoints and whichever one answers the call decides the model. That is
   * also what makes a backup on another vendor useful — it no longer has to
   * carry an identical model id.
   */
  const bindingPayload = () => ({
    default_endpoint_id: defaultEndpointId,
    backup_endpoint_id: defaultEndpointId ? backupEndpointId : '',
    reasoning_model: reasoningModel === '' ? null : reasoningModel === 'true',
  });

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isEdit) {
        await adminApi.patch<AgentProfile>(`/v1/admin/agent-profiles/${profile.id}`, {
          display_name: displayName,
          description,
          operations,
          // Demoting a default is not a thing — promoting another agent is
          // how you move it — so only ever send the promotion.
          is_default: isDefault && !profile.is_default ? true : undefined,
          ...bindingPayload(),
          ...(role === 'copy' ? { default_for_asset_kind: assetKindDefault || null } : {}),
        });
      } else {
        await adminApi.post<AgentProfile>('/v1/admin/agent-profiles', {
          role,
          key,
          display_name: displayName,
          description,
          operations,
          ...bindingPayload(),
          ...(role === 'copy' ? { default_for_asset_kind: assetKindDefault || null } : {}),
        });
      }
      notify(isEdit ? t('agentSaved') : t('agentCreated'), 'success');
      onSaved();
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const usedBy = profile?.used_by_operations ?? [];
  const operationLabel = (operation: string) => {
    const labelKey = operationLabelKey(operation);
    return labelKey ? tProviders(labelKey) : operation;
  };
  const roleLabel = preset?.display_name ?? role;

  return (
    <Dialog open onClose={onClose} size="lg" title={isEdit ? t('editAgent') : t('newAgent')}>
      <div className="flex flex-col gap-4">
        <p className="text-xs text-muted">
          {t('agentRoleLocked')} <span className="font-medium text-text">{roleLabel}</span>
        </p>

        {preset?.description ? <p className="text-xs text-muted">{preset.description}</p> : null}

        {role ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted">{t('categoryLabel')}</span>
            <Badge tone="neutral">{categoryLabel(category, t)}</Badge>
            <span className="text-xs text-muted">{categoryHint(category, t)}</span>
          </div>
        ) : null}

        {isEdit ? (
          <p className="text-xs text-muted">
            {t('agentHandleLocked')} <span className="font-mono">{profile.key}</span>
          </p>
        ) : (
          <TextInput
            label={t('agentHandle')}
            hint={t('agentHandleHint')}
            value={key}
            error={key.length > 0 && !keyValid ? t('agentHandleInvalid') : undefined}
            onChange={(event) => setKey(event.target.value)}
          />
        )}

        <TextInput
          label={t('agentName')}
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
        />

        <TextArea
          label={t('agentDescription')}
          value={description}
          maxLength={2000}
          onChange={(event) => setDescription(event.target.value)}
        />

        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium text-text">{t('capabilities')}</legend>
          <p className="text-xs text-muted">{t('capabilitiesHint')}</p>
          <div className="flex flex-wrap gap-2">
            {OPERATIONS.map((operation) => {
              const checked = operations.includes(operation);
              return (
                <label
                  key={operation}
                  className={
                    checked
                      ? 'cursor-pointer rounded-[var(--radius-sm)] border border-primary bg-primary/12 px-3 py-1.5 text-xs text-primary'
                      : 'cursor-pointer rounded-[var(--radius-sm)] border border-border px-3 py-1.5 text-xs text-muted hover:text-text'
                  }
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={checked}
                    onChange={() => toggleOperation(operation)}
                  />
                  {operationLabel(operation)}
                </label>
              );
            })}
          </div>
        </fieldset>

        <fieldset className="flex flex-col gap-3">
          <legend className="text-sm font-medium text-text">{t('modelBinding')}</legend>
          <p className="text-xs text-muted">{t('modelBindingHint')}</p>
          <Select
            label={t('defaultProvider')}
            value={defaultEndpointId}
            onChange={(event) => {
              setDefaultEndpointId(event.target.value);
              setBackupEndpointId('');
            }}
            options={[
              { value: '', label: t('modelInherit') },
              ...generalEndpoints.map((endpoint) => ({
                value: endpoint.id,
                label: endpoint.model ? `${endpoint.name} · ${endpoint.model}` : endpoint.name,
              })),
            ]}
          />
          <Select
            label={t('backupProvider')}
            hint={t('backupModelHint')}
            value={backupEndpointId}
            disabled={defaultEndpointId === ''}
            onChange={(event) => setBackupEndpointId(event.target.value)}
            options={[
              { value: '', label: t('backupModelNone') },
              ...generalEndpoints
                .filter((endpoint) => endpoint.id !== defaultEndpointId)
                .map((endpoint) => ({
                  value: endpoint.id,
                  label: endpoint.model ? `${endpoint.name} · ${endpoint.model}` : endpoint.name,
                })),
            ]}
          />
          {selectedDefault ? (
            <p className="text-xs text-muted">
              {t('modelDerived', {
                model: selectedDefault.model || t('modelPlaceholder'),
                backup: selectedBackup?.model || t('backupModelNone'),
              })}
            </p>
          ) : null}
          <p className="text-xs text-muted">{t('samplingInherited')}</p>
          <Select
            label={t('reasoningModel')}
            hint={t('reasoningModelHint')}
            value={reasoningModel}
            onChange={(event) => setReasoningModel(event.target.value)}
            options={[
              { value: '', label: t('inheritPlaceholder') },
              { value: 'true', label: t('enabled') },
              { value: 'false', label: t('disabled') },
            ]}
          />
        </fieldset>

        {isEdit && !profile.is_default ? (
          <Switch
            label={t('makeDefault')}
            description={t('makeDefaultHint')}
            checked={isDefault}
            onChange={setIsDefault}
          />
        ) : null}

        {role === 'copy' ? (
          <Select
            label={t('assetKindDefaultLabel')}
            hint={t('assetKindDefaultHint')}
            value={assetKindDefault}
            onChange={(event) => setAssetKindDefault(event.target.value)}
            options={[
              { value: '', label: t('assetKindDefaultNone') },
              { value: 'copy', label: t('assetKindDefaultCopy') },
              { value: 'character', label: t('assetKindDefaultCharacter') },
              { value: 'scene', label: t('assetKindDefaultScene') },
              { value: 'cover', label: t('assetKindDefaultCover') },
            ]}
          />
        ) : null}

        {isEdit && usedBy.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-xs text-muted">{t('usedBy')}</span>
            {usedBy.map((operation) => (
              <Badge key={operation} tone="success">
                {operationLabel(operation)}
              </Badge>
            ))}
          </div>
        ) : null}

        {error ? <ErrorNotice title={error} /> : null}

        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <Button loading={busy} disabled={!canSave} onClick={() => void save()}>
            {tAdmin('save')}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function categoryLabel(category: AgentCategory, t: (key: string) => string): string {
  if (category === 'assist') return t('categoryAssist');
  return t('categoryJudgment');
}

function categoryHint(category: AgentCategory, t: (key: string) => string): string {
  if (category === 'assist') return t('categoryAssistHint');
  return t('categoryJudgmentHint');
}
