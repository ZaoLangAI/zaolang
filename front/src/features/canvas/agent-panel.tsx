'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { TextArea } from '@/components/ui/field';
import { Badge } from '@/components/ui/primitives';

import type { CanvasAgentTask } from './agent-api';
import type { CanvasFlowNode } from './graph-convert';
import { useCanvasAgent } from './use-canvas-agent';

/**
 * The Agent card's panel: describe a goal, review the plan, confirm the spend.
 *
 * The two-step shape is the point. A plan arrives priced, and the confirm
 * button is the only thing that moves credits — so the cost is on screen
 * before it is charged, not after.
 */

function TaskRow({ task }: { task: CanvasAgentTask }) {
  const t = useTranslations('canvas');
  const tone =
    task.status === 'landed'
      ? 'text-success'
      : task.status === 'failed' || task.status === 'skipped'
        ? 'text-danger'
        : 'text-muted';
  return (
    <li className="rounded-[var(--radius-sm)] border border-border p-2">
      <div className="flex items-center justify-between gap-2">
        <Badge>{t(`agent.operation.${task.operation}`)}</Badge>
        <span className={`text-[11px] ${tone}`}>{t(`agent.taskStatus.${task.status}`)}</span>
      </div>
      <p className="mt-1 line-clamp-3 text-xs text-muted">{task.prompt}</p>
      {task.failure_message ? (
        <p className="mt-1 text-[11px] text-danger">{task.failure_message}</p>
      ) : null}
    </li>
  );
}

export function AgentPanel({ node, canvasId }: { node: CanvasFlowNode; canvasId: string }) {
  const t = useTranslations('canvas');
  const { state, plan, confirm, cancel, reset } = useCanvasAgent(canvasId);
  const [goal, setGoal] = useState('');

  const busy = state.phase === 'planning' || state.phase === 'submitting';
  const run = state.run;

  return (
    <div className="space-y-2.5">
      <TextArea
        label={t('agent.goalLabel')}
        hint={t('agent.goalHint')}
        value={goal}
        rows={3}
        maxLength={2000}
        disabled={busy}
        onChange={(event) => setGoal(event.target.value)}
      />

      {state.phase === 'idle' || state.phase === 'error' ? (
        <Button
          size="sm"
          disabled={goal.trim().length === 0}
          onClick={() => void plan({ agentNodeId: node.id, goal })}
        >
          {t('agent.plan')}
        </Button>
      ) : null}

      {state.phase === 'planning' ? (
        <div className="rounded-[var(--radius-sm)] border border-border p-2">
          <p className="text-xs text-muted">{t('agent.planning')}</p>
          {/* The reasoning trace, not a spinner: it is the only honest signal
              that something is happening during a slow call. */}
          {state.thinking ? (
            <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-[11px] text-muted">
              {state.thinking}
            </p>
          ) : null}
          <Button size="sm" variant="ghost" className="mt-2" onClick={() => void cancel()}>
            {t('agent.stop')}
          </Button>
        </div>
      ) : null}

      {run && state.phase !== 'planning' ? (
        <div className="space-y-2">
          {run.summary ? <p className="text-xs text-text">{run.summary}</p> : null}
          <ul className="space-y-1.5">
            {run.tasks.map((task) => (
              <TaskRow key={task.id} task={task} />
            ))}
          </ul>

          {state.phase === 'reviewing' ? (
            <>
              {/* The cost, before the tap that incurs it. */}
              <p className="text-xs text-muted">
                {t('agent.quote', { credits: run.quoted_credits })}
              </p>
              <div className="flex gap-1.5">
                <Button size="sm" disabled={busy} onClick={() => void confirm()}>
                  {t('agent.confirm')}
                </Button>
                <Button size="sm" variant="ghost" onClick={reset}>
                  {t('agent.discard')}
                </Button>
              </div>
            </>
          ) : null}

          {state.phase === 'submitting' ? (
            <p className="text-xs text-muted">{t('agent.submitting')}</p>
          ) : null}

          {state.phase === 'done' ? (
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted">{t(`agent.runStatus.${run.status}`)}</span>
              <Button size="sm" variant="ghost" onClick={reset}>
                {t('agent.newRun')}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}

      {state.error ? <p className="text-xs text-danger">{state.error}</p> : null}
    </div>
  );
}
