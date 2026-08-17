'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import type { SandboxTraceStep } from '@/components/admin/workflows/sandbox-run-inspector';
import { groupErrorsByNode } from '@/components/admin/workflows/validation-errors';
import { WorkflowCanvas } from '@/components/admin/workflows/workflow-canvas';
import { WorkflowPublishDialog } from '@/components/admin/workflows/workflow-publish-dialog';
import { WorkflowSandboxDialog } from '@/components/admin/workflows/workflow-sandbox-dialog';
import { WorkflowSandboxHistoryPanel } from '@/components/admin/workflows/workflow-sandbox-history-panel';
import { WorkflowVersionsDialog } from '@/components/admin/workflows/workflow-versions-dialog';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Badge, EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import {
  IMAGE_ASSET_KIND_LABEL_KEYS,
  IMAGE_ASSET_KINDS,
  OPERATION_LABEL_KEYS,
  WORKFLOW_EDITOR_OPERATIONS,
  operationHasAssetKinds,
  type ImageAssetKindValue,
  type OperationValue,
} from '@/lib/admin/operations';
import { atLeast, type AdminRole } from '@/lib/admin/rbac';
import { adminApi } from '@/lib/api/admin-client';
import type {
  LogEntry,
  NodeTypeView,
  Page,
  WorkflowGraphJson,
  WorkflowTemplateView,
} from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

const EMPTY_GRAPH: WorkflowGraphJson = { nodes: [], edges: [] };
// How far back the engine-failure hotspot query looks — long enough to
// surface a node that only breaks on an unusual input, short enough that a
// fixed-and-republished node stops being flagged within a week.
const HOTSPOT_WINDOW_DAYS = 7;

/**
 * The Coze/ComfyUI-style node editor for `GenerationWorkflowTemplate`.
 *
 * One independent version history per `Operation` (backend: `UniqueConstraint
 * (operation, version)`). The "unpublished changes" guard lives here rather
 * than per-tab since it is a global overlay; everything specific to one
 * operation's data lives in `WorkflowOperationTab`, remounted (via `key`)
 * whenever the operation or the reload token changes — the React-recommended
 * way to reset a whole subtree's state on a prop change, instead of
 * resetting it by hand inside an effect.
 *
 * Editing a node's own Prompt is deliberately out of scope here: agent-bound
 * nodes only pick *which* agent/role/slot to run (`NodeConfigForm`, backed by
 * `graph_json`) — the Prompt content itself belongs to the agent module and
 * is only editable from `/admin/agents`.
 */
export function WorkflowEditor({ nodeTypeCatalog }: { nodeTypeCatalog: NodeTypeView[] }) {
  const t = useTranslations('adminWorkflows');
  const tProviders = useTranslations('adminProviders');
  const { role } = useAdminSession();

  const [operation, setOperationState] = useState<OperationValue>(WORKFLOW_EDITOR_OPERATIONS[0]);
  // Only meaningful for text_to_image/image_to_image — every other operation
  // always runs the one generic template. `null` means "generic" (backend
  // `asset_kind=NULL`), matching `GenerationWorkflowTemplate.asset_kind`.
  const [assetKind, setAssetKind] = useState<ImageAssetKindValue | null>(null);
  const [dirty, setDirty] = useState(false);
  // A navigation the operator asked for while the canvas has unpublished
  // edits — held here until they confirm discarding or cancel.
  const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null);

  // A page navigation loses nothing server-side (nothing is autosaved), but
  // a tab switch or reload inside this SPA-like editor would silently drop
  // the canvas's unpublished draft, so both are guarded the same way.
  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  const guardNavigation = useCallback(
    (action: () => void) => {
      if (dirty) setPendingNavigation(() => action);
      else action();
    },
    [dirty],
  );

  const switchOperation = (next: OperationValue) => {
    if (next === operation) return;
    guardNavigation(() => {
      setDirty(false);
      setOperationState(next);
      setAssetKind(null);
    });
  };

  const switchAssetKind = (next: ImageAssetKindValue | null) => {
    if (next === assetKind) return;
    guardNavigation(() => {
      setDirty(false);
      setAssetKind(next);
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <div
        role="tablist"
        aria-label={t('operations')}
        className="flex flex-wrap items-center gap-2 border-b border-border pb-2"
      >
        {WORKFLOW_EDITOR_OPERATIONS.map((op) => (
          <button
            key={op}
            role="tab"
            type="button"
            aria-selected={operation === op}
            title={op === 'text_to_image' ? t('tabImageCreationHint') : undefined}
            onClick={() => switchOperation(op)}
            className={
              operation === op
                ? 'rounded-[var(--radius-sm)] bg-primary/12 px-3 py-1.5 text-sm text-primary'
                : 'rounded-[var(--radius-sm)] px-3 py-1.5 text-sm text-muted hover:bg-surface-soft hover:text-text'
            }
          >
            {op === 'text_to_image' ? t('tabImageCreation') : tProviders(OPERATION_LABEL_KEYS[op])}
          </button>
        ))}
        {dirty ? (
          <Badge tone="amber" className="ml-1">
            {t('unpublishedChanges')}
          </Badge>
        ) : null}
      </div>

      <WorkflowOperationTab
        key={`${operation}:${assetKind ?? ''}`}
        operation={operation}
        assetKind={operationHasAssetKinds(operation) ? assetKind : null}
        onAssetKindChange={switchAssetKind}
        nodeTypeCatalog={nodeTypeCatalog}
        role={role}
        onDirtyChange={setDirty}
        guardNavigation={guardNavigation}
      />

      <Dialog
        open={pendingNavigation !== null}
        onClose={() => setPendingNavigation(null)}
        title={t('discardChangesTitle')}
        description={t('discardChangesDesc')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setPendingNavigation(null)}>
              {t('keepEditing')}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                const action = pendingNavigation;
                setPendingNavigation(null);
                action?.();
              }}
            >
              {t('discardChangesConfirm')}
            </Button>
          </>
        }
      >
        <></>
      </Dialog>
    </div>
  );
}

function WorkflowOperationTab({
  operation,
  assetKind,
  onAssetKindChange,
  nodeTypeCatalog,
  role,
  onDirtyChange,
  guardNavigation,
}: {
  operation: OperationValue;
  /** `null` both for "no asset-kind split on this operation" and for the
   * generic (`asset_kind=NULL`) template within a split operation — the
   * picker is only rendered at all when `operationHasAssetKinds(operation)`. */
  assetKind: ImageAssetKindValue | null;
  onAssetKindChange: (next: ImageAssetKindValue | null) => void;
  nodeTypeCatalog: NodeTypeView[];
  role: AdminRole;
  onDirtyChange: (dirty: boolean) => void;
  guardNavigation: (action: () => void) => void;
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
  const [sandboxOpen, setSandboxOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const invalidNodeErrors = useMemo(() => groupErrorsByNode(validationErrors), [validationErrors]);

  const [hotspotCounts, setHotspotCounts] = useState<Map<string, number>>(new Map());
  const [sandboxTrace, setSandboxTrace] = useState<SandboxTraceStep[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    const query = assetKind ? { asset_kind: assetKind } : undefined;
    Promise.all([
      adminApi
        .get<WorkflowTemplateView>(`/v1/admin/workflow-templates/${operation}`, { query })
        .catch((caught) => {
          if (caught instanceof ApiError && caught.isNotFound) return null;
          throw caught;
        }),
      adminApi.get<{ items: WorkflowTemplateView[] }>(
        `/v1/admin/workflow-templates/${operation}/versions`,
        { query },
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

  // Best-effort: structural validation (phase 1) catches graphs that are
  // guaranteed to misbehave; this catches nodes that are structurally fine
  // but have actually blown up on real jobs recently. Scoped defensively to
  // node ids that exist in *this* graph — `workflow_engine_failure` rows
  // don't carry which operation they happened under, and every operation
  // starts from the same `default_graph()` node ids, so without this filter
  // a failure under one operation could highlight an unrelated one.
  useEffect(() => {
    let cancelled = false;
    const since = new Date(Date.now() - HOTSPOT_WINDOW_DAYS * 86_400_000).toISOString();
    adminApi
      .get<Page<LogEntry>>('/v1/admin/logs', {
        query: {
          source: 'pipeline',
          q: 'workflow_engine_failure',
          created_after: since,
          limit: 200,
        },
      })
      .then((page) => {
        if (cancelled) return;
        const graphNodeIds = new Set(
          ((template?.graph as WorkflowGraphJson | undefined)?.nodes ?? []).map((node) => node.id),
        );
        const counts = new Map<string, number>();
        for (const entry of page.items) {
          const nodeId =
            entry.details && typeof entry.details.node_id === 'string'
              ? entry.details.node_id
              : null;
          if (!nodeId || !graphNodeIds.has(nodeId)) continue;
          counts.set(nodeId, (counts.get(nodeId) ?? 0) + (entry.occurrence_count ?? 1));
        }
        setHotspotCounts(counts);
      })
      .catch(() => {
        if (!cancelled) setHotspotCounts(new Map());
      });
    return () => {
      cancelled = true;
    };
  }, [reloadToken, template]);

  const currentGraph = (template?.graph as WorkflowGraphJson | undefined) ?? EMPTY_GRAPH;
  const reload = () => {
    setReloadToken((token) => token + 1);
    setValidationErrors([]);
    setSandboxTrace(null);
    onDirtyChange(false);
  };

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {template ? (
            <>
              <Badge tone="success">
                v{template.version} · {template.name}
              </Badge>
              <span className="text-xs text-muted">
                {t('versionCount', { count: versions.length })}
              </span>
            </>
          ) : template === null && !loadError ? (
            <Badge tone="amber">{t('noActiveTemplate')}</Badge>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          {operationHasAssetKinds(operation) ? (
            <select
              aria-label={t('assetKind')}
              title={t('assetKindHint')}
              value={assetKind ?? ''}
              onChange={(event) =>
                onAssetKindChange((event.target.value || null) as ImageAssetKindValue | null)
              }
              className="h-9 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2.5 text-sm text-text"
            >
              <option value="">{t('assetKindGeneral')}</option>
              {IMAGE_ASSET_KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {t(IMAGE_ASSET_KIND_LABEL_KEYS[kind])}
                </option>
              ))}
            </select>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => guardNavigation(() => setVersionsOpen(true))}
          >
            {t('versionHistory')}
          </Button>
          <Button
            size="sm"
            variant={historyOpen ? 'secondary' : 'ghost'}
            onClick={() => {
              if (historyOpen) {
                setSandboxTrace(null);
                setHistoryOpen(false);
              } else {
                setHistoryOpen(true);
              }
            }}
          >
            {t('sandboxHistory')}
          </Button>
          {canDryRun ? (
            <Button size="sm" variant="secondary" onClick={() => setSandboxOpen(true)}>
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

      <div className="relative min-w-0">
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
            invalidNodeErrors={invalidNodeErrors}
            hotspotCounts={hotspotCounts}
            trace={sandboxTrace}
            onChange={setWorkingGraph}
            onDirty={() => onDirtyChange(true)}
          />
        )}
        {historyOpen ? (
          <WorkflowSandboxHistoryPanel
            operation={operation}
            onClose={() => {
              setSandboxTrace(null);
              setHistoryOpen(false);
            }}
            onTrace={setSandboxTrace}
          />
        ) : null}
      </div>

      {canDryRun ? (
        <WorkflowSandboxDialog
          open={sandboxOpen}
          operation={operation}
          assetKind={assetKind}
          draftGraph={workingGraph}
          onClose={() => setSandboxOpen(false)}
          onTrace={setSandboxTrace}
        />
      ) : null}

      {canEdit ? (
        <WorkflowPublishDialog
          open={publishOpen}
          operation={operation}
          assetKind={assetKind}
          graph={workingGraph}
          defaultName={template?.name ?? t('defaultTemplateName')}
          onClose={() => setPublishOpen(false)}
          onValidated={setValidationErrors}
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
    </>
  );
}
