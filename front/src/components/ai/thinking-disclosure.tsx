'use client';

import { useEffect, useRef, useState } from 'react';

import { IconChevronDown } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

import { latestThinkingLine, thinkingParagraphs } from './thinking-paragraphs';

function ThinkingParagraphs({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {thinkingParagraphs(text).map((paragraph, index) => (
        <p key={index} className="whitespace-pre-wrap break-words">
          {paragraph}
        </p>
      ))}
    </div>
  );
}

/** Scrolls `ref`'s node to its own bottom whenever `deps` change and `active`
 * is true — shared by both components below so an expanded trace always
 * tracks its newest content instead of staying wherever it happened to be
 * scrolled. */
function useScrollToBottom(active: boolean, dep: string): React.RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!active) return;
    const node = ref.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [active, dep]);
  return ref;
}

/**
 * A collapsed-by-default disclosure for one *finished* reasoning trace. Never
 * rendered when there is nothing to show — a call with no thinking (an older
 * record, or a model/endpoint that never produced one) gets no toggle at all
 * rather than an empty one.
 *
 * Collapsed, this shows only the trace's last line as a one-line preview —
 * clicking the summary expands it into the full raw trace, split into
 * paragraphs (`ThinkingParagraphs`). The raw trace is free-form
 * model-internal prose — often English, mixed with the user's language,
 * sometimes missing the word spacing a streamed reasoning channel should
 * have carried — but it is shown as-is rather than run through a second LLM
 * call to clean it up: a summarization pass is one more place a failure can
 * hide, and the raw trace is still legible enough to be worth having on
 * demand.
 */
export function ThinkingDisclosure({
  thinking,
  label,
  defaultOpen,
  className,
}: {
  thinking: string;
  label: string;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [opened, setOpened] = useState(Boolean(defaultOpen));
  const scrollRef = useScrollToBottom(opened, thinking);
  if (!thinking) return null;
  const preview = latestThinkingLine(thinking);
  return (
    <details
      className={cn('group max-w-[85%]', className)}
      open={defaultOpen}
      onToggle={(event) => setOpened(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer select-none items-center gap-1 text-[11px] font-medium text-muted transition-colors hover:text-text">
        <IconChevronDown className="size-3 shrink-0 transition-transform group-open:rotate-180" />
        {label}
      </summary>
      {opened ? (
        <div
          ref={scrollRef}
          className="mt-1 max-h-40 overflow-y-auto rounded-[var(--radius-sm)] bg-surface-soft/60 px-2.5 py-1.5 text-left text-xs text-muted"
        >
          <ThinkingParagraphs text={thinking} />
        </div>
      ) : preview ? (
        <p className="mt-1 truncate text-left text-xs text-muted/80">{preview}</p>
      ) : null}
    </details>
  );
}

/**
 * Live status while a turn is still streaming. Collapsed by default — a
 * one-line ticker showing only the most recent line of the model's
 * reasoning trace, replaced as new lines arrive rather than accumulating a
 * growing block. Clicking the label expands it into the full trace received
 * so far (auto-scrolled to the bottom as more streams in), same raw-text
 * treatment as `ThinkingDisclosure` — no second LLM call summarizes it,
 * live or otherwise.
 */
export function LiveThinking({
  thinking,
  label,
  className,
}: {
  thinking: string;
  label: string;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const scrollRef = useScrollToBottom(expanded, thinking);
  if (!thinking) return null;
  const preview = latestThinkingLine(thinking);
  return (
    <div aria-live="polite" className="max-w-md text-left">
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="mb-1 flex items-center gap-1 text-[11px] font-medium text-muted transition-colors hover:text-text"
      >
        <IconChevronDown className={cn('size-3 shrink-0 transition-transform', expanded && 'rotate-180')} />
        {label}
      </button>
      {expanded ? (
        <div
          ref={scrollRef}
          className={cn('overflow-y-auto rounded-[var(--radius-sm)] bg-surface-soft/60 px-2.5 py-2', className)}
        >
          <ThinkingParagraphs text={thinking} />
        </div>
      ) : (
        <p className="truncate rounded-[var(--radius-sm)] bg-surface-soft/60 px-2.5 py-2 text-xs text-muted">
          {preview || label}
        </p>
      )}
    </div>
  );
}
