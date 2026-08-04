import { Skeleton } from '@/components/ui/primitives';

/** Placeholder for the discover stage while the featured work resolves. */
export function DiscoverHeroSkeleton() {
  return (
    <section className="grid gap-6 lg:grid-cols-[minmax(0,1.72fr)_minmax(0,1fr)]" aria-busy="true">
      <Skeleton className="aspect-video w-full rounded-[var(--radius-lg)]" />
      <aside className="flex flex-col gap-3 rounded-[var(--radius-lg)] border border-border bg-surface p-5 lg:p-6">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-7 w-[80%]" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-[66%]" />
        <Skeleton className="mt-2 h-11 w-full" />
      </aside>
    </section>
  );
}
