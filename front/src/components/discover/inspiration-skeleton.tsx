import { TILE_RATIO_SAMPLES } from '@/components/discover/inspiration-aspect';
import { Skeleton } from '@/components/ui/primitives';

/** The first page's size, so the fallback reserves the height it will need. */
const PLACEHOLDER_COUNT = 20;

export const INSPIRATION_COLUMNS = 'columns-2 gap-4 sm:columns-3 lg:columns-4 xl:columns-5';

/** Keeps a tile whole when the browser breaks the column after it. */
export const INSPIRATION_TILE = 'mb-4 break-inside-avoid';

/**
 * One placeholder tile, without its own wrapper so it can sit in either a `div`
 * or an `li` depending on the surrounding list semantics.
 */
export function InspirationTileSkeleton({ index }: { index: number }) {
  const ratio = TILE_RATIO_SAMPLES[index % TILE_RATIO_SAMPLES.length]!;
  return (
    <>
      <Skeleton className="w-full rounded-[var(--radius-md)]" style={{ aspectRatio: ratio }} />
      <Skeleton className="mt-2 h-4 w-[70%]" />
      <Skeleton className="mt-1.5 h-3 w-[45%]" />
    </>
  );
}

/**
 * Loading state for the inspiration wall.
 *
 * Same columns and the same rotation of cover shapes as the real content, so
 * the skeleton occupies roughly the height the works will and the page does not
 * jump when they land.
 */
export function InspirationSkeleton({ withHeading = true }: { withHeading?: boolean }) {
  return (
    <div aria-busy="true">
      {withHeading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-4 w-64" />
        </div>
      ) : null}

      <div className="mt-4 flex gap-2">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-7 w-20 rounded-full" />
        ))}
      </div>

      <div className={`mt-5 ${INSPIRATION_COLUMNS}`}>
        {Array.from({ length: PLACEHOLDER_COUNT }, (_, index) => (
          <div key={index} className={INSPIRATION_TILE}>
            <InspirationTileSkeleton index={index} />
          </div>
        ))}
      </div>
    </div>
  );
}
