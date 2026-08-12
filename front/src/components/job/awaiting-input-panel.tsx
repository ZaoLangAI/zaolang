'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { hasMissingRequiredAnswer, QuestionField, type QuestionAnswer } from '@/components/studio/question-field';
import { Button } from '@/components/ui/button';
import { IconSparkle } from '@/components/ui/icons';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { JobInputRequest } from '@/lib/api/types';

/**
 * The C-end half of the `copy_generate` HITL flow: while a job sits at
 * `awaiting_input`, this fetches the pending questions
 * (`GET /v1/generation-jobs/{id}/input-request`) and posts the answers
 * (`POST .../answer`) to resume it.
 *
 * Deliberately does not poll or update `job` itself — `JobProgress` already
 * holds a live SSE connection (`useJobStream`) that will carry the resumed
 * job's next events, so this only needs to stop asking once that connection
 * reports a different status, which happens by simply un-rendering: the
 * parent only renders this while `status === 'awaiting_input'`.
 */
export function AwaitingInputPanel({ jobId }: { jobId: string }) {
  const t = useTranslations('jobPage');

  const [request, setRequest] = useState<JobInputRequest | null>(null);
  const [answers, setAnswers] = useState<Record<string, QuestionAnswer>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .get<JobInputRequest>(`/v1/generation-jobs/${jobId}/input-request`)
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
  }, [jobId, t]);

  if (loading) return null;
  if (!request) return error ? <p className="text-xs text-danger">{error}</p> : null;

  const missingRequired = hasMissingRequiredAnswer(request.questions, answers);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/v1/generation-jobs/${jobId}/answer`, {
        answers: Object.entries(answers).map(([question_id, value]) => ({ question_id, value })),
      });
      setSubmitted(true);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('awaitingInputSubmitError'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-3.5 rounded-[var(--radius-md)] border border-primary/30 bg-primary/5 p-4">
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
