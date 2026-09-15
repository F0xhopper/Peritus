import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/** Expert settings: avatar, rebuild with its tier cards, and the danger zone. */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar crumb titleWidth="w-16" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[560px] px-4 pt-5 pb-10 md:px-6">
          <Skeleton className="h-7 w-28" />
          <Skeleton className="mt-2 h-3.5 w-32" />
          <section className="mt-8">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="mt-2 h-3.5 w-full" />
            <div className="mt-3 flex items-center gap-3">
              <Skeleton className="size-12 rounded-card" />
              <Skeleton className="h-3 w-48" />
            </div>
          </section>
          <section className="mt-10">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="mt-2 h-3.5 w-56" />
            <Skeleton className="mt-3 h-[104px] w-full rounded-card" />
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-[104px] rounded-card" />
              ))}
            </div>
          </section>
          <section className="mt-12 border-t border-border-soft pt-6">
            <Skeleton className="h-5 w-28" />
            <Skeleton className="mt-2 h-3.5 w-full" />
            <Skeleton className="mt-3 h-8 w-44 rounded-row" />
          </section>
        </div>
      </div>
    </>
  )
}
