'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { TextArea, TextInput } from '@/components/ui/field';
import { Badge } from '@/components/ui/primitives';

import { AgentPanel } from './agent-panel';
import { WorkflowPanel } from './workflow-panel';
import { CameraControl, readCameraControl } from './camera-control';
import type { CameraControlOptions } from './canvas-camera';
import type { CanvasFlowNode } from './graph-convert';

/** Kinds whose label is the user's own text.
 *
 * A bound node's label is re-derived from the hydration snapshot on every
 * load, so letting someone type over it would silently lose the edit on the
 * next visit. Those show the domain title read-only instead.
 */
const EDITABLE_LABEL_KINDS = new Set(['note', 'prompt', 'image', 'video']);

/** Kinds that carry a body of text worth editing on the canvas itself. */
const TEXT_BODY_KINDS = new Set(['note', 'prompt']);

export interface NodePatch {
  label?: string;
  text?: string;
  camera?: CameraControlOptions;
}

export function CanvasProperties({
  canvasId,
  node,
  onPatch,
  onGenerate,
  onSendToSeries,
  canSendToSeries,
  onUpload,
  uploading = false,
  referenceCount = 0,
}: {
  canvasId: string;
  node: CanvasFlowNode | null;
  onPatch: (nodeId: string, patch: NodePatch) => void;
  onGenerate?: (node: CanvasFlowNode) => void;
  onSendToSeries?: (node: CanvasFlowNode) => void;
  canSendToSeries: boolean;
  onUpload?: (node: CanvasFlowNode, file: File) => void;
  uploading?: boolean;
  /** How many upstream picture cards feed this prompt — see `upstreamAssetIds`. */
  referenceCount?: number;
}) {
  const t = useTranslations('canvas');

  if (!node) {
    return (
      <aside className="w-72 shrink-0 border-l border-border p-4">
        <p className="text-xs text-muted">{t('propsEmpty')}</p>
      </aside>
    );
  }

  const kind = node.data.kind;
  const editableLabel = EDITABLE_LABEL_KINDS.has(kind);
  const hasTextBody = TEXT_BODY_KINDS.has(kind);
  const text = typeof node.data.payload?.text === 'string' ? node.data.payload.text : '';

  return (
    <aside className="flex w-72 shrink-0 flex-col gap-3 overflow-y-auto border-l border-border p-4">
      <div className="flex items-center gap-2">
        <Badge>{t(`kind.${kind}`)}</Badge>
        {node.data.stale ? <Badge tone="danger">{t('staleBadge')}</Badge> : null}
      </div>

      {kind === 'agent' ? (
        // The Agent card owns its whole panel: its state lives on
        // `CanvasAgentRun`, not in the card's `data`, so none of the ordinary
        // label/text editing below applies to it.
        <AgentPanel node={node} canvasId={canvasId} />
      ) : kind === 'skill' ? (
        // Same reasoning: a skill card's content is the skill, and when that
        // skill declares variables the panel is the form that runs it.
        <WorkflowPanel node={node} canvasId={canvasId} />
      ) : editableLabel ? (
        <TextInput
          label={t('propsLabel')}
          value={node.data.label}
          maxLength={120}
          onChange={(event) => onPatch(node.id, { label: event.target.value })}
        />
      ) : (
        <div>
          <p className="text-xs text-muted">{t('propsLabel')}</p>
          <p className="mt-1 text-sm text-text">{node.data.label || t('untitledNode')}</p>
          <p className="mt-1 text-[11px] text-muted">{t('propsBoundHint')}</p>
        </div>
      )}

      {hasTextBody ? (
        <TextArea
          label={t(kind === 'prompt' ? 'propsPrompt' : 'propsNote')}
          value={text}
          maxLength={4000}
          onChange={(event) => onPatch(node.id, { text: event.target.value })}
        />
      ) : null}

      {onUpload && (kind === 'image' || kind === 'video') ? (
        <div className="space-y-1.5">
          <label className="block text-xs text-muted" htmlFor={`upload-${node.id}`}>
            {t('propsPicture')}
          </label>
          <input
            id={`upload-${node.id}`}
            type="file"
            accept={kind === 'image' ? 'image/*' : 'video/*'}
            disabled={uploading}
            className="block w-full text-xs text-muted file:mr-2 file:rounded-[var(--radius-sm)] file:border file:border-border file:bg-surface-soft file:px-2 file:py-1 file:text-xs"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onUpload(node, file);
              // Clear it so re-picking the same file still fires a change.
              event.target.value = '';
            }}
          />
          {uploading ? <p className="text-xs text-muted">{t('propsUploading')}</p> : null}
        </div>
      ) : null}

      {kind === 'prompt' ? (
        <CameraControl
          value={readCameraControl(node.data.payload)}
          onChange={(camera) => onPatch(node.id, { camera })}
        />
      ) : null}

      {onGenerate && kind === 'prompt' ? (
        <>
          <Button size="sm" onClick={() => onGenerate(node)} disabled={!text.trim()}>
            {t('propsGenerate')}
          </Button>
          {referenceCount > 0 ? (
            <p className="text-[11px] text-muted">
              {t('propsReferenceCount', { count: referenceCount })}
            </p>
          ) : (
            <p className="text-[11px] text-muted">{t('propsReferenceHint')}</p>
          )}
        </>
      ) : null}

      {onSendToSeries && canSendToSeries ? (
        <Button size="sm" variant="secondary" onClick={() => onSendToSeries(node)}>
          {t('propsSendToSeries')}
        </Button>
      ) : null}

      {node.data.stale ? <p className="text-xs text-danger">{t('staleHint')}</p> : null}
    </aside>
  );
}
