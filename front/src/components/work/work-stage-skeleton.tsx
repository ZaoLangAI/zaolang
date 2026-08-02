import { Skeleton } from '@/components/ui/primitives';

/** Shared loading shell for discover and work detail layouts. */
export function WorkStageSkeleton({ compactPanel = false }: { compactPanel?: boolean }) {
  return (
    <div
      className="mx-auto flex w-full max-w-[1440px] flex-col gap-8 px-4 py-6 sm:px-6"
      aria-busy="true"
    >
      <section className="grid gap-6 lg:grid-cols-[minmax(0,1.72fr)_minmax(0,1fr)]">
        <Skeleton className="aspect-video w-full rounded-[var(--radius-lg)]" />
        <aside className="rounded-[var(--radius-lg)] border border-border bg-surface p-5 lg:p-6">
          <div className="flex flex-col gap-3">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-7 w-[80%]" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-[66%]" />
            {compactPanel ? null : (
              <>
                <Skeleton className="mt-2 h-10 w-full" />
                <Skeleton className="h-24 w-full" />
              </>
            )}
          </div>
        </aside>
      </section>
      <section className="flex flex-col gap-4">
        <Skeleton className="h-6 w-40" />
        <div className="flex gap-4 overflow-hidden">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="aspect-video w-[19%] min-w-[140px] shrink-0" />
          ))}
        </div>
      </section>
    </div>
  );
}

export function StudioSkeleton() {
  return (
    <div
      className="mx-auto flex w-full max-w-[1440px] flex-col gap-5 px-4 py-6 sm:px-6"
      aria-busy="true"
    >
      <Skeleton className="h-4 w-28" />
      <Skeleton className="h-9 w-72" />
      <Skeleton className="h-4 w-full max-w-xl" />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Skeleton className="min-h-80 w-full rounded-[var(--radius-lg)]" />
        <Skeleton className="min-h-80 w-full rounded-[var(--radius-lg)]" />
      </div>
    </div>
  );
}

export function JobProgressSkeleton() {
  return (
    <div
      className="mx-auto flex w-full max-w-2xl flex-col gap-5 px-4 py-10 sm:px-6"
      aria-busy="true"
    >
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-3 w-full rounded-full" />
      <Skeleton className="h-40 w-full rounded-[var(--radius-lg)]" />
      <div className="flex gap-3">
        <Skeleton className="h-10 w-28" />
        <Skeleton className="h-10 w-28" />
      </div>
    </div>
  );
}
