import { Skeleton } from '@/components/ui/primitives';

export default function CharactersLoading() {
  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6" aria-busy="true">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-4 w-80" />
      </div>
      <div className="flex justify-end">
        <Skeleton className="h-9 w-32" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-52 w-full rounded-[var(--radius-md)]" />
        ))}
      </div>
    </div>
  );
}
