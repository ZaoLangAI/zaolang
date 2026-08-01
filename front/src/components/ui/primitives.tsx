import { cn } from '@/lib/cn';

export function Card({
  className,
  children,
  as: Tag = 'div',
}: {
  className?: string;
  children: React.ReactNode;
  as?: 'div' | 'section' | 'article' | 'li';
}) {
  return (
    <Tag
      className={cn(
        'rounded-[var(--radius-md)] border border-border bg-surface shadow-card',
        className,
      )}
    >
      {children}
    </Tag>
  );
}

type BadgeTone = 'neutral' | 'primary' | 'amber' | 'success' | 'danger';

const badgeTones: Record<BadgeTone, string> = {
  neutral: 'bg-surface-soft text-muted border-border',
  primary: 'bg-primary/12 text-primary border-primary/30',
  amber: 'bg-amber/12 text-amber border-amber/35',
  success: 'bg-success/12 text-success border-success/30',
  danger: 'bg-danger/12 text-danger border-danger/30',
};

export function Badge({
  tone = 'neutral',
  children,
  className,
  icon,
}: {
  tone?: BadgeTone;
  children: React.ReactNode;
  className?: string;
  icon?: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium',
        badgeTones[tone],
        className,
      )}
    >
      {icon ? (
        <span aria-hidden="true" className="inline-flex">
          {icon}
        </span>
      ) : null}
      {children}
    </span>
  );
}

/** Section heading with the design's amber eyebrow above a large title. */
export function PageHeading({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <p className="eyebrow mb-2">{eyebrow}</p> : null}
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-sm text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-3">{actions}</div> : null}
    </header>
  );
}

export function SectionHeading({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {description ? <p className="mt-1 text-xs text-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn('animate-pulse rounded-[var(--radius-sm)] bg-skeleton', className)}
    />
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[var(--radius-md)] border border-dashed border-border px-6 py-14 text-center">
      {icon ? (
        <span aria-hidden="true" className="text-muted">
          {icon}
        </span>
      ) : null}
      <p className="text-base font-medium">{title}</p>
      {description ? <p className="max-w-md text-sm text-muted">{description}</p> : null}
      {action}
    </div>
  );
}

/** Inline failure notice. `role="alert"` so a failed action is announced. */
export function ErrorNotice({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: React.ReactNode;
}) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-danger/40 bg-danger/8 px-4 py-3"
    >
      <div>
        <p className="text-sm font-medium text-danger">{title}</p>
        {detail ? <p className="mt-0.5 text-xs text-muted">{detail}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function StatTile({
  value,
  label,
  hint,
  tone,
  className,
}: {
  value: React.ReactNode;
  label: string;
  hint?: string;
  /** Colours the number when it is a figure that should not be non-zero. */
  tone?: 'danger' | 'amber' | 'success';
  className?: string;
}) {
  return (
    <div className={cn('px-5 py-4', className)}>
      <p
        className={cn(
          'tabular text-2xl font-semibold',
          tone === 'danger' && 'text-danger',
          tone === 'amber' && 'text-amber',
          tone === 'success' && 'text-success',
        )}
      >
        {value}
      </p>
      <p className="mt-1 text-xs text-muted">{label}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-muted/80">{hint}</p> : null}
    </div>
  );
}

/** Row of stats sharing one bordered surface, as in the profile and library. */
export function StatRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 divide-x divide-y divide-border overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface sm:grid-cols-3 lg:grid-cols-5 lg:divide-y-0">
      {children}
    </div>
  );
}
