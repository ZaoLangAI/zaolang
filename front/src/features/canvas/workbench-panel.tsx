'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { AwaitingInputPanel } from '@/components/job/awaiting-input-panel';
import { STAGES, stageLabelKey } from '@/components/job/job-stages';
import { jobStageState } from '@/components/job/job-stage-state';
import { jobOutputs } from '@/components/job/job-outputs';
import { OutputGallery } from '@/components/media/output-gallery';
import { useJobStream } from '@/lib/use-job-stream';
import { cn } from '@/lib/cn';

import { listCanvasAgentRuns, type CanvasAgentRun, type CanvasAgentTask } from './agent-api';

/**
 * What the Agent is doing on this canvas, and what it did before.
 *
 * Two levels: runs, and the tasks under them. The list re-reads whenever the
 * canvas change stream carries an `agent_run`/`agent_task` frame — `revision`
 * is that signal, already plumbed through `useCanvasSync`.
 *
 * **Exactly one live job stream at a time.** Expanding a task opens it;
 * collapsing closes it. That is not thrift: `sse_quota` caps a user at 8
 * concurrent streams and the canvas itself already holds one, so a panel that
 * mounted a stream per task would eat the budget and starve the notification
 * feed — the very thing the canvas-scoped stream was built to avoid.
 */

const SETTLED = new Set<CanvasAgentTask['status']>(['landed', 'failed', 'cancelled', 'skipped']);

/** Statuses whose card is worth opening — anything that has, or will have,
 * a job behind it. */
const HAS_JOB = new Set<CanvasAgentTask['status']>(['submitted', 'running', 'landed', 'failed']);

function TaskStages({
  status,
  operation,
  events,
}: {
  status: string;
  operation: string;
  events: { event_type: string }[];
}) {
  // `stageLabelKey` returns keys in the `jobPage` namespace; the panel's own
  // copy lives under `canvas`. Two hooks rather than one root-namespaced `t`,
  // so neither set of keys has to be written out fully qualified.
  const t = useTranslations('jobPage');
  const tc = useTranslations('canvas');
  const { reached, displayStage, finished } = jobStageState(status, events);
  return (
    <ol className="flex flex-wrap items-center gap-1.5" aria-label={tc('workbench.stagesLabel')}>
      {STAGES.map((stage) => {
        const active = stage === displayStage && !finished;
        return (
          <li key={stage} className="flex items-center gap-1">
            <span
              aria-hidden="true"
              className={cn(
                'size-1.5 rounded-full',
                reached.has(stage) ? 'bg-success' : 'bg-border',
                active && 'bg-primary',
              )}
            />
            <span className="text-[10px] text-muted">{t(stageLabelKey(stage, operation))}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** The expanded task: one live stream, its stages, and its output. */
function TaskDetail({ task, onLanded }: { task: CanvasAgentTask; onLanded: () => void }) {
  const t = useTranslations('canvas');
  const { job, events } = useJobStream(task.generation_job_id ?? '', null);
  const status = job?.status ?? (task.status === 'landed' ? 'succeeded' : 'running');
  const { urls, assetIds } = jobOutputs(job);

  return (
    <div className="mt-2 space-y-2 border-t border-border pt-2">
      <TaskStages status={status} operation={task.operation} events={events} />

      {job?.status === 'awaiting_input' ? (
        <AwaitingInputPanel jobId={job.id} onSubmitted={onLanded} />
      ) : null}

      {urls.length > 0 ? (
        <OutputGallery
          urls={urls}
          assetIds={assetIds}
          mediaType={task.operation.endsWith('_video') ? 'video' : 'image'}
          title={t('workbench.outputTitle')}
          itemLabel={(index, total) => t('workbench.outputItem', { index: index + 1, total })}
          maxHeight={220}
        />
      ) : null}

      {job?.failure_message ? (
        <ErrorNotice title={t('workbench.taskFailed')} detail={job.failure_message} />
      ) : null}
    </div>
  );
}

function TaskRow({
  task,
  expanded,
  onToggle,
  onRestore,
  restoring,
}: {
  task: CanvasAgentTask;
  expanded: boolean;
  onToggle: () => void;
  onRestore: () => void;
  restoring: boolean;
}) {
  const t = useTranslations('canvas');
  const tone =
    task.status === 'landed'
      ? 'text-success'
      : task.status === 'failed' || task.status === 'skipped'
        ? 'text-danger'
        : 'text-muted';
  const openable = HAS_JOB.has(task.status) && !!task.generation_job_id;

  return (
    <li className="rounded-[var(--radius-sm)] border border-border p-2">
      <div className="flex items-center justify-between gap-2">
        <Badge>{t(`agent.operation.${task.operation}`)}</Badge>
        <span className={`text-[11px] ${tone}`}>{t(`agent.taskStatus.${task.status}`)}</span>
      </div>
      <p className="mt-1 line-clamp-2 text-xs text-muted">{task.prompt}</p>
      {task.failure_message ? (
        <p className="mt-1 text-[11px] text-danger">{task.failure_message}</p>
      ) : null}

      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {openable ? (
          <Button size="sm" variant="ghost" onClick={onToggle} aria-expanded={expanded}>
            {t(expanded ? 'workbench.collapse' : 'workbench.expand')}
          </Button>
        ) : null}
        {/* Results land on the canvas by themselves. This is only for when the
            card was deleted afterwards and the user wants it back. */}
        {task.status === 'landed' ? (
          <Button size="sm" variant="ghost" disabled={restoring} onClick={onRestore}>
            {t('workbench.restore')}
          </Button>
        ) : null}
      </div>

      {expanded ? <TaskDetail task={task} onLanded={onToggle} /> : null}
    </li>
  );
}

function RunRow({
  run,
  expandedTaskId,
  onToggleTask,
  onRestore,
  restoringTaskId,
}: {
  run: CanvasAgentRun;
  expandedTaskId: string | null;
  onToggleTask: (taskId: string) => void;
  onRestore: (task: CanvasAgentTask) => void;
  restoringTaskId: string | null;
}) {
  const t = useTranslations('canvas');
  const landed = run.tasks.filter((task) => task.status === 'landed').length;
  const settled = run.tasks.filter((task) => SETTLED.has(task.status)).length;
  const tone =
    run.status === 'failed'
      ? 'text-danger'
      : run.status === 'succeeded'
        ? 'text-success'
        : 'text-muted';

  return (
    <li className="rounded-[var(--radius-sm)] border border-border p-2">
      <div className="flex items-start justify-between gap-2">
        <p className="line-clamp-2 text-xs text-text">{run.goal}</p>
        <span className={`shrink-0 text-[11px] ${tone}`}>{t(`agent.runStatus.${run.status}`)}</span>
      </div>
      <p className="mt-1 text-[11px] text-muted">
        {t('workbench.progress', { landed, total: run.tasks.length })}
        {settled < run.tasks.length ? ` · ${t('workbench.inFlight')}` : ''}
      </p>
      {run.failure_message ? (
        <p className="mt-1 text-[11px] text-danger">{run.failure_message}</p>
      ) : null}

      {run.tasks.length > 0 ? (
        <ul className="mt-2 space-y-1.5">
          {run.tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              expanded={expandedTaskId === task.id}
              onToggle={() => onToggleTask(task.id)}
              onRestore={() => onRestore(task)}
              restoring={restoringTaskId === task.id}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function WorkbenchPanel({
  canvasId,
  /** Bumped by the shell whenever an agent frame arrives on the change
   * stream. A counter rather than the frames themselves: the panel wants the
   * server's view of a run, not a partial reconstruction of it. */
  revision = 0,
  onRestoreTask,
}: {
  canvasId: string;
  revision?: number;
  /** Re-land a result whose card was deleted. */
  onRestoreTask?: (task: CanvasAgentTask) => Promise<void>;
}) {
  const t = useTranslations('canvas');
  const [runs, setRuns] = useState<CanvasAgentRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // One at a time — see the module docstring.
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [restoringTaskId, setRestoringTaskId] = useState<string | null>(null);

  const load = useCallback(() => {
    listCanvasAgentRuns(canvasId)
      .then((next) => {
        setRuns(next);
        setError(null);
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause));
      });
  }, [canvasId]);

  useEffect(load, [load, revision]);

  const restore = useCallback(
    (task: CanvasAgentTask) => {
      if (!onRestoreTask) return;
      setRestoringTaskId(task.id);
      void onRestoreTask(task).finally(() => setRestoringTaskId(null));
    },
    [onRestoreTask],
  );

  if (error) return <p className="text-xs text-danger">{error}</p>;
  if (runs === null) return <p className="text-xs text-muted">{t('workbench.loading')}</p>;
  if (runs.length === 0) return <p className="text-xs text-muted">{t('workbench.empty')}</p>;

  return (
    <ul className="space-y-1.5">
      {runs.map((run) => (
        <RunRow
          key={run.id}
          run={run}
          expandedTaskId={expandedTaskId}
          onToggleTask={(taskId) =>
            setExpandedTaskId((current) => (current === taskId ? null : taskId))
          }
          onRestore={restore}
          restoringTaskId={restoringTaskId}
        />
      ))}
    </ul>
  );
}
