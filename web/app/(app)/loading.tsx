import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/**
 * Home's skeleton — and the fallback for any `(app)` route without its own.
 *
 * Every route that looks different has its own `loading.tsx` beside it, because
 * a skeleton of the wrong page is worse than none: the layout jumps twice, once
 * into the wrong shape and once into the right one. This one mirrors Home at
 * its real measures: the `max-w-6xl` column, the composer, the stat tiles (two
 * unless a build is running; one summary line on a phone) and the expert card
 * grid.
 */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar titleWidth="w-12" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-6xl px-4 pt-5 pb-12 md:px-6">
          <Skeleton className="h-7 w-24" />
          <Skeleton className="mt-2 h-3.5 w-80 max-w-full" />
          <Skeleton className="mt-6 h-[88px] w-full rounded-card" />
          <Skeleton className="mt-3 h-3 w-40 md:hidden" />
          <div className="mt-6 hidden grid-cols-2 gap-2 md:grid">
            {Array.from({ length: 2 }, (_, i) => (
              <Skeleton key={i} className="h-[72px] rounded-card" />
            ))}
          </div>
          <Skeleton className="mt-6 h-3 w-16" />
          <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-[128px] rounded-card" />
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
