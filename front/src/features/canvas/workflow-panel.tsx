'use client';

import { useTranslations } from 'next-intl';
import dynamic from 'next/dynamic';
import { useMemo, useState } from 'react';

import { QuestionField, type QuestionAnswer } from '@/components/studio/question-field';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { ApiError } from '@/lib/api/errors';
import type { CreationSkillDetail } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

import { startCanvasWorkflowRun, type CanvasAgentRun } from './agent-api';
import type { CanvasFlowNode } from './graph-convert';
import { useConfirmCanvasAgentRun } from './use-canvas-agent';

/**
 * A skill card's panel — and, when that skill declares variables, the form
 * that turns it into a run.
 *
 * A creation workflow is just a `CreationSkill` whose `params_json` carries a
 * `variables` list in the agents' own question shape, so the form is
 * `QuestionField` rather than a second renderer that could disagree with the
 * one the awaiting-input panel already uses.
 *
 * Two steps, like the Agent panel and for the same reason: starting the run
 * prices it and stops, and the confirm is the only tap that spends anything.
 */

/** Loaded when the viewer actually reaches a locked paid workflow.
 *
 * Statically importing it pulled the marketplace unlock chain into the canvas'
 * bundle for every user, measurably (~100KB raw) and for a branch most sessions
 * never take. */
const UnlockDialog = dynamic(
  () => import('@/components/marketplace/unlock-dialog').then((mod) => mod.UnlockDialog),
  { ssr: false },
);

interface WorkflowVariable {
  id: string;
  kind: 'single_choice' | 'multi_choice' | 'free_text';
  prompt: string;
  options?: Array<{ value: string; label: string }>;
  required?: boolean;
}

const KINDS = new Set(['single_choice', 'multi_choice', 'free_text']);

/**
 * `params_json` is an unvalidated bag on the server, so this validates rather
 * than casts — `kind` included, since `QuestionField` switches on it and an
 * unknown value would silently fall through to a text box the author never
 * asked for. Mirrors `app/agents/questions.py::sanitize_question`.
 */
function variablesOf(detail: CreationSkillDetail | undefined): WorkflowVariable[] {
  const raw = (detail?.params as Record<string, unknown> | undefined)?.variables;
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is WorkflowVariable => {
    if (typeof item !== 'object' || item === null) return false;
    const candidate = item as Partial<WorkflowVariable>;
    return (
      typeof candidate.id === 'string' &&
      typeof candidate.prompt === 'string' &&
      typeof candidate.kind === 'string' &&
      KINDS.has(candidate.kind)
    );
  });
}

export function WorkflowPanel({ node, canvasId }: { node: CanvasFlowNode; canvasId: string }) {
  const t = useTranslations('canvas');
  const tSkill = useTranslations('skillLibrary');
  const skillId = node.data.binding?.skill_id ?? null;
  // The detail read is what carries `params`; the summary endpoints omit it,
  // which is exactly why `has_variables` exists on the summary at all.
  const { status, data, refetch } = useResource<CreationSkillDetail>(
    skillId ? `/v1/skills/${skillId}` : null,
  );
  const variables = useMemo(() => variablesOf(data), [data]);

  const [answers, setAnswers] = useState<Record<string, QuestionAnswer>>({});
  const [run, setRun] = useState<CanvasAgentRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);
  const confirmRun = useConfirmCanvasAgentRun();

  const missingRequired = variables.some((variable) => {
    if (!variable.required) return false;
    const value = answers[variable.id];
    return Array.isArray(value) ? value.length === 0 : !String(value ?? '').trim();
  });

  const call = async (work: () => Promise<CanvasAgentRun>) => {
    setBusy(true);
    setError(null);
    try {
      setRun(await work());
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  if (!skillId) return <p className="text-xs text-muted">{t('workflow.unbound')}</p>;
  if (status === 'failed') return <p className="text-xs text-danger">{t('workflow.loadFailed')}</p>;
  if (!data) return <Spinner />;

  // A paid workflow the viewer has not unlocked: the server withholds `params`
  // (and therefore the questions) while still reporting `has_variables`.
  const locked = data.has_variables && variables.length === 0;

  return (
    <div className="space-y-2.5">
      <div>
        <p className="text-sm text-text">{data.title}</p>
        {data.description ? (
          <p className="mt-1 text-[11px] text-muted">{data.description}</p>
        ) : null}
      </div>

      {locked ? (
        // `CreationSkillDetail.params` comes back empty for a paid skill the
        // viewer has not unlocked, so the form cannot be drawn — but
        // `has_variables` is computed server-side from the real params and is
        // still true. Without this branch a paid workflow would claim to have
        // no form at all, which is both wrong and unactionable.
        <>
          <p className="text-xs text-muted">
            {t('workflow.locked', { credits: data.access_credits })}
          </p>
          <Button size="sm" onClick={() => setUnlocking(true)}>
            {tSkill('unlock')}
          </Button>
          <UnlockDialog
            open={unlocking}
            onClose={() => setUnlocking(false)}
            path={`/v1/skills/${skillId}/unlock`}
            credits={data.access_credits}
            title={tSkill('unlock')}
            confirm={tSkill('unlockConfirm', {
              credits: data.access_credits,
              title: data.title,
            })}
            onUnlocked={() => {
              setUnlocking(false);
              // The params only arrive on a re-read, now that the viewer may
              // see them.
              refetch();
            }}
          />
        </>
      ) : variables.length === 0 ? (
        // Not a workflow, just a skill card. Saying so is more useful than an
        // empty form or a button that would 422.
        <p className="text-xs text-muted">{t('workflow.notAWorkflow')}</p>
      ) : run === null ? (
        <>
          {variables.map((variable) => (
            <QuestionField
              key={variable.id}
              question={variable}
              value={answers[variable.id]}
              requiredLabel={t('workflow.required')}
              choosePlaceholder={t('workflow.choose')}
              onChange={(value) => setAnswers((current) => ({ ...current, [variable.id]: value }))}
            />
          ))}
          <Button
            size="sm"
            disabled={busy || missingRequired}
            onClick={() =>
              void call(() =>
                startCanvasWorkflowRun(canvasId, {
                  skillId,
                  nodeId: node.id,
                  answers,
                }),
              )
            }
          >
            {t('workflow.run')}
          </Button>
        </>
      ) : (
        <div className="space-y-2">
          <p className="line-clamp-3 text-[11px] text-muted">{run.tasks[0]?.prompt}</p>
          {run.status === 'awaiting_confirm' ? (
            <>
              {/* The cost, before the tap that incurs it — same contract as
                  the Agent panel. */}
              <p className="text-xs text-muted">
                {t('agent.quote', { credits: run.quoted_credits })}
              </p>
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => void call(() => confirmRun(run.id))}
                >
                  {t('agent.confirm')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setRun(null)}>
                  {t('agent.discard')}
                </Button>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-between gap-2">
              {/* Progress lives in the workbench from here on — it is the
                  panel that already owns one job stream at a time. */}
              <span className="text-xs text-muted">{t(`agent.runStatus.${run.status}`)}</span>
              <Button size="sm" variant="ghost" onClick={() => setRun(null)}>
                {t('agent.newRun')}
              </Button>
            </div>
          )}
        </div>
      )}

      {error ? <p className="text-xs text-danger">{error}</p> : null}
    </div>
  );
}
