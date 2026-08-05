'use client';

import { IconAlert, IconCheck, IconClock } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

export interface StepperItem {
  key: string;
  label: string;
  detail?: string;
  tone: 'success' | 'danger' | 'primary' | 'pending';
}

/**
 * Horizontal pipeline stepper: icon + connector per stage.
 *
 * Complements `Timeline`'s vertical replay of what happened with an at-a-glance
 * "how far along the declared pipeline is this" view — the two answer
 * different questions (chronology vs. structure) from the same underlying data.
 */
export function Stepper({ items }: { items: StepperItem[] }) {
  return (
    <ol className="flex flex-wrap items-start gap-x-1 gap-y-4">
      {items.map((item, index) => (
        <li key={item.key} className="flex items-start">
          <div className="flex flex-col items-center gap-1.5" style={{ width: 96 }}>
            <span
              aria-hidden="true"
              className={cn(
                'grid size-7 place-items-center rounded-full border-2 text-[11px] font-semibold',
                item.tone === 'success' && 'border-success bg-success/12 text-success',
                item.tone === 'danger' && 'border-danger bg-danger/12 text-danger',
                item.tone === 'primary' && 'border-primary bg-primary/12 text-primary',
                item.tone === 'pending' && 'border-border bg-surface-soft text-muted',
              )}
            >
              {item.tone === 'success' ? (
                <IconCheck className="size-3.5" />
              ) : item.tone === 'danger' ? (
                <IconAlert className="size-3.5" />
              ) : item.tone === 'primary' ? (
                <IconClock className="size-3.5" />
              ) : (
                index + 1
              )}
            </span>
            <p
              className={cn(
                'text-center text-xs leading-tight',
                item.tone === 'pending' ? 'text-muted' : 'text-text',
              )}
            >
              {item.label}
            </p>
            {item.detail ? (
              <p className="text-center text-[10px] leading-tight text-muted">{item.detail}</p>
            ) : null}
          </div>
          {index < items.length - 1 ? (
            <span
              aria-hidden="true"
              className={cn(
                'mt-3.5 h-0.5 w-6 shrink-0',
                item.tone === 'success' ? 'bg-success' : 'bg-border',
              )}
            />
          ) : null}
        </li>
      ))}
    </ol>
  );
}
