'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { hasMissingRequiredAnswer, QuestionField } from '@/components/studio/question-field';
import { Button } from '@/components/ui/button';
import { IconSparkle } from '@/components/ui/icons';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { ClarifyQuestion, ClarifyResult } from '@/lib/api/types';

export interface ClarifyApplyResult {
  /** The prompt textarea's new value: the original text plus a short summary
   * of what was answered, so the author can see and edit what was captured. */
  updatedPrompt: string;
  /** Structured answers keyed by question id, merged into the job's
   * `params.extra.clarify_answers` so downstream planning agents can use them
   * directly rather than re-parsing prose. */
  answers: Record<string, string | string[]>;
}

type Answer = string | string[];

/**
 * The shortform studio's "reverse-questioning" step: before submitting, asks
 * the copy agent whether the scene description is missing enough to be worth
 * asking about, then lets the author fill in the gaps.
 *
 * Kept separate from `PromptPolish` (which this sits next to) rather than
 * merged into it — `PromptPolish` is shared with the general creation studio,
 * and this capability is shortform-only.
 */
export function ClarifyPanel({
  prompt,
  onApply,
  className,
}: {
  prompt: string;
  onApply: (result: ClarifyApplyResult) => void;
  className?: string;
}) {
  const t = useTranslations('shortform');
  const tStates = useTranslations('states');
  const { requireAuth } = useSession();

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ClarifyResult | null>(null);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});

  const handleRequest = () =>
    requireAuth({
      label: t('clarifyButton'),
      run: async () => {
        setPending(true);
        setError(null);
        try {
          const body = await api.post<ClarifyResult>('/v1/shortform/prompt/clarify', {
            prompt: prompt.trim(),
          });
          setResult(body);
          setAnswers({});
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
        } finally {
          setPending(false);
        }
      },
    });

  const setAnswer = (id: string, value: Answer) =>
    setAnswers((current) => ({ ...current, [id]: value }));

  const missingRequired = hasMissingRequiredAnswer(result?.questions ?? [], answers);

  const dismiss = () => {
    setResult(null);
    setAnswers({});
  };

  const apply = () => {
    if (!result) return;
    const summary = summarize(result.questions ?? [], answers, t);
    const updatedPrompt = summary ? `${prompt.trim()}${prompt.trim() ? '，' : ''}${summary}` : prompt;
    onApply({ updatedPrompt, answers });
    dismiss();
  };

  return (
    <div className={className}>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          icon={<IconSparkle className="size-4" />}
          disabled={prompt.trim().length === 0 || pending}
          loading={pending}
          onClick={handleRequest}
        >
          {pending ? t('clarifyButtonPending') : t('clarifyButton')}
        </Button>
      </div>

      {error ? (
        <p role="alert" className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      ) : null}

      {result && !result.needs_clarification ? (
        <p className="mt-2 text-xs text-muted">{t('clarifyNoneNeeded')}</p>
      ) : null}

      {result && result.needs_clarification ? (
        <div className="mt-2.5 flex flex-col gap-3.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft p-3">
          <p className="text-xs text-muted">{t('clarifyIntro')}</p>
          {(result.questions ?? []).map((question) => (
            <QuestionField
              key={question.id}
              question={question}
              value={answers[question.id]}
              requiredLabel={t('clarifyRequired')}
              choosePlaceholder={t('clarifyChoosePlaceholder')}
              onChange={(value) => setAnswer(question.id, value)}
            />
          ))}
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={missingRequired} onClick={apply}>
              {t('clarifyApply')}
            </Button>
            <Button size="sm" variant="ghost" onClick={dismiss}>
              {t('clarifySkip')}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function summarize(
  questions: ClarifyQuestion[],
  answers: Record<string, Answer>,
  t: ReturnType<typeof useTranslations>,
): string {
  const parts: string[] = [];
  for (const question of questions) {
    const value = answers[question.id];
    if (value === undefined) continue;
    const options = question.options ?? [];
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      const labels = value.map(
        (item) => options.find((option) => option.value === item)?.label ?? item,
      );
      parts.push(labels.join('、'));
    } else if (value.trim()) {
      const label =
        question.kind === 'single_choice'
          ? (options.find((option) => option.value === value)?.label ?? value)
          : value.trim();
      parts.push(label);
    }
  }
  if (parts.length === 0) return '';
  return t('clarifySummaryPrefix', { detail: parts.join('，') });
}
