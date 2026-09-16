import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/**
 * A conversation: the transcript starts at the top of its column, as the real
 * one does — a question, the answer card under it with the persona line — and
 * the composer is pinned below.
 */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar crumb titleWidth="w-56" />
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="mx-auto flex w-full max-w-[720px] flex-1 flex-col gap-4 px-3 py-4 md:px-4">
          <Skeleton className="h-4 w-2/3" />
          <div className="rounded-card bg-panel p-3 md:p-4">
            <div className="mb-3 flex items-center gap-2">
              <Skeleton className="size-5 rounded-chip" />
              <Skeleton className="h-3.5 w-32" />
            </div>
            <div className="space-y-2">
              {['w-full', 'w-full', 'w-11/12', 'w-full', 'w-3/4', 'w-full', 'w-5/6'].map(
                (width, i) => (
                  <Skeleton key={i} className={`h-3.5 ${width}`} />
                )
              )}
            </div>
            <Skeleton className="mt-4 h-3 w-24" />
          </div>
        </div>
        <div className="shrink-0 px-3 pt-2 pb-3 md:px-4">
          <Skeleton className="mx-auto h-11 w-full max-w-[720px] rounded-card" />
        </div>
      </div>
    </>
  )
}
