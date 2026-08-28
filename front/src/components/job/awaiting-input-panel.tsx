'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { hasMissingRequiredAnswer, QuestionField, type QuestionAnswer } from '@/components/studio/question-field';
import { Button } from '@/components/ui/button';
import { IconSparkle } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { JobInputRequest } from '@/lib/api/types';

type JobHttp = {
  get: <T>(path: string) => Promise<T>;
  post: <T>(path: string, body?: unknown) => Promise<T>;
};

/**
 * HITL follow-up form while a job sits at `awaiting_input`.
 *
 * C-end (`/v1/generation-jobs/{id}`) and admin (`/v1/admin/jobs/{id}`) share
 * the same question shapes; they only differ in which client and path prefix
 * they talk to. The parent un-renders this once SSE reports a different status.
 *
 * Every caller renders this with `key={jobId}`, so a different job is a fresh
 * mount rather than a prop change on the same instance — the `useState`
 * initializers are the reset, and the fetch effect never needs to zero out
 * the previous job's answers/error itself.
 */
export function AwaitingInputPanel({
  jobId,
  client = api,
  basePath = '/v1/generation-jobs',
  onSubmitted,
}: {
  jobId: string;
  client?: JobHttp;
  basePath?: string;
  onSubmitted?: () => void;
}) {
  const t = useTranslations('jobPage');

  const [request, setRequest] = useState<JobInputRequest | null>(null);
  const [answers, setAnswers] = useState<Record<string, QuestionAnswer>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    client
      .get<JobInputRequest>(`${basePath}/${jobId}/input-request`)
      .then((body) => {
        if (!active) return;
        setRequest(body);
        setAnswers({});
      })
      .catch((caught) => {
        if (!active) return;
        // 404 just means the job moved on between the SSE event and this
        // fetch (already answered elsewhere, or expired) — not an error.
        if (!(caught instanceof ApiError && caught.isNotFound)) {
          setError(caught instanceof ApiError ? caught.message : t('awaitingInputLoadError'));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [jobId, client, basePath, t]);

  useEffect(() => {
    if (!request) return;
    rootRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [request]);

  if (loading) {
    return (
      <div className="flex flex-col gap-3.5 rounded-[var(--radius-md)] border border-primary/30 bg-primary/5 p-4">
        <p className="flex items-center gap-2 text-sm font-medium text-text">
          <IconSparkle className="size-4 text-primary" />
          {t('awaitingInputTitle')}
        </p>
        <Spinner className="text-muted" label={t('awaitingInputLoading')} />
      </div>
    );
  }
  if (!request) return error ? <p className="text-xs text-danger">{error}</p> : null;

  const missingRequired = hasMissingRequiredAnswer(request.questions, answers);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await client.post(`${basePath}/${jobId}/answer`, {
        answers: Object.entries(answers).map(([question_id, value]) => ({ question_id, value })),
      });
      setSubmitted(true);
      onSubmitted?.();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('awaitingInputSubmitError'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      ref={rootRef}
      className="flex flex-col gap-3.5 rounded-[var(--radius-md)] border border-primary/30 bg-primary/5 p-4"
    >
      <p className="flex items-center gap-2 text-sm font-medium text-text">
        <IconSparkle className="size-4 text-primary" />
        {t('awaitingInputTitle')}
      </p>
      <p className="text-xs text-muted">{t('awaitingInputIntro')}</p>

      {request.questions.map((question) => (
        <QuestionField
          key={question.id}
          question={question}
          value={answers[question.id]}
          requiredLabel={t('awaitingInputRequired')}
          choosePlaceholder={t('awaitingInputChoosePlaceholder')}
          onChange={(value) =>
            setAnswers((current) => ({ ...current, [question.id]: value }))
          }
        />
      ))}

      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}

      <div>
        <Button
          size="sm"
          disabled={missingRequired || submitted}
          loading={submitting}
          onClick={() => void submit()}
        >
          {submitted ? t('awaitingInputSubmitted') : t('awaitingInputSubmit')}
        </Button>
      </div>
    </div>
  );
}
