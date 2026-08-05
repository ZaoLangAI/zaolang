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
 */
export function WorkflowSteps({
  steps,
  events,
  jobStatus,
}: {
  steps: WorkflowStep[];
  events: AdminJobDetail['events'];
  jobStatus: string;
}) {
  const t = useTranslations('adminJobs');
  const byEventType = new Map((events ?? []).map((event) => [event.event_type, event]));
  const terminal = TERMINAL_STATUSES.has(jobStatus);

  const items: StepperItem[] = steps.map((step) => {
    const event = byEventType.get(step.event_type);
    const tone: StepperItem['tone'] = event
      ? event.status === 'failed' || event.status === 'expired'
        ? 'danger'
        : event.status === 'succeeded'
          ? 'success'
          : 'primary'
      : 'pending';

    return {
      key: step.key,
      label: step.label,
      detail: event ? event.message : terminal ? t('pipelineSkipped') : t('pipelinePending'),
      tone,
    };
  });

  return <Stepper items={items} />;
}
