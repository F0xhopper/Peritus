import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/** Admin: the grant form — four labelled fields and a button. */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar titleWidth="w-14" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[560px] px-4 pt-5 pb-10 md:px-6">
          <Skeleton className="h-7 w-24" />
          <Skeleton className="mt-2 h-3.5 w-full" />
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="mt-5">
              <Skeleton className="h-3 w-32" />
              <Skeleton className="mt-1.5 h-9 w-full rounded-row" />
            </div>
          ))}
          <Skeleton className="mt-6 h-9 w-28 rounded-row" />
        </div>
      </div>
    </>
  )
}
