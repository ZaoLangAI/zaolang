'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useState } from 'react';

import { DangerConfirm } from '@/components/admin/danger-confirm';
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
  MediaCandidate,
  Page,
  RolePreset,
} from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { OPERATIONS, capabilitiesForModalities, operationLabelKey } from '@/lib/admin/operations';

/**
 * Creates or edits one agent — never its prompts, which are versioned
 * separately in `AgentSkillEditorDialog`.
 *
 * An agent's role comes from the preset dropdown (`GET /agent-node-presets`),
 * never free text: a role only ever runs if some workflow node type invokes
 * it, so one an operator invented would sit there doing nothing. Several
 * agents may share a role; a workflow node picks between them.
 *
 * The preset also fixes `category`, which decides which half of the form
 * applies: `judgment` agents pin one LLM endpoint (plus a backup), `creative`
 * agents pick media routes with a cost weight each. Those weights are context
 * the routing agent reads, not a ranking coefficient — see
 * `app/agents/router.py`.
 *
 * `role` is fixed after creation because a graph binds an agent for a specific
 * stage, and changing the role underneath it would run the wrong kind of agent
 * there. The backend rejects it too (`AgentProfileUpdateRequest` has no
 * `role`).
 */
export function AgentProfileDialog({
  profile,
  onClose,
  onSaved,
}: {
  profile?: AgentProfile;
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

  const [role, setRole] = useState(profile?.role ?? '');
  const [key, setKey] = useState(profile?.key ?? '');
  const [displayName, setDisplayName] = useState(profile?.display_name ?? '');
  const [description, setDescription] = useState(profile?.description ?? '');
  const [operations, setOperations] = useState<string[]>(profile?.operations ?? []);
  const [isDefault, setIsDefault] = useState(profile?.is_default ?? false);
  const [defaultEndpointId, setDefaultEndpointId] = useState(profile?.default_endpoint_id ?? '');
  const [backupEndpointId, setBackupEndpointId] = useState(profile?.backup_endpoint_id ?? '');
  const [candidates, setCandidates] = useState<MediaCandidate[]>(profile?.media_candidates ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disabling, setDisabling] = useState(false);

  // Needed in both modes: creating reads the dropdown from it, editing reads
  // the role's display name and description.
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
  const isCreative = category === 'creative';
  // Creative roles carry their operations from the preset: a `video_creative`
  // agent that also claimed `text_to_image` would offer the routing agent
  // candidates its prompts were never written for.
  const operationsLocked = isCreative;

  const selectPreset = (nextRole: string) => {
    setRole(nextRole);
    const next = presets?.find((item) => item.role === nextRole);
    if (next?.category === 'creative') {
      setOperations(next.operations ?? []);
      setDefaultEndpointId('');
      setBackupEndpointId('');
    } else {
      setCandidates([]);
    }
  };

  const generalEndpoints = (endpoints ?? []).filter(
    (endpoint) => endpoint.kind === 'general' && endpoint.enabled,
  );

  /** Every `(endpoint, capability)` pair a creative agent of this role may
   * route to — the same catalogue key `app/agents/router.py` builds. */
  const routableCandidates = useMemo(() => {
    const allowed = new Set(operations);
    return (endpoints ?? [])
      .filter((endpoint) => endpoint.kind === 'media' && endpoint.enabled)
      .flatMap((endpoint) => {
        const capabilities =
          endpoint.capabilities ??
          capabilitiesForModalities(
            endpoint.input_modalities ?? [],
            endpoint.output_modalities ?? [],
          );
        return capabilities
          .filter((capability) => allowed.size === 0 || allowed.has(capability))
          .map((capability) => ({ endpoint, capability }));
      });
  }, [endpoints, operations]);

  const candidateOf = (endpointId: string, capability: string) =>
    candidates.find((item) => item.endpoint_id === endpointId && item.capability === capability);

  const toggleCandidate = (endpointId: string, capability: string) =>
    setCandidates((current) =>
      current.some((item) => item.endpoint_id === endpointId && item.capability === capability)
        ? current.filter(
            (item) => !(item.endpoint_id === endpointId && item.capability === capability),
          )
        : [...current, { endpoint_id: endpointId, capability, weight: 100 }],
    );

  const setWeight = (endpointId: string, capability: string, weight: number) =>
    setCandidates((current) =>
      current.map((item) =>
        item.endpoint_id === endpointId && item.capability === capability
          ? { ...item, weight }
          : item,
      ),
    );

  const toggleOperation = (operation: string) =>
    setOperations((current) =>
      current.includes(operation)
        ? current.filter((item) => item !== operation)
        : [...current, operation],
    );

  const keyValid = /^[a-z0-9][a-z0-9-]*$/.test(key);
  const bindingsValid = isCreative ? candidates.length > 0 : true;
  const canSave =
    displayName.trim().length > 0 && role.length > 0 && (isEdit || keyValid) && bindingsValid;

  /** `""` clears a pin server-side; `undefined` leaves it alone. Sending the
   * unchanged value back is harmless and keeps the two branches symmetric. */
  const bindingPayload = () =>
    isCreative
      ? { default_endpoint_id: '', backup_endpoint_id: '', media_candidates: candidates }
      : {
          default_endpoint_id: defaultEndpointId,
          backup_endpoint_id: defaultEndpointId ? backupEndpointId : '',
          media_candidates: [],
        };

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
        });
      } else {
        await adminApi.post<AgentProfile>('/v1/admin/agent-profiles', {
          role,
          key,
          display_name: displayName,
          description,
          operations,
          ...bindingPayload(),
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

  const disable = async (reason: string) => {
    if (!profile) return;
    await adminApi.post<AgentProfile>(`/v1/admin/agent-profiles/${profile.id}/disable`, {
      reason,
      confirm: true,
    });
    notify(t('agentDisabled'), 'success');
    setDisabling(false);
    onSaved();
    onClose();
  };

  const usedBy = profile?.used_by_operations ?? [];
  const operationLabel = (operation: string) => {
    const labelKey = operationLabelKey(operation);
    return labelKey ? tProviders(labelKey) : operation;
  };
  const roleLabel = preset?.display_name ?? role;

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={isEdit ? t('editAgent') : t('newAgent')}
      description={roleLabel ? t('agentDialogDesc', { role: roleLabel }) : t('newAgentDesc')}
    >
      <div className="flex flex-col gap-4">
        {isEdit ? null : (
          <Select
            label={t('rolePreset')}
            hint={t('rolePresetHint')}
            value={role}
            onChange={(event) => selectPreset(event.target.value)}
            options={[
              { value: '', label: t('rolePresetPlaceholder') },
              ...(presets ?? []).map((item) => ({
                value: item.role,
                label: `${categoryLabel(item.category, t)} · ${item.display_name}`,
              })),
            ]}
          />
        )}

        {preset?.description ? <p className="text-xs text-muted">{preset.description}</p> : null}

        {role ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted">{t('categoryLabel')}</span>
            <Badge tone={isCreative ? 'primary' : 'neutral'}>{categoryLabel(category, t)}</Badge>
            <span className="text-xs text-muted">
              {isCreative ? t('categoryCreativeHint') : t('categoryJudgmentHint')}
            </span>
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
          <p className="text-xs text-muted">
            {operationsLocked ? t('capabilitiesLockedHint') : t('capabilitiesHint')}
          </p>
          <div className="flex flex-wrap gap-2">
            {OPERATIONS.map((operation) => {
              const checked = operations.includes(operation);
              if (operationsLocked) {
                return checked ? (
                  <Badge key={operation} tone="neutral">
                    {operationLabel(operation)}
                  </Badge>
                ) : null;
              }
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

        {isCreative ? (
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium text-text">{t('mediaCandidates')}</legend>
            <p className="text-xs text-muted">{t('mediaCandidatesHint')}</p>
            {endpoints === null ? (
              <p className="text-xs text-muted">{t('loading')}</p>
            ) : routableCandidates.length === 0 ? (
              <p className="text-xs text-muted">{t('mediaCandidatesEmpty')}</p>
            ) : (
              <ul className="flex flex-col rounded-[var(--radius-sm)] border border-border">
                {routableCandidates.map(({ endpoint, capability }) => {
                  const selected = candidateOf(endpoint.id, capability);
                  return (
                    <li
                      key={`${endpoint.id}:${capability}`}
                      className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-3 py-2 last:border-b-0"
                    >
                      <label className="flex min-w-0 cursor-pointer items-center gap-2">
                        <input
                          type="checkbox"
                          checked={selected !== undefined}
                          onChange={() => toggleCandidate(endpoint.id, capability)}
                        />
                        <span className="truncate text-sm text-text">{endpoint.name}</span>
                        <Badge tone="neutral">{operationLabel(capability)}</Badge>
                      </label>
                      {selected ? (
                        <label className="flex items-center gap-2 text-xs text-muted">
                          {t('mediaCandidateWeight')}
                          <input
                            type="number"
                            min={1}
                            max={1000}
                            value={selected.weight}
                            onChange={(event) =>
                              setWeight(endpoint.id, capability, Number(event.target.value))
                            }
                            className="h-8 w-20 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2 text-text"
                          />
                        </label>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
            {candidates.length === 0 && routableCandidates.length > 0 ? (
              <p className="text-xs text-amber">{t('mediaCandidatesRequired')}</p>
            ) : null}
          </fieldset>
        ) : (
          <fieldset className="flex flex-col gap-3">
            <legend className="text-sm font-medium text-text">{t('modelBinding')}</legend>
            <p className="text-xs text-muted">{t('modelBindingHint')}</p>
            <Select
              label={t('defaultModel')}
              value={defaultEndpointId}
              onChange={(event) => setDefaultEndpointId(event.target.value)}
              options={[
                { value: '', label: t('modelInherit') },
                ...generalEndpoints.map((endpoint) => ({
                  value: endpoint.id,
                  label: endpoint.name,
                })),
              ]}
            />
            <Select
              label={t('backupModel')}
              hint={t('backupModelHint')}
              value={backupEndpointId}
              disabled={defaultEndpointId === ''}
              onChange={(event) => setBackupEndpointId(event.target.value)}
              options={[
                { value: '', label: t('backupModelNone') },
                ...generalEndpoints
                  .filter((endpoint) => endpoint.id !== defaultEndpointId)
                  .map((endpoint) => ({ value: endpoint.id, label: endpoint.name })),
              ]}
            />
          </fieldset>
        )}

        {isEdit && !profile.is_default ? (
          <Switch
            label={t('makeDefault')}
            description={t('makeDefaultHint')}
            checked={isDefault}
            onChange={setIsDefault}
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

        <div className="flex items-center justify-between gap-2 border-t border-border pt-4">
          {isEdit && profile.enabled && !profile.is_default ? (
            <Button variant="ghost" onClick={() => setDisabling(true)}>
              {t('disableAgent')}
            </Button>
          ) : (
            <span />
          )}
          <Button loading={busy} disabled={!canSave} onClick={() => void save()}>
            {tAdmin('save')}
          </Button>
        </div>
      </div>

      <DangerConfirm
        open={disabling}
        onClose={() => setDisabling(false)}
        title={t('disableAgent')}
        description={t('disableAgentDesc')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={disable}
      />
    </Dialog>
  );
}

function categoryLabel(category: AgentCategory, t: (key: string) => string): string {
  return category === 'creative' ? t('categoryCreative') : t('categoryJudgment');
}
