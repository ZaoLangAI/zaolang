import { Skeleton } from '@/components/ui/primitives';

export default function VideoAnalysisLoading() {
  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6" aria-busy="true">
      <Skeleton className="h-4 w-24" />
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-4 w-80" />
      </div>
      <Skeleton className="h-64 w-full rounded-[var(--radius-md)]" />
    </div>
  );
}
