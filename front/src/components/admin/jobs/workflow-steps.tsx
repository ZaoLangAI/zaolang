'use client';

import { useTranslations } from 'next-intl';

import { Stepper, type StepperItem } from '@/components/admin/stepper';
import type { AdminJobDetail, WorkflowStep } from '@/lib/api/admin-types';

const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

/**
 * The declared pipeline overlaid with what actually happened, as a horizontal
 * stepper.
 *
 * A job that failed at "safety" never emits `planning`/`routing`/... events,
 * so `job.events` alone cannot show an operator how far the pipeline was
 * *supposed* to go. Steps the job hasn't reached read as "pending" while it
 * is still running, and as "not reached" once it has terminated.
 *
 * Matches events to steps by `node_id` first — the graph node that actually
 * emitted the event — and only falls back to guessing from `event_type` for
 * events recorded before that column existed. Two nodes emitting the same
 * `event_type` (two `custom_agent` nodes, a retry's `PROGRESS`) would
 * otherwise collide on the fallback path alone.
 */
export function WorkflowSteps({
  steps,
  events,
  agentRuns,
  jobStatus,
}: {
  steps: WorkflowStep[];
  events: AdminJobDetail['events'];
  agentRuns: AdminJobDetail['agent_runs'];
  jobStatus: string;
}) {
  const t = useTranslations('adminJobs');
  const byNodeId = new Map(
    (events ?? []).filter((event) => event.node_id != null).map((event) => [event.node_id, event]),
  );
  const byEventType = new Map((events ?? []).map((event) => [event.event_type, event]));
  const agentByNodeId = new Map(
    (agentRuns ?? []).filter((run) => run.node_id != null).map((run) => [run.node_id, run]),
  );
  const terminal = TERMINAL_STATUSES.has(jobStatus);

  const items: StepperItem[] = steps.map((step) => {
    const event = byNodeId.get(step.key) ?? byEventType.get(step.event_type);
    const tone: StepperItem['tone'] = event
      ? event.status === 'failed' || event.status === 'expired'
        ? 'danger'
        : event.status === 'succeeded'
          ? 'success'
          : 'primary'
      : 'pending';

    const agentRun = agentByNodeId.get(step.key);

    return {
      key: step.key,
      label: step.label,
      detail: event ? event.message : terminal ? t('pipelineSkipped') : t('pipelinePending'),
      tone,
      agent: agentRun ? (agentRun.agent_display_name ?? agentRun.agent_name) : null,
      degradedLabel: agentRun?.degraded ? t('degraded') : null,
    };
  });

  return <Stepper items={items} />;
}
