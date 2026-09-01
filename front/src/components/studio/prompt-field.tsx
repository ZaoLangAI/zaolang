'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { SkillMentionMenu } from '@/components/skills/skill-mention-menu';
import { PromptPolish, type PromptPolishContext } from '@/components/studio/prompt-polish';
import { TextArea } from '@/components/ui/field';
import type { CreationSkillSummary } from '@/lib/api/types';
import { STUDIO_PROMPT_MAX_LENGTH } from '@/lib/prompt-limits';
import {
  computeMentionMenuStyle,
  detectMentionTrigger,
  filterMentionSkills,
} from '@/lib/skill-mention';

export interface PromptSkillMention {
  skills: CreationSkillSummary[];
  selectedIds: string[];
  maxReached: boolean;
  onSelect: (skill: CreationSkillSummary) => void;
}

interface MentionState {
  start: number;
  query: string;
  activeIndex: number;
  style: React.CSSProperties;
}

/**
 * The prompt textarea + character counter + optional "AI 润色" button,
 * identical across image, video and audio. Audio omits `polishContext` —
 * there is nothing camera/lighting-shaped for the copy agent to critique.
 *
 * Image and video pass `skillMention` so typing `@` opens a caret-anchored
 * menu of free / already-purchased skills that apply to the current
 * operation. Selecting one strips the in-progress `@query` and calls
 * `onSelect` — it does not insert an `@Title` token into the generation
 * prompt.
 */
export function PromptField({
  prompt,
  onChange,
  polishContext,
  onPolishAccept,
  closePolishSignal,
  skillMention,
  maxLength = STUDIO_PROMPT_MAX_LENGTH,
}: {
  prompt: string;
  onChange: (value: string) => void;
  polishContext?: PromptPolishContext;
  onPolishAccept?: (prompt: string) => void;
  /** Forwarded to `PromptPolish` — see its own doc comment. */
  closePolishSignal?: number;
  skillMention?: PromptSkillMention;
  /** Defaults to `STUDIO_PROMPT_MAX_LENGTH`. */
  maxLength?: number;
}) {
  const t = useTranslations('remixPage');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dismissedMentionStartRef = useRef<number | null>(null);
  const [mention, setMention] = useState<MentionState | null>(null);

  const filteredSkills = mention
    ? filterMentionSkills(skillMention?.skills ?? [], mention.query)
    : [];

  useEffect(() => {
    if (!mention) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setMention(null);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [mention]);

  const refreshMention = (value: string, caret: number) => {
    if (!skillMention) {
      setMention(null);
      return;
    }
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
    const container = containerRef.current;
    if (!textarea || !container) return;
    setMention({
      start: trigger.start,
      query: trigger.query,
      activeIndex: 0,
      style: computeMentionMenuStyle(textarea, container, caret),
    });
  };

  const selectMention = (skill: CreationSkillSummary) => {
    const current = mention;
    if (!current || !skillMention) return;
    const textarea = textareaRef.current;
    const caret = textarea?.selectionStart ?? current.start + current.query.length + 1;
    const before = prompt.slice(0, current.start);
    const after = prompt.slice(caret);
    const next = `${before}${after}`;
    onChange(next);
    dismissedMentionStartRef.current = null;
    setMention(null);
    skillMention.onSelect(skill);
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(before.length, before.length);
    });
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!mention || !skillMention) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setMention((current) =>
        current
          ? {
              ...current,
              activeIndex: Math.min(current.activeIndex + 1, Math.max(filteredSkills.length - 1, 0)),
            }
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
  };

  return (
    <div ref={containerRef} className="relative">
      <TextArea
        ref={textareaRef}
        label={t('promptLabel')}
        placeholder={skillMention ? t('mentionPromptPlaceholder') : t('promptPlaceholder')}
        hint={skillMention ? t('mentionHint') : undefined}
        value={prompt}
        maxLength={maxLength}
        onChange={(event) => {
          onChange(event.target.value);
          refreshMention(event.target.value, event.target.selectionStart ?? event.target.value.length);
        }}
        onKeyDown={handleKeyDown}
      />
      <p className="tabular mt-1 text-right text-[11px] text-muted">
        {prompt.length}/{maxLength}
      </p>
      {polishContext && onPolishAccept ? (
        <PromptPolish
          className="mt-2"
          endpoint="/v1/generation/prompts/enhance"
          prompt={prompt}
          context={polishContext}
          onAccept={onPolishAccept}
          closeSignal={closePolishSignal}
        />
      ) : null}
      {mention && skillMention ? (
        <SkillMentionMenu
          skills={filteredSkills}
          selectedIds={skillMention.selectedIds}
          activeIndex={mention.activeIndex}
          maxReached={skillMention.maxReached}
          style={mention.style}
          label={t('mentionSkill')}
          emptyLabel={t('mentionEmpty')}
          onHoverIndex={(index) =>
            setMention((current) => (current ? { ...current, activeIndex: index } : current))
          }
          onSelect={selectMention}
        />
      ) : null}
    </div>
  );
}
