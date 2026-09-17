'use client';

import { useTranslations } from 'next-intl';
import { useRef } from 'react';

import { LiveThinking } from '@/components/ai/thinking-disclosure';
import {
  QuestionField,
  hasMissingRequiredAnswer,
  type QuestionAnswer,
} from '@/components/studio/question-field';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { IconClose, IconSparkle } from '@/components/ui/icons';
import { Badge, ErrorNotice, type BadgeTone } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type {
  PromptEnhancePayload,
  PromptEnhanceReferencedSkill,
  PromptEnhanceResult,
} from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { loadAnime, useIsomorphicLayoutEffect, useReducedMotion } from '@/lib/motion';
import { useOverlayTransition } from '@/lib/use-overlay-transition';

export type Direction = NonNullable<PromptEnhancePayload['direction']>;
type DetailLevel = PromptEnhanceResult['detail_level'];

export const DIRECTIONS: readonly Direction[] = [
  'more_specific',
  'more_concise',
  'stronger_camera',
  'stronger_lighting',
  'more_dramatic',
];

// Camera work is meaningless on a still, so that direction is hidden there
// rather than offered and then ignored by the agent.
export const VIDEO_ONLY_DIRECTIONS: readonly Direction[] = ['stronger_camera'];

const DETAIL_TONE: Record<DetailLevel, BadgeTone> = {
  sparse: 'danger',
  adequate: 'amber',
  detailed: 'success',
};

const ENTER_DURATION = 220;
const EXIT_DURATION = 160;
// A small downward grow rather than a rise from the viewport edge — this
// panel now unfolds in place under the "AI 润色" button, it doesn't arrive
// from off-screen.
const SHIFT_DISTANCE = 8;

/**
 * The "AI 润色" result panel, merged **inline** into `PromptComposer`'s
 * "说说你想怎么改" card, directly beneath the polish button.
 *
 * This used to be a page-level `fixed` bottom drawer (portalled to
 * `document.body`, with a drag-to-resize handle and a `ResizeObserver`
 * synced `body` padding). That fought the mobile submit bar for the same
 * `fixed bottom-0` real estate (`GenerationStudioShell`'s own bar) and read
 * as a separate popup rather than part of the composer. Now it is a plain
 * block in normal document flow, styled as a nested panel inside the
 * gradient card — it grows the card instead of covering the page, and the
 * page's own scroll is all that is ever needed to see the rest of it.
 *
 * Still not modal: no backdrop, no `Escape` handling, no focus trap — the
 * author can keep typing in the field above while this is open. The only
 * way to dismiss it is the close button in its header.
 */
export function PromptPolishPanel({
  open,
  onClose,
  pending,
  thinking = '',
  matchedSkills = [],
  error,
  suggestion,
  instruction,
  onInstructionChange,
  directions,
  onDirection,
  onRefine,
  onAutofill,
  answers,
  onAnswerChange,
  onAnswerSubmit,
}: {
  open: boolean;
  onClose: () => void;
  pending: boolean;
  thinking?: string;
  // Arrives on the stream's first frame, well before the polish itself, so
  // the wait shows what the coach is reading rather than only a spinner.
  matchedSkills?: PromptEnhanceReferencedSkill[];
  error: string | null;
  suggestion: PromptEnhanceResult | null;
  instruction: string;
  onInstructionChange: (value: string) => void;
  directions: readonly Direction[];
  onDirection: (direction: Direction) => void;
  onRefine: () => void;
  onAutofill: () => void;
  answers: Record<string, QuestionAnswer>;
  onAnswerChange: (id: string, value: QuestionAnswer) => void;
  onAnswerSubmit: () => void;
}) {
  const t = useTranslations('promptPolish');
  const tActions = useTranslations('actions');
  const panelRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  const animateExit = async (signal: AbortSignal) => {
    const { animate } = await loadAnime();
    if (signal.aborted) return;
    const panel = panelRef.current;
    if (!panel) return;
    await animate(panel, {
      opacity: [1, 0],
      translateY: [0, -SHIFT_DISTANCE],
      duration: EXIT_DURATION,
      ease: 'inQuad',
    }).then();
  };

  const render = useOverlayTransition(open, animateExit);

  useIsomorphicLayoutEffect(() => {
    if (!render || reduced) return;
    const panel = panelRef.current;
    if (!panel) return;
    panel.style.opacity = '0';
    loadAnime().then(({ animate }) => {
      animate(panel, {
        opacity: [0, 1],
        translateY: [-SHIFT_DISTANCE, 0],
        duration: ENTER_DURATION,
        ease: 'outExpo',
      });
    });
  }, [render, reduced]);

  if (!render) return null;

  const questions = suggestion?.questions ?? [];

  return (
    <div
      ref={panelRef}
      aria-live="polite"
      aria-busy={pending || undefined}
      className={cn(
        'mt-3 flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border/60 bg-surface-soft p-3',
        'outline-none',
      )}
    >
      <div className="flex items-center gap-2">
        <IconSparkle className="size-3.5 shrink-0 text-primary" aria-hidden="true" />
        <h3 className="min-w-0 flex-1 truncate text-xs font-semibold">{t('panelTitle')}</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label={tActions('close')}
          className={cn(
            'grid size-6 shrink-0 place-items-center rounded-[var(--radius-sm)] text-muted transition-colors',
            'hover:bg-surface-raised hover:text-text focus-visible:outline-2',
          )}
        >
          <IconClose className="size-3.5" />
        </button>
      </div>

      {error ? <ErrorNotice title={error} /> : null}

      {!error && pending && !suggestion ? (
        <div className="flex flex-col gap-3 py-2">
          <div className="flex items-center gap-2 text-sm text-muted">
            <Spinner className="size-4" />
            {t('panelPendingHint')}
          </div>
          {matchedSkills.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-muted">{t('referencedSkillsLabel')}</span>
              {matchedSkills.map((skill) => (
                <Badge key={skill.id} tone="neutral">
                  {skill.title}
                </Badge>
              ))}
            </div>
          ) : null}
          <LiveThinking thinking={thinking} label={t('thinkingLive')} className="max-h-32 overflow-y-auto" />
        </div>
      ) : null}

      {pending && suggestion && thinking ? (
        <LiveThinking thinking={thinking} label={t('thinkingLive')} className="max-h-24 overflow-y-auto" />
      ) : null}

      {suggestion ? (
        <div className="flex flex-col gap-3">
          <div className="max-h-40 overflow-y-auto rounded-[var(--radius-sm)] bg-surface-raised p-3">
            <p className="text-sm leading-relaxed text-text">{suggestion.prompt}</p>
          </div>

          {questions.length > 0 ? (
            <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-amber/40 bg-amber/5 p-3">
              <p className="text-xs leading-relaxed text-muted">{t('questionsHint')}</p>
              {questions.map((question) => (
                <QuestionField
                  key={question.id}
                  question={question}
                  value={answers[question.id]}
                  requiredLabel={t('questionRequired')}
                  choosePlaceholder={t('questionChoose')}
                  onChange={(value) => onAnswerChange(question.id, value)}
                />
              ))}
              <div className="flex justify-end">
                <Button
                  size="sm"
                  disabled={pending || hasMissingRequiredAnswer(questions, answers)}
                  loading={pending}
                  onClick={onAnswerSubmit}
                >
                  {t('questionsApply')}
                </Button>
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-0 flex-1">
              <TextInput
                label={t('instructionLabel')}
                placeholder={t('instructionPlaceholder')}
                value={instruction}
                maxLength={200}
                onChange={(event) => onInstructionChange(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== 'Enter' || !instruction.trim() || pending) return;
                  event.preventDefault();
                  onRefine();
                }}
              />
            </div>
            <Button
              size="sm"
              variant="secondary"
              disabled={instruction.trim().length === 0 || pending}
              loading={pending}
              onClick={onRefine}
            >
              {t('refineApply')}
            </Button>
            <Button size="sm" onClick={onAutofill}>
              {t('accept')}
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
            <Badge tone={DETAIL_TONE[suggestion.detail_level]}>
              {t(`detail.${suggestion.detail_level}`)}
            </Badge>
            <p className="min-w-0 flex-1 text-xs text-muted">{suggestion.feedback}</p>
          </div>

          {suggestion.dimensions && suggestion.dimensions.length > 0 ? (
            <ul className="flex flex-col gap-1.5">
              {suggestion.dimensions.map((dimension) => (
                <li key={dimension.key} className="flex items-start gap-2 text-xs">
                  <span
                    aria-hidden="true"
                    className={cn(
                      'mt-1.5 size-1.5 shrink-0 rounded-full',
                      dimension.status === 'missing' && 'bg-danger',
                      dimension.status === 'weak' && 'bg-amber',
                      dimension.status === 'ok' && 'bg-success',
                    )}
                  />
                  <span className="w-14 shrink-0 font-medium">{t(`dimension.${dimension.key}`)}</span>
                  <span className="sr-only">{t(`status.${dimension.status}`)}</span>
                  <span className="min-w-0 flex-1 leading-relaxed text-muted">{dimension.hint}</span>
                </li>
              ))}
            </ul>
          ) : null}

          {suggestion.additions && suggestion.additions.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-muted">{t('addedLabel')}</span>
              {suggestion.additions.map((addition) => (
                <Badge key={addition} tone="primary">
                  {addition}
                </Badge>
              ))}
            </div>
          ) : null}

          {suggestion.applied_format_skills && suggestion.applied_format_skills.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-muted">{t('appliedSkillsLabel')}</span>
              {suggestion.applied_format_skills.map((skill) => (
                <Badge key={skill.id} tone="amber">
                  {skill.title}
                </Badge>
              ))}
            </div>
          ) : null}

          {/* Separate row and a different tone from the amber one above on
              purpose: an applied format skill's rule text is verbatim in the
              rewritten prompt, a referenced drama skill only informed it. */}
          {suggestion.referenced_skills && suggestion.referenced_skills.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-muted">{t('referencedSkillsLabel')}</span>
              {suggestion.referenced_skills.map((skill) => (
                <Badge key={skill.id} tone="neutral">
                  {skill.title}
                </Badge>
              ))}
            </div>
          ) : null}

          <div className="flex flex-col gap-1.5 border-t border-border pt-2.5">
            <p className="text-[11px] text-muted">{t('refineLabel')}</p>
            <div className="flex flex-wrap gap-1.5">
              {directions.map((direction) => (
                <button
                  key={direction}
                  type="button"
                  disabled={pending}
                  onClick={() => onDirection(direction)}
                  className="rounded-md border border-border px-2 py-1 text-xs text-muted transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-50"
                >
                  {t(`direction.${direction}`)}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
