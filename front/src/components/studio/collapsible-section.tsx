'use client';

import { useState } from 'react';

import { IconChevronDown } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

/**
 * Shared chrome for a collapsible params-panel section — extracted from
 * `VideoGenerationStudio`'s original inline "更多设置" block once a second
 * collapsible ("参考与首尾帧") needed the exact same border/button/chevron
 * treatment.
 */
export function CollapsibleSection({
  label,
  icon,
  defaultOpen = false,
  children,
}: {
  label: string;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-[var(--radius-sm)] border border-border">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-sm font-medium"
      >
        <span className="flex items-center gap-2">
          {icon}
          {label}
        </span>
        <IconChevronDown
          className={cn('size-4 text-muted transition-transform', open && 'rotate-180')}
        />
      </button>
      {open ? <div className="flex flex-col gap-4 border-t border-border p-3">{children}</div> : null}
    </div>
  );
}
