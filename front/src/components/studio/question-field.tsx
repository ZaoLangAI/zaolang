'use client';

import { OptionGroup } from '@/components/studio/option-group';
import { MultiSelect, TextInput } from '@/components/ui/field';

export type QuestionAnswer = string | string[];

/**
 * The three question shapes a copy agent's follow-up can take, shared by
 * `ClarifyQuestionResponse` (pre-submission, `app/domain/shortform/clarify.py`)
 * and `JobInputQuestionView` (mid-workflow, `app/domain/jobs/input_requests.py`)
 * — same fields, two different backend callers.
 */
export interface QuestionFieldQuestion {
  id: string;
  kind: 'single_choice' | 'multi_choice' | 'free_text';
  prompt: string;
  options?: Array<{ value: string; label: string }>;
  required?: boolean;
}

/**
 * One follow-up question rendered as whichever control its `kind` calls for.
 *
 * Pulled out of `shortform/clarify-panel.tsx` so the awaiting-input panel on
 * the job page (`job/awaiting-input-panel.tsx`) renders the exact same
 * single/multi/free-text controls rather than a second, driftable copy — the
 * two only differ in *when* the question is asked (before submission vs. a
 * suspended job), never in how it looks.
 */
export function QuestionField({
  question,
  value,
  requiredLabel,
  choosePlaceholder,
  onChange,
}: {
  question: QuestionFieldQuestion;
  value: QuestionAnswer | undefined;
  /** Appended to the label for a required question, e.g. "（必填）". */
  requiredLabel: string;
  /** Placeholder for the multi-choice control. */
  choosePlaceholder: string;
  onChange: (value: QuestionAnswer) => void;
}) {
  const label = question.required ? `${question.prompt}（${requiredLabel}）` : question.prompt;
  const options = question.options ?? [];

  if (question.kind === 'single_choice') {
    return (
      <OptionGroup
        label={label}
        value={typeof value === 'string' ? value : ''}
        onChange={onChange}
        columns={2}
        options={options.map((option) => ({ value: option.value, label: option.label }))}
      />
    );
  }

  if (question.kind === 'multi_choice') {
    return (
      <MultiSelect
        label={label}
        value={Array.isArray(value) ? value : []}
        onChange={onChange}
        options={options}
        placeholder={choosePlaceholder}
      />
    );
  }

  return (
    <TextInput
      label={label}
      value={typeof value === 'string' ? value : ''}
      maxLength={200}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

/** A required question with no legal answer yet — shared disable condition
 * for both panels' submit button. */
export function hasMissingRequiredAnswer(
  questions: QuestionFieldQuestion[],
  answers: Record<string, QuestionAnswer>,
): boolean {
  return questions.some((question) => {
    if (!question.required) return false;
    const value = answers[question.id];
    return value === undefined || (Array.isArray(value) ? value.length === 0 : value.trim() === '');
  });
}
