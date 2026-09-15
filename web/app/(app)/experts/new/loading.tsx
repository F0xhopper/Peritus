import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/** New expert: the 560px form — subject field, example topics, tier cards, Build. */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar titleWidth="w-24" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[560px] px-4 pt-4 pb-10 md:px-6">
          <Skeleton className="h-7 w-36" />
          <Skeleton className="mt-2 h-3.5 w-full" />
          <Skeleton className="mt-1.5 h-3.5 w-3/5" />
          <Skeleton className="mt-6 h-3 w-16" />
          <Skeleton className="mt-1.5 h-[60px] w-full rounded-row" />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {['w-56', 'w-52', 'w-60'].map((width) => (
              <Skeleton key={width} className={`h-6 ${width} max-w-full`} />
            ))}
          </div>
          <Skeleton className="mt-6 h-3 w-14" />
          <div className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-[104px] rounded-card" />
            ))}
          </div>
          <div className="mt-6 hidden items-center justify-between gap-4 md:flex">
            <Skeleton className="h-3 w-56" />
            <Skeleton className="h-10 w-28 rounded-row" />
          </div>
        </div>
      </div>
    </>
  )
}
