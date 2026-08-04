import { DiscoverHeroSkeleton } from '@/components/discover/hero-skeleton';
import { InspirationSkeleton } from '@/components/discover/inspiration-skeleton';

export default function DiscoverLoading() {
  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-8 px-4 py-6 sm:px-6">
      <DiscoverHeroSkeleton />
      <InspirationSkeleton />
    </div>
  );
}
