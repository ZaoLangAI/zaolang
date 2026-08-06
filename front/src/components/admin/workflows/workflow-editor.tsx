'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { AgentSkillEditorDialog } from '@/components/admin/agents/agent-skills-panel';
import { WorkflowCanvas } from '@/components/admin/workflows/workflow-canvas';
import { WorkflowDryRunDialog } from '@/components/admin/workflows/workflow-dry-run-dialog';
import { WorkflowPublishDialog } from '@/components/admin/workflows/workflow-publish-dialog';
import { WorkflowVersionsDialog } from '@/components/admin/workflows/workflow-versions-dialog';
import { Button } from '@/components/ui/button';
import { Badge, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { atLeast, type AdminRole } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type {
  AgentNode,
  NodeTypeView,
  WorkflowGraphJson,
  WorkflowTemplateView,
} from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

const OPERATIONS = [
  'text_to_image',
  'image_to_image',
  'text_to_video',
  'image_to_video',
  'video_to_video',
  'audio_generation',
] as const;

const OPERATION_LABEL_KEYS: Record<(typeof OPERATIONS)[number], string> = {
  text_to_image: 'capabilityTextToImage',
  image_to_image: 'capabilityImageToImage',
  text_to_video: 'capabilityTextToVideo',
  image_to_video: 'capabilityImageToVideo',
  video_to_video: 'capabilityVideoToVideo',
  audio_generation: 'capabilityAudioGeneration',
};

const EMPTY_GRAPH: WorkflowGraphJson = { nodes: [], edges: [] };

/**
 * The Coze/ComfyUI-style node editor for `GenerationWorkflowTemplate`.
 *
 * One independent version history per `Operation` (backend: `UniqueConstraint
 * (operation, version)`). The prompt-editing dialog lives here rather than
 * per-tab since it is a global overlay; everything else that is specific to
 * one operation's data lives in `WorkflowOperationTab`, remounted (via
 * `key`) whenever the operation or the reload token changes — the React-
 * recommended way to reset a whole subtree's state on a prop change,
 * instead of resetting it by hand inside an effect.
 */
export function WorkflowEditor({ nodeTypeCatalog }: { nodeTypeCatalog: NodeTypeView[] }) {
  const t = useTranslations('adminWorkflows');
  const tProviders = useTranslations('adminProviders');
  const { role } = useAdminSession();

  const [operation, setOperation] = useState<(typeof OPERATIONS)[number]>(OPERATIONS[0]);
  const [editingAgentRole, setEditingAgentRole] = useState<string | null>(null);
  const [editingAgentNode, setEditingAgentNode] = useState<AgentNode | null>(null);

  useEffect(() => {
    if (!editingAgentRole) return;
    let cancelled = false;
    adminApi.get<{ items: AgentNode[] }>('/v1/admin/agent-nodes').then((page) => {
      if (cancelled) return;
      setEditingAgentNode(page.items.find((node) => node.role === editingAgentRole) ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [editingAgentRole]);

  return (
    <div className="flex flex-col gap-4">
      <div
        role="tablist"
        aria-label={t('operations')}
        className="flex flex-wrap gap-2 border-b border-border pb-2"
      >
        {OPERATIONS.map((op) => (
          <button
            key={op}
            role="tab"
            type="button"
            aria-selected={operation === op}
            onClick={() => setOperation(op)}
            className={
              operation === op
                ? 'rounded-[var(--radius-sm)] bg-primary/12 px-3 py-1.5 text-sm text-primary'
                : 'rounded-[var(--radius-sm)] px-3 py-1.5 text-sm text-muted hover:bg-surface-soft hover:text-text'
            }
          >
            {tProviders(OPERATION_LABEL_KEYS[op])}
          </button>
        ))}
      </div>

      <WorkflowOperationTab
        key={operation}
        operation={operation}
        nodeTypeCatalog={nodeTypeCatalog}
        role={role}
        onEditPrompt={setEditingAgentRole}
      />

      {editingAgentRole && editingAgentNode?.role === editingAgentRole ? (
        <AgentSkillEditorDialog
          node={editingAgentNode}
          editable={atLeast(role, 'admin')}
          onClose={() => setEditingAgentRole(null)}
          onPublished={() => {}}
        />
      ) : null}
    </div>
  );
}

function WorkflowOperationTab({
  operation,
  nodeTypeCatalog,
  role,
  onEditPrompt,
}: {
  operation: string;
  nodeTypeCatalog: NodeTypeView[];
  role: AdminRole;
  onEditPrompt: (agentRole: string) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const tAdmin = useTranslations('admin');
  const canEdit = atLeast(role, 'admin');
  const canDryRun = atLeast(role, 'operator');

  const [template, setTemplate] = useState<WorkflowTemplateView | null | undefined>(undefined);
  const [versions, setVersions] = useState<WorkflowTemplateView[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [workingGraph, setWorkingGraph] = useState<WorkflowGraphJson>(EMPTY_GRAPH);

  const [publishOpen, setPublishOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [dryRunOpen, setDryRunOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      adminApi
        .get<WorkflowTemplateView>(`/v1/admin/workflow-templates/${operation}`)
        .catch((caught) => {
          if (caught instanceof ApiError && caught.isNotFound) return null;
          throw caught;
        }),
      adminApi.get<{ items: WorkflowTemplateView[] }>(
        `/v1/admin/workflow-templates/${operation}/versions`,
      ),
    ])
      .then(([active, versionPage]) => {
        if (cancelled) return;
        setTemplate(active);
        setVersions(versionPage.items);
      })
      .catch((caught) => {
        if (cancelled) return;
        setLoadError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
        setTemplate(null);
      });
    return () => {
      cancelled = true;
    };
    // Mount-only: a new `operation` remounts this whole component (see the
    // `key` on `WorkflowOperationTab` above), and `reloadToken` bumping is
    // handled by `reload()` re-running this same effect deliberately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken]);

  const currentGraph = (template?.graph as WorkflowGraphJson | undefined) ?? EMPTY_GRAPH;
  const reload = () => setReloadToken((token) => token + 1);

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {template ? (
            <>
              <Badge tone="success">
                v{template.version} · {template.name}
              </Badge>
              <span className="text-xs text-muted">{t('versionCount', { count: versions.length })}</span>
            </>
          ) : template === null && !loadError ? (
            <Badge tone="amber">{t('noActiveTemplate')}</Badge>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => setVersionsOpen(true)}>
            {t('versionHistory')}
          </Button>
          {canDryRun ? (
            <Button size="sm" variant="secondary" onClick={() => setDryRunOpen(true)}>
              {t('dryRun')}
            </Button>
          ) : null}
          {canEdit ? (
            <Button size="sm" onClick={() => setPublishOpen(true)}>
              {t('publish')}
            </Button>
          ) : null}
        </div>
      </div>

      {loadError ? <ErrorNotice title={loadError} /> : null}

      {template === undefined ? (
        <div className="flex h-40 items-center justify-center">
          <Spinner />
        </div>
      ) : template === null && !loadError ? (
        <EmptyState
          title={t('noActiveTemplate')}
          description={t('noActiveTemplateDesc')}
          action={
            canEdit ? (
              <Button size="sm" variant="secondary" onClick={() => setPublishOpen(true)}>
                {t('publish')}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <WorkflowCanvas
          key={reloadToken}
          initialGraph={currentGraph}
          nodeTypeCatalog={nodeTypeCatalog}
          readOnly={!canEdit}
          onChange={setWorkingGraph}
          onEditPrompt={onEditPrompt}
        />
      )}

      {canEdit ? (
        <WorkflowPublishDialog
          open={publishOpen}
          operation={operation}
          graph={workingGraph}
          defaultName={template?.name ?? t('defaultTemplateName')}
          onClose={() => setPublishOpen(false)}
          onPublished={() => {
            setPublishOpen(false);
            reload();
          }}
        />
      ) : null}

      <WorkflowVersionsDialog
        open={versionsOpen}
        operation={operation}
        currentGraph={currentGraph}
        versions={versions}
        editable={canEdit}
        onClose={() => setVersionsOpen(false)}
        onRolledBack={() => {
          setVersionsOpen(false);
          reload();
        }}
      />

      {canDryRun ? (
        <WorkflowDryRunDialog open={dryRunOpen} operation={operation} onClose={() => setDryRunOpen(false)} />
      ) : null}
    </>
  );
}
