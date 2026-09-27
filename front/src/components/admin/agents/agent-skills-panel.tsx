'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { AgentDebugChatDialog } from '@/components/admin/agents/agent-debug-chat-dialog';
import { AgentProfileDialog } from '@/components/admin/agents/agent-profile-dialog';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button, IconButton } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { MultiSelect, Select, Switch, TextArea } from '@/components/ui/field';
import { IconGear, IconMessage, IconPencil, IconTrash } from '@/components/ui/icons';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import {
  assetKindLabelKey,
  copyEditorSlot,
  recommendedCopyTemplateKey,
  templatesForCopyAgent,
} from '@/lib/admin/copy-routing';
import { operationLabelKey } from '@/lib/admin/operations';
import { atLeast } from '@/lib/admin/rbac';
import { toolGrantLabelKey } from '@/lib/admin/tool-grants';
import { adminApi } from '@/lib/api/admin-client';
import type {
  AgentCategory,
  AgentNode,
  AgentProfile,
  AgentSkill,
  AgentSkillTool,
  Page,
  RolePreset,
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

// Mirrors the actual job pipeline (`app/workflows/defaults.py`): safety
// gates first, then planning, then routing picks a generation lane, then
// quality checks the result. `copy` never appears in that DAG — it backs a
// separate "AI polish" button the user triggers by hand — so it sorts after
// the roles a generation job actually runs. A role missing from this table
// keeps its existing relative order at the end.
const PIPELINE_ROLE_ORDER: Record<string, number> = {
  safety: 0,
  planner: 1,
  intent_router: 2,
  quality: 3,
  copy: 4,
};

function displayRank(role: string, sortOrder: number): number {
  return PIPELINE_ROLE_ORDER[role] ?? 100 + sortOrder;
}

function categoryLabel(category: AgentCategory, t: (key: string) => string): string {
  if (category === 'assist') return t('categoryAssist');
  return t('categoryJudgment');
}

/** One role's group header, merging its `AgentNode` (once at least one agent
 * exists) with its catalogue `RolePreset` (always exists). A role has no
 * node row until its first agent is created (see
 * `agent_skills.service.create_profile`'s `ensure_node_for_role`), so without
 * the preset half a role nobody has used yet would have no arrow to create
 * one from. */
interface RoleSummary {
  role: string;
  displayName: string;
  category: AgentCategory;
  description: string;
  sortOrder: number;
  node: AgentNode | null;
}

export function AgentSkillsPanel({ initial }: { initial: AgentNode[] }) {
  const t = useTranslations('adminAgents');
  const { role } = useAdminSession();
  const editable = atLeast(role, 'admin');

  const [nodes, setNodes] = useState(initial);
  const [presets, setPresets] = useState<RolePreset[]>([]);
  const [profiles, setProfiles] = useState<AgentProfile[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editing, setEditing] = useState<{ node: AgentNode; profile: AgentProfile } | null>(null);
  const [creatingForRole, setCreatingForRole] = useState<string | null>(null);
  const [editingMeta, setEditingMeta] = useState<AgentProfile | null>(null);
  const [debugging, setDebugging] = useState<{ node: AgentNode; profile: AgentProfile } | null>(
    null,
  );

  const reload = useCallback(
    () =>
      Promise.all([
        adminApi.get<{ items: AgentNode[] }>('/v1/admin/agent-nodes'),
        adminApi.get<{ items: AgentProfile[] }>('/v1/admin/agent-profiles'),
        adminApi.get<Page<RolePreset>>('/v1/admin/agent-node-presets'),
      ])
        .then(([nodePage, profilePage, presetPage]) => {
          setNodes(nodePage.items);
          setProfiles(profilePage.items);
          setPresets(presetPage.items);
          setLoadFailed(false);
        })
        .catch(() => setLoadFailed(true)),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  const nodeByRole = new Map(nodes.map((node) => [node.role, node]));
  const allRoles = new Set([...nodeByRole.keys(), ...presets.map((preset) => preset.role)]);
  const summaries: RoleSummary[] = [...allRoles].map((roleKey, index) => {
    const node = nodeByRole.get(roleKey) ?? null;
    const preset = presets.find((item) => item.role === roleKey);
    return {
      role: roleKey,
      displayName: node?.display_name ?? preset?.display_name ?? roleKey,
      category: node?.category ?? preset?.category ?? 'judgment',
      description: node?.description ?? preset?.description ?? '',
      sortOrder: node?.sort_order ?? 100 + index,
      node,
    };
  });
  const sorted = summaries.sort(
    (a, b) => displayRank(a.role, a.sortOrder) - displayRank(b.role, b.sortOrder),
  );
  // Every role draws from the same enabled `kind="general"` pool, so an empty
  // one is a page-level problem rather than something to repeat per role.
  const noEndpoints =
    nodes.length > 0 && nodes.every((node) => !node.candidate_endpoint_ids?.length);

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
      {loadFailed ? <ErrorNotice title={t('loadProfilesFailed')} /> : null}

      {noEndpoints ? (
        <p className="mt-4 rounded-[var(--radius-sm)] border border-amber/40 bg-amber/10 px-3 py-2 text-xs text-amber">
          {t('noCandidateEndpoints')}
        </p>
      ) : null}

      <ol className="mt-4 flex flex-col gap-5">
        {sorted.map((summary) => (
          <li key={summary.role}>
            <RoleGroup
              summary={summary}
              profiles={profiles?.filter((profile) => profile.role === summary.role) ?? null}
              editable={editable}
              onEditPrompt={(profile) =>
                summary.node ? setEditing({ node: summary.node, profile }) : undefined
              }
              onEditMeta={setEditingMeta}
              onDebug={(profile) =>
                summary.node ? setDebugging({ node: summary.node, profile }) : undefined
              }
              onCreate={() => setCreatingForRole(summary.role)}
              onChanged={() => void reload()}
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

      {creatingForRole ? (
        <AgentProfileDialog
          initialRole={creatingForRole}
          onClose={() => setCreatingForRole(null)}
          onSaved={() => void reload()}
        />
      ) : null}

      {editingMeta ? (
        <AgentProfileDialog
          profile={editingMeta}
          onClose={() => setEditingMeta(null)}
          onSaved={() => void reload()}
        />
      ) : null}

      {debugging ? (
        <AgentDebugChatDialog
          node={debugging.node}
          profile={debugging.profile}
          onClose={() => setDebugging(null)}
        />
      ) : null}
    </section>
  );
}

/**
 * One role's heading and the agents filed under it.
 *
 * The heading itself is still a label, not a thing to act on: a role is a
 * slot in the pipeline that ships in `app/workflows/registry.py`. The one
 * exception is the arrow button, which does not edit the role — it opens
 * `AgentProfileDialog` to create a new agent under it.
 */
function RoleGroup({
  summary,
  profiles,
  editable,
  onEditPrompt,
  onEditMeta,
  onDebug,
  onCreate,
  onChanged,
}: {
  summary: RoleSummary;
  profiles: AgentProfile[] | null;
  editable: boolean;
  onEditPrompt: (profile: AgentProfile) => void;
  onEditMeta: (profile: AgentProfile) => void;
  onDebug: (profile: AgentProfile) => void;
  onCreate: () => void;
  onChanged: () => void;
}) {
  const t = useTranslations('adminAgents');

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-2 border-b border-border pb-2">
        <h3 className="text-sm font-medium text-text">{summary.displayName}</h3>
        <span className="font-mono text-[11px] text-muted">{summary.role}</span>
        <Badge tone="neutral">{categoryLabel(summary.category, t)}</Badge>
        <span className="min-w-0 flex-1 truncate text-xs text-muted">{summary.description}</span>
        {editable ? (
          <Button
            size="sm"
            variant="ghost"
            aria-label={t('newAgentForRole', { role: summary.displayName })}
            title={t('newAgentForRole', { role: summary.displayName })}
            onClick={onCreate}
          >
            {t('newAgentArrow')}
          </Button>
        ) : null}
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
                  onDebug={() => onDebug(profile)}
                  onChanged={onChanged}
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
  onDebug,
  onChanged,
}: {
  profile: AgentProfile;
  editable: boolean;
  onEditPrompt: () => void;
  onEditMeta: () => void;
  onDebug: () => void;
  onChanged: () => void;
}) {
  const t = useTranslations('adminAgents');
  const tAdmin = useTranslations('admin');
  const tProviders = useTranslations('adminProviders');
  const { notify } = useToast();
  const label = (operation: string) => {
    const key = operationLabelKey(operation);
    return key ? tProviders(key) : operation;
  };

  const [toggling, setToggling] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const declared = profile.operations ?? [];
  const usedBy = profile.used_by_operations ?? [];
  // The one thing an operator can get wrong that nothing else catches: an
  // agent written for video wired into an image workflow. Publishing warns
  // about it too, but this is where they would notice it after the fact.
  const mismatched = declared.length > 0 ? usedBy.filter((op) => !declared.includes(op)) : [];

  const enable = async () => {
    setToggling(true);
    setActionError(null);
    try {
      await adminApi.patch<AgentProfile>(`/v1/admin/agent-profiles/${profile.id}`, {
        enabled: true,
      });
      notify(t('agentEnabled'), 'success');
      onChanged();
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setToggling(false);
    }
  };

  const disable = async (reason: string) => {
    await adminApi.post<AgentProfile>(`/v1/admin/agent-profiles/${profile.id}/disable`, {
      reason,
      confirm: true,
    });
    notify(t('agentDisabled'), 'success');
    onChanged();
  };

  const remove = async (reason: string) => {
    await adminApi.post(`/v1/admin/agent-profiles/${profile.id}/delete`, {
      reason,
      confirm: true,
    });
    notify(t('agentDeleted'), 'success');
    onChanged();
  };

  return (
    <div className="flex h-full flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-muted">{profile.key}</span>
        <span className="flex flex-wrap items-center gap-1">
          {profile.is_default ? <Badge tone="primary">{t('defaultAgent')}</Badge> : null}
          {profile.default_for_asset_kind ? (
            <Badge tone="primary">{t(assetKindLabelKey(profile.default_for_asset_kind))}</Badge>
          ) : null}
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
          <Badge tone="neutral">
            {profile.is_default
              ? t('usedByFallback')
              : profile.default_for_asset_kind
                ? t(assetKindLabelKey(profile.default_for_asset_kind))
                : t('usedByNone')}
          </Badge>
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

      {actionError ? <ErrorNotice title={actionError} /> : null}

      <div className="mt-auto flex items-center gap-1.5 border-t border-border pt-2">
        <IconButton label={t('editSkill')} variant="secondary" onClick={onEditPrompt}>
          <IconPencil className="size-4" />
        </IconButton>
        {editable ? (
          <IconButton label={t('editAgent')} onClick={onEditMeta}>
            <IconGear className="size-4" />
          </IconButton>
        ) : null}
        {editable ? (
          <IconButton label={t('debugChat')} onClick={onDebug}>
            <IconMessage className="size-4" />
          </IconButton>
        ) : null}
        {editable ? (
          <Switch
            compact
            className="ml-auto"
            label={profile.enabled ? t('enabled') : t('disabled')}
            checked={profile.enabled}
            disabled={profile.is_default || toggling}
            onChange={(next) => (next ? void enable() : setDisabling(true))}
          />
        ) : null}
        {editable && !profile.is_default ? (
          <IconButton label={t('deleteAgent')} variant="danger" onClick={() => setDeleting(true)}>
            <IconTrash className="size-4" />
          </IconButton>
        ) : null}
      </div>

      <DangerConfirm
        open={disabling}
        onClose={() => setDisabling(false)}
        title={t('disableAgent')}
        description={t('disableAgentDesc')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={disable}
      />

      <DangerConfirm
        open={deleting}
        onClose={() => setDeleting(false)}
        title={t('deleteAgent')}
        description={t('deleteAgentDesc')}
        reasonLabel={tAdmin('dangerReason')}
        confirmWord={profile.key}
        onConfirm={remove}
      />
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
  const isCopyRole = profile.role === 'copy';
  const inferredSlot = isCopyRole ? copyEditorSlot(profile) : (slots[0]?.key ?? 'default');
  const [slot, setSlot] = useState(inferredSlot);
  const [versions, setVersions] = useState<AgentSkill[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [promptTemplate, setPromptTemplate] = useState('');
  const [toolGrants, setToolGrants] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activating, setActivating] = useState<AgentSkill | null>(null);
  const [rollbackBusy, setRollbackBusy] = useState(false);
  const [rollbackError, setRollbackError] = useState<string | null>(null);
  const [templates, setTemplates] = useState<SkillTemplate[]>([]);
  // Stay on "no template" until the operator actually picks one. Pre-selecting
  // the recommended key without applying it makes the dropdown lie: it shows
  // 「文案润色 · 角色」while the textarea still holds the published (often
  // generic) prompt, and clicking the already-selected option never fires
  // `onChange`.
  const [templateKey, setTemplateKey] = useState('');
  // Once a template has filled the form, later skill reloads must not
  // clobber it — that is how a character agent ended up showing the generic
  // enhance draft after 「从模板填充」.
  const [templateApplied, setTemplateApplied] = useState(false);
  const [availableTools, setAvailableTools] = useState<string[]>([]);
  const [debuggingDraft, setDebuggingDraft] = useState(false);

  useEffect(() => {
    if (!editable) return;
    void adminApi
      .get<Page<SkillTemplate>>('/v1/admin/agent-skill-templates', {
        query: { category: profile.category, role: profile.role },
      })
      .then((page) => setTemplates(page.items))
      .catch(() => setTemplates([]));
  }, [editable, profile.category, profile.role]);

  useEffect(() => {
    if (!editable) return;
    void adminApi
      .get<Page<AgentSkillTool>>('/v1/admin/agent-skill-tools', { query: { role: node.role } })
      .then((page) => setAvailableTools(page.items.map((item) => item.name)))
      .catch(() => setAvailableTools([]));
  }, [editable, node.role]);

  const editorSlot = isCopyRole ? inferredSlot : slot;
  // A role's templates are written for one slot — offering `copy`'s prompt
  // polisher while editing its tag suggester would fill in the wrong prompt.
  // Role-agnostic templates suit any slot. Copy additionally narrows by
  // the agent's request-routing bucket so a character agent is only offered
  // the character starting prompt, not the generic enhance draft or
  // scene/cover specialised drafts.
  const slotTemplates = useMemo(
    () =>
      isCopyRole
        ? templatesForCopyAgent(templates, editorSlot, profile.default_for_asset_kind)
        : templates.filter((template) => !template.role || template.slot === editorSlot),
    [isCopyRole, templates, editorSlot, profile.default_for_asset_kind],
  );
  const recommendedTemplateKey = isCopyRole
    ? recommendedCopyTemplateKey(profile.default_for_asset_kind)
    : '';
  const selectedTemplate = slotTemplates.find((template) => template.key === templateKey);

  const toolLabel = (tool: string) => {
    const key = toolGrantLabelKey(tool);
    return key ? t(key) : tool;
  };

  /** Fills the form only. Publishing stays a separate confirmed action:
   * the published text is what decides whether content gets rejected. */
  const applyTemplate = (key: string) => {
    setTemplateKey(key);
    if (!key) return;
    const template = slotTemplates.find((item) => item.key === key);
    if (!template?.prompt_template) return;
    setTemplateApplied(true);
    setPromptTemplate(template.prompt_template);
    setToolGrants(template.tool_grants ?? []);
  };

  const load = useCallback(
    () =>
      adminApi
        .get<{ items: AgentSkill[] }>('/v1/admin/agent-skills', {
          query: { profile_id: profile.id, slot: editorSlot },
        })
        .then((page) => {
          setVersions(page.items);
          setLoadFailed(false);
        })
        .catch(() => setLoadFailed(true)),
    [profile.id, editorSlot],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Both form fills below are adjusted during render rather than set from an
  // effect: every fetch that lands (initial, slot switch, publish, rollback)
  // yields a new `versions` array, which reseeds the form from the active
  // version unless a template already filled it.
  const activeVersion = versions?.find((version) => version.is_active) ?? null;
  const [seededVersions, setSeededVersions] = useState<AgentSkill[] | null>(null);
  if (versions !== seededVersions) {
    setSeededVersions(versions);
    if (versions && !templateApplied) {
      setPromptTemplate(activeVersion?.prompt_template ?? '');
      setToolGrants(activeVersion?.tool_grants ?? []);
    }
  }

  // Nothing published yet: start from the recommended (or first) template
  // for this slot as soon as both the versions and the templates are in.
  const fallbackKey =
    recommendedTemplateKey &&
    slotTemplates.some((template) => template.key === recommendedTemplateKey)
      ? recommendedTemplateKey
      : (slotTemplates[0]?.key ?? '');
  const fallbackTemplate = slotTemplates.find((item) => item.key === fallbackKey);
  if (
    !templateApplied &&
    versions !== null &&
    !(activeVersion?.prompt_template ?? '').trim() &&
    fallbackTemplate?.prompt_template
  ) {
    setTemplateApplied(true);
    setTemplateKey(fallbackKey);
    setPromptTemplate(fallbackTemplate.prompt_template);
    setToolGrants(fallbackTemplate.tool_grants ?? []);
  }

  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      const active = versions?.find((version) => version.is_active) ?? null;
      await adminApi.post<AgentSkill>('/v1/admin/agent-skills', {
        profile_id: profile.id,
        slot: editorSlot,
        prompt_template: promptTemplate,
        tool_grants: toolGrants,
        reason: summarizeSkillChange(active, {
          promptTemplate,
          toolGrants,
          templateLabel: templates.find((item) => item.key === templateKey)?.label,
        }),
        confirm: true,
      });
      notify(t('skillPublished'), 'success');
      await load();
      onPublished();
      // Publishing is the end of this dialog's job — leave the operator back
      // on the roster instead of sitting on a form that just succeeded.
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const activate = async () => {
    if (!activating) return;
    setRollbackBusy(true);
    setRollbackError(null);
    try {
      await adminApi.post<AgentSkill>(`/v1/admin/agent-skills/${activating.id}/activate`, {
        reason: `回滚到版本 ${activating.version}`,
        confirm: true,
      });
      notify(t('skillActivated'), 'success');
      setActivating(null);
      await load();
      onPublished();
    } catch (caught) {
      setRollbackError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setRollbackBusy(false);
    }
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
        {slots.length > 1 && !isCopyRole ? (
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

        {editable ? (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
            <section className="flex flex-col gap-4">
              <h3 className="text-sm font-semibold">{t('publishNewVersion')}</h3>
              {slotTemplates.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                  <Select
                    label={t('fillFromTemplate')}
                    hint={t('fillFromTemplateHint')}
                    value={templateKey}
                    onChange={(event) => applyTemplate(event.target.value)}
                    options={[
                      { value: '', label: t('fillFromTemplatePlaceholder') },
                      ...slotTemplates.map((template) => ({
                        value: template.key,
                        label:
                          template.key === recommendedTemplateKey
                            ? t('fillFromTemplateRecommended', { label: template.label })
                            : template.label,
                      })),
                    ]}
                  />
                  {selectedTemplate?.description ? (
                    <p className="text-xs text-muted">{selectedTemplate.description}</p>
                  ) : null}
                </div>
              ) : null}
              <TextArea
                label={t('promptTemplate')}
                value={promptTemplate}
                onChange={(event) => setPromptTemplate(event.target.value)}
                className="min-h-56 font-mono text-xs"
              />
              <MultiSelect
                label={t('toolGrants')}
                hint={t('toolGrantsHint')}
                value={toolGrants}
                onChange={setToolGrants}
                placeholder={t('toolGrantsPlaceholder')}
                emptyHint={t('toolGrantsEmpty')}
                options={availableTools.map((tool) => ({ value: tool, label: toolLabel(tool) }))}
              />
              {error ? <ErrorNotice title={error} /> : null}
              <div className="flex justify-end gap-2">
                <Button
                  variant="ghost"
                  disabled={promptTemplate.trim().length === 0}
                  onClick={() => setDebuggingDraft(true)}
                >
                  {t('debugChatDraft')}
                </Button>
                <Button
                  loading={busy}
                  disabled={promptTemplate.trim().length === 0}
                  onClick={() => void publish()}
                >
                  {t('publish')}
                </Button>
              </div>
            </section>

            <VersionHistorySection
              loadFailed={loadFailed}
              versions={versions}
              profile={profile}
              editable={editable}
              locale={locale}
              onActivate={setActivating}
            />
          </div>
        ) : (
          <VersionHistorySection
            loadFailed={loadFailed}
            versions={versions}
            profile={profile}
            editable={editable}
            locale={locale}
            onActivate={setActivating}
          />
        )}
      </div>

      {activating ? (
        <Dialog
          open
          onClose={() => setActivating(null)}
          title={t('activateVersion')}
          description={t('activateVersionDesc')}
          footer={
            <>
              <Button variant="ghost" onClick={() => setActivating(null)}>
                {tAdmin('reset')}
              </Button>
              <Button variant="danger" loading={rollbackBusy} onClick={() => void activate()}>
                {tAdmin('dangerProceed')}
              </Button>
            </>
          }
        >
          {rollbackError ? <ErrorNotice title={rollbackError} /> : null}
        </Dialog>
      ) : null}

      {debuggingDraft ? (
        <AgentDebugChatDialog
          node={node}
          profile={profile}
          draftPromptTemplate={promptTemplate}
          onClose={() => setDebuggingDraft(false)}
        />
      ) : null}
    </Dialog>
  );
}

function VersionHistorySection({
  loadFailed,
  versions,
  profile,
  editable,
  locale,
  onActivate,
}: {
  loadFailed: boolean;
  versions: AgentSkill[] | null;
  profile: AgentProfile;
  editable: boolean;
  locale: Locale;
  onActivate: (version: AgentSkill) => void;
}) {
  const t = useTranslations('adminAgents');
  const tAdmin = useTranslations('admin');

  return (
    <section className="flex flex-col gap-2">
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
        <ul className="mt-2 flex max-h-96 flex-col gap-2 overflow-y-auto">
          {versions.map((version) => (
            <li
              key={version.id}
              className="flex flex-col gap-1 rounded-[var(--radius-sm)] border border-border px-3 py-2 text-xs"
            >
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-mono">v{version.version}</span>
                {version.is_active ? <Badge tone="success">{t('active')}</Badge> : null}
              </span>
              <span className="text-muted">{formatDateTime(version.created_at, locale)}</span>
              {version.reason ? <span className="text-muted">{version.reason}</span> : null}
              {editable && !version.is_active ? (
                <Button size="sm" variant="ghost" onClick={() => onActivate(version)}>
                  {t('activateVersion')}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** A short, auditable summary of what changed since the last published
 * version — computed instead of asked for, since the diff already says it.
 * Kept in Chinese regardless of admin locale, matching the backend's own
 * auto-generated reason text (`activate_version`'s rollback default). */
function summarizeSkillChange(
  previous: AgentSkill | null,
  next: { promptTemplate: string; toolGrants: string[]; templateLabel?: string },
): string {
  if (!previous) return '创建初始版本';

  const parts: string[] = [];
  if (next.templateLabel) parts.push(`应用模板「${next.templateLabel}」`);

  if (next.promptTemplate !== previous.prompt_template) {
    const delta = next.promptTemplate.length - previous.prompt_template.length;
    parts.push(`更新提示词（${delta >= 0 ? '+' : ''}${delta} 字）`);
  }

  const previousTools = previous.tool_grants ?? [];
  const added = next.toolGrants.filter((tool) => !previousTools.includes(tool));
  const removed = previousTools.filter((tool) => !next.toolGrants.includes(tool));
  if (added.length > 0 || removed.length > 0) {
    const changes = [...added.map((tool) => `+${tool}`), ...removed.map((tool) => `-${tool}`)];
    parts.push(`工具授权：${changes.join(' ')}`);
  }

  return parts.length > 0 ? parts.join('；') : '更新技能配置';
}
