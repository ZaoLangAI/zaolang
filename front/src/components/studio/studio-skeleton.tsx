import { Skeleton } from '@/components/ui/primitives';

/** Layout-sized placeholder while a generation studio chunk is loading. */
export function StudioSkeleton() {
  return (
    <div
      className="flex flex-col gap-5 lg:grid lg:grid-cols-[184px_minmax(0,1fr)_340px]"
      aria-hidden
    >
      <div className="flex gap-3 overflow-hidden lg:flex-col">
        <Skeleton className="h-24 w-28 shrink-0 lg:w-full" />
        <Skeleton className="h-24 w-28 shrink-0 lg:w-full" />
        <Skeleton className="h-24 w-28 shrink-0 lg:w-full" />
      </div>
      <Skeleton className="aspect-video w-full" />
      <Skeleton className="hidden min-h-96 lg:block" />
    </div>
  );
}
