'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { AgentProfileDialog } from '@/components/admin/agents/agent-profile-dialog';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { operationLabelKey } from '@/lib/admin/operations';
import { atLeast } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type {
  AgentNode,
  AgentProfile,
  AgentSkill,
  Page,
  SkillTemplate,
} from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';
import { formatDateTime } from '@/lib/format';

/**
 * The agent roster and each agent's versioned prompts.
 *
 * An **agent** is the unit here; its **role** (`safety`, `planner`, ...) says
 * which pipeline stage it can run, and is only a grouping in this list. More
 * than one agent may share a role — `/admin/routing` is where a workflow node
 * picks which of them it runs, so `text_to_video` can bind a stricter safety
 * agent than `text_to_image`. A **skill** is one append-only prompt version
 * for an `(agent, slot)` pair.
 *
 * Distinct from `LlmProvidersPanel`: that maintains *which endpoints exist*,
 * this maintains *what each agent says*. Publishing here writes through
 * `agent_skills.service.publish`, which is append-only and activates the new
 * row atomically, so "rollback" is re-publishing an older row's content,
 * never an edit in place.
 */
export function AgentSkillsPanel({ initial }: { initial: AgentNode[] }) {
  const t = useTranslations('adminAgents');
  const { role } = useAdminSession();
  const editable = atLeast(role, 'admin');

  const [nodes, setNodes] = useState(initial);
  const [profiles, setProfiles] = useState<AgentProfile[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editing, setEditing] = useState<{ node: AgentNode; profile: AgentProfile } | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingMeta, setEditingMeta] = useState<AgentProfile | null>(null);

  const reload = useCallback(
    () =>
      Promise.all([
        adminApi.get<{ items: AgentNode[] }>('/v1/admin/agent-nodes'),
        adminApi.get<{ items: AgentProfile[] }>('/v1/admin/agent-profiles'),
      ])
        .then(([nodePage, profilePage]) => {
          setNodes(nodePage.items);
          setProfiles(profilePage.items);
          setLoadFailed(false);
        })
        .catch(() => setLoadFailed(true)),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  const sorted = [...nodes].sort((a, b) => a.sort_order - b.sort_order);
  // Every role draws from the same enabled `kind="general"` pool, so an empty
  // one is a page-level problem rather than something to repeat per role.
  const noEndpoints =
    sorted.length > 0 && sorted.every((node) => !node.candidate_endpoint_ids?.length);

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{t('sectionAgents')}</h2>
          <p className="mt-1 max-w-3xl text-xs text-muted">{t('sectionAgentsDesc')}</p>
        </div>
        {editable ? (
          <Button size="sm" onClick={() => setCreating(true)}>
            {t('newAgent')}
          </Button>
        ) : null}
      </div>

      {loadFailed ? (
        <div className="mt-4">
          <ErrorNotice title={t('loadProfilesFailed')} />
        </div>
      ) : null}

      {noEndpoints ? (
        <p className="mt-4 rounded-[var(--radius-sm)] border border-amber/40 bg-amber/10 px-3 py-2 text-xs text-amber">
          {t('noCandidateEndpoints')}
        </p>
      ) : null}

      <ol className="mt-4 flex flex-col gap-5">
        {sorted.map((node) => (
          <li key={node.id}>
            <RoleGroup
              node={node}
              profiles={profiles?.filter((profile) => profile.role === node.role) ?? null}
              editable={editable}
              onEditPrompt={(profile) => setEditing({ node, profile })}
              onEditMeta={setEditingMeta}
            />
          </li>
        ))}
      </ol>

      {editing ? (
        <AgentSkillEditorDialog
          node={editing.node}
          profile={editing.profile}
          editable={editable}
          onClose={() => setEditing(null)}
          onPublished={() => void reload()}
        />
      ) : null}

      {creating ? (
        <AgentProfileDialog onClose={() => setCreating(false)} onSaved={() => void reload()} />
      ) : null}

      {editingMeta ? (
        <AgentProfileDialog
          profile={editingMeta}
          onClose={() => setEditingMeta(null)}
          onSaved={() => void reload()}
        />
      ) : null}
    </section>
  );
}

/**
 * One role's heading and the agents filed under it.
 *
 * The heading is a label, not a thing to act on: a role is a slot in the
 * pipeline that ships in `app/workflows/registry.py`, so there is nothing here
 * to create, edit or disable. Every action belongs to an agent.
 */
function RoleGroup({
  node,
  profiles,
  editable,
  onEditPrompt,
  onEditMeta,
}: {
  node: AgentNode;
  profiles: AgentProfile[] | null;
  editable: boolean;
  onEditPrompt: (profile: AgentProfile) => void;
  onEditMeta: (profile: AgentProfile) => void;
}) {
  const t = useTranslations('adminAgents');

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-2 border-b border-border pb-2">
        <h3 className="text-sm font-medium text-text">{node.display_name}</h3>
        <span className="font-mono text-[11px] text-muted">{node.role}</span>
        <Badge tone={node.category === 'creative' ? 'primary' : 'neutral'}>
          {node.category === 'creative' ? t('categoryCreative') : t('categoryJudgment')}
        </Badge>
        <span className="min-w-0 flex-1 truncate text-xs text-muted">{node.description}</span>
      </div>

      <div className="mt-3">
        {profiles === null ? (
          <p className="text-xs text-muted">{t('loading')}</p>
        ) : profiles.length === 0 ? (
          <p className="text-xs text-muted">{t('noAgentsYet')}</p>
        ) : (
          <ul className="flex flex-wrap gap-3">
            {profiles.map((profile) => (
              <li key={profile.id} className="w-72">
                <AgentCard
                  profile={profile}
                  editable={editable}
                  onEditPrompt={() => onEditPrompt(profile)}
                  onEditMeta={() => onEditMeta(profile)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function AgentCard({
  profile,
  editable,
  onEditPrompt,
  onEditMeta,
}: {
  profile: AgentProfile;
  editable: boolean;
  onEditPrompt: () => void;
  onEditMeta: () => void;
}) {
  const t = useTranslations('adminAgents');
  const tProviders = useTranslations('adminProviders');
  const label = (operation: string) => {
    const key = operationLabelKey(operation);
    return key ? tProviders(key) : operation;
  };

  const declared = profile.operations ?? [];
  const usedBy = profile.used_by_operations ?? [];
  // The one thing an operator can get wrong that nothing else catches: an
  // agent written for video wired into an image workflow. Publishing warns
  // about it too, but this is where they would notice it after the fact.
  const mismatched = declared.length > 0 ? usedBy.filter((op) => !declared.includes(op)) : [];

  return (
    <div className="flex h-full flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-muted">{profile.key}</span>
        <span className="flex items-center gap-1">
          {profile.is_default ? <Badge tone="primary">{t('defaultAgent')}</Badge> : null}
          {profile.enabled ? null : <Badge tone="neutral">{t('disabled')}</Badge>}
        </span>
      </div>
      <p className="text-sm font-medium text-text">{profile.display_name}</p>
      {profile.description ? <p className="text-xs text-muted">{profile.description}</p> : null}

      <div className="flex flex-wrap items-center gap-1">
        <span className="text-[11px] text-muted">{t('capabilities')}</span>
        {declared.length === 0 ? (
          <Badge tone="neutral">{t('capabilityAny')}</Badge>
        ) : (
          declared.map((operation) => (
            <Badge key={operation} tone="neutral">
              {label(operation)}
            </Badge>
          ))
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1">
        <span className="text-[11px] text-muted">{t('usedBy')}</span>
        {usedBy.length === 0 ? (
          <Badge tone="neutral">{profile.is_default ? t('usedByFallback') : t('usedByNone')}</Badge>
        ) : (
          usedBy.map((operation) => (
            <Badge key={operation} tone={mismatched.includes(operation) ? 'amber' : 'success'}>
              {label(operation)}
            </Badge>
          ))
        )}
      </div>

      {mismatched.length > 0 ? (
        <p className="text-[11px] text-amber">
          {t('capabilityMismatch', { operations: mismatched.map(label).join('、') })}
        </p>
      ) : null}

      <div className="mt-auto flex gap-2 pt-2">
        <Button size="sm" variant="secondary" onClick={onEditPrompt}>
          {t('editSkill')}
        </Button>
        {editable ? (
          <Button size="sm" variant="ghost" onClick={onEditMeta}>
            {t('editAgent')}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function AgentSkillEditorDialog({
  node,
  profile,
  editable,
  onClose,
  onPublished,
}: {
  node: AgentNode;
  profile: AgentProfile;
  editable: boolean;
  onClose: () => void;
  onPublished: () => void;
}) {
  const t = useTranslations('adminAgents');
  const tAdmin = useTranslations('admin');
  const { notify } = useToast();
  const locale = useLocale() as Locale;

  const slots = node.prompt_slots ?? [];
  const [slot, setSlot] = useState(slots[0]?.key ?? 'default');
  const [versions, setVersions] = useState<AgentSkill[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [promptTemplate, setPromptTemplate] = useState('');
  const [toolGrants, setToolGrants] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activating, setActivating] = useState<AgentSkill | null>(null);
  const [templates, setTemplates] = useState<SkillTemplate[]>([]);
  const [templateKey, setTemplateKey] = useState('');

  useEffect(() => {
    if (!editable) return;
    void adminApi
      .get<Page<SkillTemplate>>('/v1/admin/agent-skill-templates', {
        query: { category: profile.category, role: profile.role },
      })
      .then((page) => setTemplates(page.items))
      .catch(() => setTemplates([]));
  }, [editable, profile.category, profile.role]);

  // A role's templates are written for one slot — offering `copy`'s prompt
  // polisher while editing its tag suggester would fill in the wrong prompt.
  // Role-agnostic templates suit any slot.
  const slotTemplates = templates.filter((template) => !template.role || template.slot === slot);

  /** Fills the form only. Publishing stays a separate confirmed action:
   * the published text is what decides whether content gets rejected. */
  const applyTemplate = (key: string) => {
    setTemplateKey(key);
    const template = templates.find((item) => item.key === key);
    if (!template) return;
    setPromptTemplate(template.prompt_template);
    setToolGrants((template.tool_grants ?? []).join(', '));
  };

  const load = useCallback(
    () =>
      adminApi
        .get<{ items: AgentSkill[] }>('/v1/admin/agent-skills', {
          query: { profile_id: profile.id, slot },
        })
        .then((page) => {
          setVersions(page.items);
          const active = page.items.find((version) => version.is_active);
          setPromptTemplate(active?.prompt_template ?? '');
          setToolGrants((active?.tool_grants ?? []).join(', '));
          setLoadFailed(false);
        })
        .catch(() => setLoadFailed(true)),
    [profile.id, slot],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      await adminApi.post<AgentSkill>('/v1/admin/agent-skills', {
        profile_id: profile.id,
        slot,
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
      title={`${profile.display_name} · ${node.display_name}`}
      description={t('editSkillDesc')}
    >
      <div className="flex flex-col gap-6">
        {slots.length > 1 ? (
          <section>
            <h3 className="text-sm font-semibold">{t('promptSlot')}</h3>
            <p className="mt-1 text-xs text-muted">{t('promptSlotHint')}</p>
            <div role="tablist" className="mt-2 flex flex-wrap gap-2">
              {slots.map((candidate) => (
                <button
                  key={candidate.key}
                  type="button"
                  role="tab"
                  aria-selected={candidate.key === slot}
                  onClick={() => {
                    // Clear here rather than in `load`, so switching slots
                    // shows the loading state without a setState inside the
                    // effect that reloads.
                    setVersions(null);
                    setSlot(candidate.key);
                  }}
                  className={
                    candidate.key === slot
                      ? 'rounded-[var(--radius-sm)] border border-accent bg-accent-soft px-3 py-1.5 text-xs font-medium text-text'
                      : 'rounded-[var(--radius-sm)] border border-border px-3 py-1.5 text-xs text-muted hover:text-text'
                  }
                >
                  {candidate.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">
              {slots.find((candidate) => candidate.key === slot)?.description}
            </p>
          </section>
        ) : null}

        <section>
          <h3 className="text-sm font-semibold">{t('versionHistory')}</h3>
          {loadFailed ? (
            <div className="mt-2">
              <ErrorNotice title={tAdmin('loadFailed')} />
            </div>
          ) : versions === null ? (
            <p className="mt-2 text-xs text-muted">{t('loading')}</p>
          ) : versions.length === 0 ? (
            <p className="mt-2 text-xs text-muted">
              {profile.is_default ? t('noVersionsYet') : t('noVersionsYetInherited')}
            </p>
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
            {slotTemplates.length > 0 ? (
              <Select
                label={t('fillFromTemplate')}
                hint={t('fillFromTemplateHint')}
                value={templateKey}
                onChange={(event) => applyTemplate(event.target.value)}
                options={[
                  { value: '', label: t('fillFromTemplatePlaceholder') },
                  ...slotTemplates.map((template) => ({
                    value: template.key,
                    label: template.label,
                  })),
                ]}
              />
            ) : null}
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
