'use client';

import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/cn';

/**
 * A span of text that becomes an inline `<textarea>` on double-click, and
 * commits back to plain text on blur (mouse-away) or Ctrl/Cmd+S — the one
 * inline-edit pattern for the whole app; nothing else in the codebase does
 * double-click/contentEditable-style editing, so this is deliberately a
 * plain controlled textarea rather than a rich editor (see
 * `components/learn/markdown-body-editor-impl.tsx` for that heavier need).
 *
 * `onCommit` only fires when the trimmed value actually changed — a blur or
 * Ctrl+S with nothing edited is a no-op, not a wasted save.
 */
export function EditableInlineText({
  value,
  onCommit,
  editable,
  className,
  textareaClassName,
  ariaLabel,
  title,
}: {
  value: string;
  onCommit: (next: string) => void;
  editable: boolean;
  className?: string;
  textareaClassName?: string;
  ariaLabel: string;
  title?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!editing) return;
    const node = textareaRef.current;
    if (!node) return;
    node.focus();
    node.select();
  }, [editing]);

  if (!editable) {
    return <span className={className}>{value}</span>;
  }

  if (!editing) {
    return (
      <span
        className={cn(
          className,
          'cursor-text rounded-sm outline-offset-2 transition-colors hover:bg-surface-soft/80',
        )}
        onDoubleClick={() => {
          // Always starts from the current prop value, not whatever the
          // draft was left at by a previous edit session — covers the case
          // where a prompt-based revision (or another save) landed a new
          // `value` while this field was last shown read-only.
          setDraft(value);
          setEditing(true);
        }}
        title={title}
      >
        {value}
      </span>
    );
  }

  const commit = () => {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed !== value) onCommit(trimmed);
  };

  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  return (
    <textarea
      ref={textareaRef}
      className={cn(
        // `text-base` (16px) is forced regardless of the surrounding
        // read-only text size — below that threshold, focusing this
        // textarea makes mobile Safari auto-zoom the whole viewport.
        'w-full resize-none rounded-[var(--radius-sm)] border border-border-strong bg-surface px-2 py-1 text-inherit text-base leading-relaxed outline-none transition-colors focus:border-primary/60',
        textareaClassName,
      )}
      value={draft}
      rows={Math.max(1, draft.split('\n').length)}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === 's') {
          event.preventDefault();
          commit();
        } else if (event.key === 'Escape') {
          event.preventDefault();
          cancel();
        }
      }}
      aria-label={ariaLabel}
    />
  );
}
