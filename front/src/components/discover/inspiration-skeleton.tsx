import { Skeleton } from '@/components/ui/primitives';

/** The first page's size, so the fallback reserves the height it will need. */
const PLACEHOLDER_COUNT = 20;

export const INSPIRATION_COLUMNS =
  'grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5';

/**
 * One placeholder tile, without its own wrapper so it can sit in either a `div`
 * or an `li` depending on the surrounding list semantics.
 */
export function InspirationTileSkeleton() {
  return (
    <>
      <Skeleton className="aspect-video w-full rounded-[var(--radius-md)]" />
      <Skeleton className="mt-2 h-4 w-[70%]" />
      <Skeleton className="mt-1.5 h-3 w-[45%]" />
    </>
  );
}

/**
 * Loading state for the inspiration wall.
 *
 * Same columns and the same 16:9 cover box as the real content, so the
 * skeleton occupies roughly the height the works will and the page does not
 * jump when they land.
 */
export function InspirationSkeleton({ withHeading = true }: { withHeading?: boolean }) {
  return (
    <div aria-busy="true">
      {withHeading ? (
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <Skeleton className="h-6 w-40" />
            <Skeleton className="mt-1 h-4 w-64" />
          </div>
          <div className="flex gap-4">
            {Array.from({ length: 3 }, (_, index) => (
              <Skeleton key={index} className="h-5 w-12" />
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex gap-2">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-7 w-20 rounded-full" />
        ))}
      </div>

      <div className={`mt-5 ${INSPIRATION_COLUMNS}`}>
        {Array.from({ length: PLACEHOLDER_COUNT }, (_, index) => (
          <div key={index}>
            <InspirationTileSkeleton />
          </div>
        ))}
      </div>
    </div>
  );
}
