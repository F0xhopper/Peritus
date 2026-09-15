import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/** The build log: the six-segment stage timeline, the counts line, and the log box. */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar crumb titleWidth="w-16" action />
      <div className="flex min-h-0 flex-1 flex-col gap-3 p-3 md:p-4">
        <div className="flex gap-1.5">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="min-w-0 flex-1">
              <Skeleton className="mb-1 h-3 w-12" />
              <Skeleton className="h-1 w-full rounded-full" />
            </div>
          ))}
        </div>
        <Skeleton className="h-3 w-40" />
        <div className="min-h-0 flex-1 space-y-1.5 rounded-card border border-border bg-panel p-3">
          {Array.from({ length: 12 }, (_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-3 w-3" />
              <Skeleton className="h-3 w-14" />
              <Skeleton className="h-3" style={{ width: `${62 - (i % 5) * 9}%` }} />
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
