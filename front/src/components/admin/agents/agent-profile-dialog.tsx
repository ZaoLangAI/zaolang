'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Switch, TextArea, TextInput } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { adminApi } from '@/lib/api/admin-client';
import type { AgentNode, AgentProfile } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { OPERATIONS, operationLabelKey } from '@/lib/admin/operations';

/**
 * Creates or edits one agent variant's metadata — never its prompts, which
 * are versioned separately in `AgentSkillEditorDialog`.
 *
 * `role` and `key` are only editable while creating: published workflow
 * graphs bind a variant by `role/key`, so allowing a rename here would
 * silently re-point live workflows at a different prompt. The backend
 * rejects it too (`AgentProfileUpdateRequest` has neither field).
 */
export function AgentProfileDialog({
  node,
  profile,
  onClose,
  onSaved,
}: {
  node: AgentNode;
  profile?: AgentProfile;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations('adminAgents');
  const tAdmin = useTranslations('admin');
  const tProviders = useTranslations('adminProviders');
  const { notify } = useToast();

  const isEdit = profile !== undefined;
  const [key, setKey] = useState(profile?.key ?? '');
  const [displayName, setDisplayName] = useState(profile?.display_name ?? '');
  const [description, setDescription] = useState(profile?.description ?? '');
  const [operations, setOperations] = useState<string[]>(profile?.operations ?? []);
  const [isDefault, setIsDefault] = useState(profile?.is_default ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disabling, setDisabling] = useState(false);

  const keyValid = /^[a-z0-9][a-z0-9-]*$/.test(key);
  const canSave = displayName.trim().length > 0 && (isEdit || keyValid);

  const toggleOperation = (operation: string) =>
    setOperations((current) =>
      current.includes(operation)
        ? current.filter((item) => item !== operation)
        : [...current, operation],
    );

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isEdit) {
        await adminApi.patch<AgentProfile>(`/v1/admin/agent-profiles/${profile.id}`, {
          display_name: displayName,
          description,
          operations,
          // Demoting a default is not a thing — promoting another variant is
          // how you move it — so only ever send the promotion.
          is_default: isDefault && !profile.is_default ? true : undefined,
        });
      } else {
        await adminApi.post<AgentProfile>('/v1/admin/agent-profiles', {
          role: node.role,
          key,
          display_name: displayName,
          description,
          operations,
        });
      }
      notify(isEdit ? t('profileSaved') : t('profileCreated'), 'success');
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
    notify(t('profileDisabled'), 'success');
    setDisabling(false);
    onSaved();
    onClose();
  };

  const usedBy = profile?.used_by_operations ?? [];

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={isEdit ? t('editProfile') : t('newProfile')}
      description={t('profileDialogDesc', { role: node.display_name })}
    >
      <div className="flex flex-col gap-4">
        {isEdit ? (
          <p className="text-xs text-muted">
            {t('profileKeyLocked')}{' '}
            <span className="font-mono">
              {node.role}/{profile.key}
            </span>
          </p>
        ) : (
          <TextInput
            label={t('profileKey')}
            hint={t('profileKeyHint')}
            value={key}
            error={key.length > 0 && !keyValid ? t('profileKeyInvalid') : undefined}
            onChange={(event) => setKey(event.target.value)}
          />
        )}

        <TextInput
          label={t('profileName')}
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
        />

        <TextArea
          label={t('profileDescription')}
          value={description}
          maxLength={2000}
          onChange={(event) => setDescription(event.target.value)}
        />

        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium text-text">{t('capabilities')}</legend>
          <p className="text-xs text-muted">{t('capabilitiesHint')}</p>
          <div className="flex flex-wrap gap-2">
            {OPERATIONS.map((operation) => {
              const labelKey = operationLabelKey(operation);
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
                  {labelKey ? tProviders(labelKey) : operation}
                </label>
              );
            })}
          </div>
        </fieldset>

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
            {usedBy.map((operation) => {
              const labelKey = operationLabelKey(operation);
              return (
                <Badge key={operation} tone="success">
                  {labelKey ? tProviders(labelKey) : operation}
                </Badge>
              );
            })}
          </div>
        ) : null}

        {error ? <ErrorNotice title={error} /> : null}

        <div className="flex items-center justify-between gap-2 border-t border-border pt-4">
          {isEdit && profile.enabled && !profile.is_default ? (
            <Button variant="ghost" onClick={() => setDisabling(true)}>
              {t('disableProfile')}
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
        title={t('disableProfile')}
        description={t('disableProfileDesc')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={disable}
      />
    </Dialog>
  );
}
