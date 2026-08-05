'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type { AgentNode, AgentSkill } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { formatDateTime } from '@/lib/format';

/**
 * Node topology + versioned prompt editor for the four/five built-in agent
 * pipeline stages.
 *
 * Distinct from `LlmProvidersPanel`: that maintains *which endpoints exist*,
 * this maintains *which prompt each node currently runs* and which of those
 * endpoints (by `scenario_tags`) could actually serve it. Publishing here
 * writes through `agent_skills.service.publish`, which is append-only and
 * activates the new row atomically — so "rollback" is just re-activating an
 * older row, never an edit-in-place.
 */
export function AgentSkillsPanel({ initial }: { initial: AgentNode[] }) {
  const t = useTranslations('adminAgents');
  const { role } = useAdminSession();
  const editable = atLeast(role, 'admin');

  const [nodes, setNodes] = useState(initial);
  const [editingRole, setEditingRole] = useState<string | null>(null);

  const reload = async () => {
    setNodes((await adminApi.get<{ items: AgentNode[] }>('/v1/admin/agent-nodes')).items);
  };

  const sorted = [...nodes].sort((a, b) => a.sort_order - b.sort_order);
  const editingNode = sorted.find((node) => node.role === editingRole) ?? null;

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
      <div>
        <h2 className="text-sm font-semibold">{t('sectionNodes')}</h2>
        <p className="mt-1 max-w-2xl text-xs text-muted">{t('sectionNodesDesc')}</p>
      </div>

      <ol className="mt-4 flex flex-wrap items-stretch gap-3">
        {sorted.map((node, index) => (
          <li key={node.id} className="flex items-stretch">
            <div className="flex w-56 flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface-soft p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] text-muted">{node.role}</span>
                <Badge tone={node.enabled ? 'success' : 'neutral'}>
                  {node.enabled ? t('enabled') : t('disabled')}
                </Badge>
              </div>
              <p className="text-sm font-medium text-text">{node.display_name}</p>
              <p className="text-xs text-muted">{node.description}</p>
              <div className="mt-auto flex flex-wrap items-center gap-1 pt-2">
                {(node.candidate_endpoint_ids ?? []).length === 0 ? (
                  <Badge tone="amber">{t('noCandidateEndpoints')}</Badge>
                ) : (
                  (node.candidate_endpoint_ids ?? []).map((id) => (
                    <Badge key={id} tone="neutral">
                      {id}
                    </Badge>
                  ))
                )}
              </div>
              <Button size="sm" variant="secondary" onClick={() => setEditingRole(node.role)}>
                {t('editSkill')}
              </Button>
            </div>
            {index < sorted.length - 1 ? (
              <span aria-hidden="true" className="mt-8 h-0.5 w-6 shrink-0 self-center bg-border" />
            ) : null}
          </li>
        ))}
      </ol>

      {editingNode ? (
        <AgentSkillEditorDialog
          node={editingNode}
          editable={editable}
          onClose={() => setEditingRole(null)}
          onPublished={() => void reload()}
        />
      ) : null}
    </section>
  );
}

function AgentSkillEditorDialog({
  node,
  editable,
  onClose,
  onPublished,
}: {
  node: AgentNode;
  editable: boolean;
  onClose: () => void;
  onPublished: () => void;
}) {
  const t = useTranslations('adminAgents');
  const tAdmin = useTranslations('admin');
  const { notify } = useToast();
  const locale = useLocale() as Locale;

  const [versions, setVersions] = useState<AgentSkill[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [promptTemplate, setPromptTemplate] = useState('');
  const [toolGrants, setToolGrants] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activating, setActivating] = useState<AgentSkill | null>(null);

  const load = () =>
    adminApi
      .get<{ items: AgentSkill[] }>('/v1/admin/agent-skills', { query: { node_role: node.role } })
      .then((page) => {
        setVersions(page.items);
        const active = page.items.find((v) => v.is_active);
        setPromptTemplate(active?.prompt_template ?? '');
        setToolGrants((active?.tool_grants ?? []).join(', '));
        setLoadFailed(false);
      })
      .catch(() => setLoadFailed(true));

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.role]);

  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      await adminApi.post<AgentSkill>('/v1/admin/agent-skills', {
        node_role: node.role,
        prompt_template: promptTemplate,
        tool_grants: toolGrants
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
        reason,
        confirm: true,
      });
      notify(t('skillPublished'), 'success');
      setReason('');
      await load();
      onPublished();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const activate = async (activateReason: string) => {
    if (!activating) return;
    await adminApi.post<AgentSkill>(`/v1/admin/agent-skills/${activating.id}/activate`, {
      reason: activateReason,
      confirm: true,
    });
    notify(t('skillActivated'), 'success');
    setActivating(null);
    await load();
    onPublished();
  };

  return (
    <Dialog
      open
      onClose={onClose}
      size="xl"
      title={`${node.display_name} · ${node.role}`}
      description={t('editSkillDesc')}
    >
      <div className="flex flex-col gap-6">
        <section>
          <h3 className="text-sm font-semibold">{t('versionHistory')}</h3>
          {loadFailed ? (
            <div className="mt-2">
              <ErrorNotice title={tAdmin('loadFailed')} />
            </div>
          ) : versions === null ? (
            <p className="mt-2 text-xs text-muted">{t('loading')}</p>
          ) : versions.length === 0 ? (
            <p className="mt-2 text-xs text-muted">{t('noVersionsYet')}</p>
          ) : (
            <ul className="mt-2 flex flex-col gap-2">
              {versions.map((version) => (
                <li
                  key={version.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-border px-3 py-2 text-xs"
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono">v{version.version}</span>
                    {version.is_active ? <Badge tone="success">{t('active')}</Badge> : null}
                    <span className="text-muted">{formatDateTime(version.created_at, locale)}</span>
                    {version.reason ? <span className="text-muted">· {version.reason}</span> : null}
                  </span>
                  {editable && !version.is_active ? (
                    <Button size="sm" variant="ghost" onClick={() => setActivating(version)}>
                      {t('activateVersion')}
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        {editable ? (
          <section className="flex flex-col gap-4 border-t border-border pt-4">
            <h3 className="text-sm font-semibold">{t('publishNewVersion')}</h3>
            <TextArea
              label={t('promptTemplate')}
              value={promptTemplate}
              onChange={(event) => setPromptTemplate(event.target.value)}
              className="min-h-56 font-mono text-xs"
            />
            <TextInput
              label={t('toolGrants')}
              hint={t('toolGrantsHint')}
              value={toolGrants}
              onChange={(event) => setToolGrants(event.target.value)}
            />
            <TextArea
              label={tAdmin('dangerReason')}
              hint={tAdmin('dangerReasonHint')}
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
            />
            {error ? <ErrorNotice title={error} /> : null}
            <div className="flex justify-end">
              <Button
                loading={busy}
                disabled={promptTemplate.trim().length === 0 || reason.trim().length < 4}
                onClick={() => void publish()}
              >
                {t('publish')}
              </Button>
            </div>
          </section>
        ) : null}
      </div>

      <DangerConfirm
        open={activating !== null}
        onClose={() => setActivating(null)}
        title={t('activateVersion')}
        description={t('activateVersionDesc')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={activate}
      />
    </Dialog>
  );
}
