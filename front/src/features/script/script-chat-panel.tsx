'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { LiveThinking, ThinkingDisclosure } from '@/components/ai/thinking-disclosure';
import { SkillMentionMenu } from '@/components/skills/skill-mention-menu';
import { Button } from '@/components/ui/button';
import { IconArrowUp } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type { CreationSkillSummary } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import {
  computeMentionMenuStyle,
  detectMentionTrigger,
  filterMentionSkills,
  hasMentionToken,
  stripMentionToken,
} from '@/lib/skill-mention';

import type { ScriptTurnSummary } from './api';
import { ReferencedSkillChips } from './referenced-skill-chips';
import { streamingPreviewText } from './stream-preview';
import { MAX_REFERENCED_SKILLS, useSkillReferences } from './use-skill-references';

const MESSAGE_MAX_LENGTH = 2000;

interface MentionState {
  /** Index of the triggering `@` inside `message`. */
  start: number;
  query: string;
  activeIndex: number;
  style: React.CSSProperties;
}

/**
 * Left column: full conversation history (each turn as a user bubble plus
 * the assistant's change summary, the summary bubble clickable to view that
 * turn's full script on the right), a live "typing" preview while a turn is
 * in flight, and the composer — a single bordered box (chips, textarea,
 * round send button) in which typing `@` opens a caret-anchored menu to
 * reference a skill as a style guide, instead of the separate card rail
 * this used to be.
 */
export function ScriptChatPanel({
  turns,
  selectedTurnId,
  onSelectTurn,
  onSend,
  streaming,
  liveText,
  liveThinking,
  streamError,
}: {
  turns: ScriptTurnSummary[];
  selectedTurnId: string | null;
  onSelectTurn: (turnId: string) => void;
  onSend: (message: string, referencedSkillIds: string[]) => void;
  streaming: boolean;
  liveText: string;
  liveThinking: string;
  streamError: string | null;
}) {
  const t = useTranslations('scriptStudio');
  const { skills, requestReference, unlockDialog } = useSkillReferences();

  const [message, setMessage] = useState('');
  const [referencedSkillIds, setReferencedSkillIds] = useState<string[]>([]);
  const [mention, setMention] = useState<MentionState | null>(null);
  const wasStreaming = useRef(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const dismissedMentionStartRef = useRef<number | null>(null);

  // Pins the view to the newest content — a new turn, or another chunk of
  // the in-flight one — the same way a chat window is expected to track
  // what is currently being said rather than staying wherever it happened
  // to be scrolled.
  useEffect(() => {
    const node = listRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [turns.length, streaming, liveText, liveThinking]);

  // Keep the composer populated through a failed turn so the author can
  // hit retry (or edit and resend) instead of re-typing. Only clear after
  // a stream that started here actually completes without an error.
  useEffect(() => {
    if (streaming) {
      wasStreaming.current = true;
      return;
    }
    if (wasStreaming.current && !streamError) {
      setMessage('');
      setReferencedSkillIds([]);
      setMention(null);
    }
    wasStreaming.current = false;
  }, [streaming, streamError]);

  // Closes the mention menu on any click outside the composer — a click on
  // one of its own option buttons is *inside* `composerRef`, so this never
  // races with `selectMention`'s own click handling.
  useEffect(() => {
    if (!mention) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!composerRef.current?.contains(event.target as Node)) setMention(null);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [mention]);

  const referencedSkills = referencedSkillIds
    .map((id) => skills.find((skill) => skill.id === id))
    .filter((skill): skill is CreationSkillSummary => skill !== undefined);

  const filteredSkills = mention ? filterMentionSkills(skills, mention.query) : [];

  const refreshMention = (value: string, caret: number) => {
    const trigger = detectMentionTrigger(value, caret);
    if (!trigger) {
      dismissedMentionStartRef.current = null;
      setMention(null);
      return;
    }
    if (dismissedMentionStartRef.current === trigger.start) {
      setMention(null);
      return;
    }
    const textarea = textareaRef.current;
    const container = composerRef.current;
    if (!textarea || !container) return;
    setMention({
      start: trigger.start,
      query: trigger.query,
      activeIndex: 0,
      style: computeMentionMenuStyle(textarea, container, caret),
    });
  };

  const handleChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = event.target.value;
    setMessage(value);
    setReferencedSkillIds((ids) =>
      ids.filter((id) => {
        const skill = skills.find((item) => item.id === id);
        return !skill || hasMentionToken(value, skill.title);
      }),
    );
    refreshMention(value, event.target.selectionStart ?? value.length);
  };

  const selectMention = (skill: CreationSkillSummary) => {
    const current = mention;
    if (!current) return;
    const textarea = textareaRef.current;
    const caret = textarea?.selectionStart ?? current.start + current.query.length + 1;
    const alreadyReferenced = referencedSkillIds.includes(skill.id);

    const insert = () => {
      const before = message.slice(0, current.start);
      const after = message.slice(caret);
      const token = `@${skill.title} `;
      setMessage(before + token + after);
      if (!alreadyReferenced) {
        setReferencedSkillIds((ids) => (ids.length >= MAX_REFERENCED_SKILLS ? ids : [...ids, skill.id]));
      }
      dismissedMentionStartRef.current = null;
      setMention(null);

      // The textarea's `value` only reflects `message` after this render
      // commits, so the caret can only be placed on the next frame.
      const nextCaret = before.length + token.length;
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(nextCaret, nextCaret);
      });
    };

    if (alreadyReferenced) {
      insert();
      return;
    }
    if (referencedSkillIds.length >= MAX_REFERENCED_SKILLS) return;
    requestReference(skill, insert);
  };

  const removeReference = (skillId: string) => {
    const skill = skills.find((item) => item.id === skillId);
    setReferencedSkillIds((ids) => ids.filter((id) => id !== skillId));
    if (skill) setMessage((current) => stripMentionToken(current, skill.title));
  };

  const send = () => {
    const trimmed = message.trim();
    if (!trimmed || streaming) return;
    onSend(trimmed, referencedSkillIds);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setMention((current) =>
          current
            ? { ...current, activeIndex: Math.min(current.activeIndex + 1, Math.max(filteredSkills.length - 1, 0)) }
            : current,
        );
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setMention((current) =>
          current ? { ...current, activeIndex: Math.max(current.activeIndex - 1, 0) } : current,
        );
        return;
      }
      if ((event.key === 'Enter' || event.key === 'Tab') && filteredSkills.length > 0) {
        event.preventDefault();
        const target = filteredSkills[mention.activeIndex] ?? filteredSkills[0];
        if (target) selectMention(target);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        dismissedMentionStartRef.current = mention.start;
        setMention(null);
        return;
      }
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        setMention(null);
      }
    }

    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    send();
  };

  return (
    <div className="flex h-full flex-col gap-3">
      {/* `min-h-0` overrides the flex item's default `min-height: auto`,
          which would otherwise let this list's own content (an
          ever-growing turn history) force the flex column taller than its
          now-fixed parent instead of shrinking to fit and scrolling — see
          `script-editor.tsx`'s `WORKSPACE_HEIGHT`. */}
      <ul
        ref={listRef}
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto rounded-[var(--radius-sm)] border border-border bg-surface p-3"
      >
        {turns.length === 0 && !streaming ? (
          <p className="m-auto max-w-xs text-center text-xs text-muted">{t('chatEmpty')}</p>
        ) : null}

        {turns.map((turn) => (
          <li key={turn.id} className="flex flex-col gap-2">
            <div className="ml-auto flex max-w-[85%] flex-col items-end gap-1">
              {turn.turn_no === 1 ? (
                <p className="text-[11px] font-medium text-muted">{t('batchInitialIdea')}</p>
              ) : null}
              <div className="rounded-[var(--radius-sm)] bg-accent-soft px-3 py-2 text-sm text-text">
                <button
                  type="button"
                  disabled={streaming}
                  onClick={() => {
                    setMessage(turn.user_message.slice(0, MESSAGE_MAX_LENGTH));
                    requestAnimationFrame(() => textareaRef.current?.focus());
                  }}
                  className="block w-full text-left disabled:cursor-not-allowed"
                >
                  <p className="whitespace-pre-wrap break-words">{turn.user_message}</p>
                  <span className="mt-1.5 inline-block text-[11px] font-medium text-primary hover:underline">
                    {t('batchFillComposer')}
                  </span>
                </button>
              </div>
            </div>
            <button
              type="button"
              onClick={() => onSelectTurn(turn.id)}
              className={cn(
                'max-w-[85%] rounded-[var(--radius-sm)] border px-3 py-2 text-left text-sm transition-colors',
                turn.id === selectedTurnId
                  ? 'border-primary/40 bg-primary/10 text-text'
                  : 'border-border bg-surface-soft text-text hover:border-border-strong',
              )}
            >
              <p className="mb-1 text-[11px] font-medium text-muted">
                {t('turnLabel', { count: turn.turn_no })}
              </p>
              <p className="whitespace-pre-wrap break-words">{turn.summary}</p>
            </button>
            {/* A native `<details>`, keyed by `turn.id` — its open/closed
                state lives in the DOM node itself, so a turn the user
                expands to read never fights with a different turn that
                is still streaming in, with no extra state needed here. */}
            <ThinkingDisclosure thinking={turn.thinking} label={t('thinkingLabel')} />
          </li>
        ))}

        {streaming ? (
          <li className="flex max-w-[85%] flex-col gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2 text-sm text-muted">
            <div>
              <p className="mb-1 text-[11px] font-medium">{t('generating')}</p>
              <p className="whitespace-pre-wrap break-words">
                {streamingPreviewText(liveText, t('scriptGeneratingBody')) || '…'}
              </p>
            </div>
            <LiveThinking
              thinking={liveThinking}
              label={t('thinkingLive')}
              className="max-h-32 overflow-y-auto"
            />
          </li>
        ) : null}
      </ul>

      {streamError ? (
        <ErrorNotice
          title={streamError}
          action={
            <Button size="sm" disabled={streaming || message.trim().length === 0} onClick={send}>
              {t('retryTurn')}
            </Button>
          }
        />
      ) : null}

      <div
        ref={composerRef}
        className="relative rounded-[1.25rem] border border-border bg-surface-soft transition-colors focus-within:border-primary/40"
      >
        <ReferencedSkillChips skills={referencedSkills} onRemove={removeReference} />
        <textarea
          ref={textareaRef}
          aria-label={t('composerLabel')}
          placeholder={t('revisePlaceholder')}
          value={message}
          maxLength={MESSAGE_MAX_LENGTH}
          disabled={streaming}
          rows={2}
          className="block max-h-40 min-h-16 w-full resize-none bg-transparent px-3.5 py-2.5 pr-12 text-sm text-text outline-none placeholder:text-muted/70 disabled:cursor-not-allowed disabled:opacity-60"
          onChange={handleChange}
          onKeyDown={handleKeyDown}
        />
        <button
          type="button"
          aria-label={t('send')}
          title={t('send')}
          aria-busy={streaming || undefined}
          disabled={streaming || message.trim().length === 0}
          onClick={send}
          className="absolute bottom-2 right-2 grid size-9 shrink-0 place-items-center rounded-full bg-primary text-on-primary transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-primary/40 disabled:text-on-primary/70"
        >
          {streaming ? <Spinner className="text-on-primary" /> : <IconArrowUp className="size-4" />}
        </button>

        {mention ? (
          <SkillMentionMenu
            skills={filteredSkills}
            selectedIds={referencedSkillIds}
            activeIndex={mention.activeIndex}
            maxReached={referencedSkillIds.length >= MAX_REFERENCED_SKILLS}
            style={mention.style}
            label={t('referenceSkill')}
            emptyLabel={t('mentionEmpty')}
            priceLabel={(credits) => t('referenceSkillPrice', { credits })}
            onHoverIndex={(index) => setMention((current) => (current ? { ...current, activeIndex: index } : current))}
            onSelect={selectMention}
          />
        ) : null}
      </div>

      {unlockDialog}
    </div>
  );
}
