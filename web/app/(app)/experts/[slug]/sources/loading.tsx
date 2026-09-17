import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/** The sources: the toolbar, then a full-width table at the table row height. */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar crumb titleWidth="w-16" action />
      <div className="scroll-col flex-1">
        <div className="space-y-3 p-3 md:p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Skeleton className="h-8 w-32 rounded-row" />
            <Skeleton className="ml-auto hidden h-3 w-20 sm:block" />
          </div>
          {/* No border: the real table is a borderless `bg-panel`, and the
              swap used to flash a rule away. */}
          <div className="overflow-hidden rounded-card bg-panel">
            <div className="flex h-9 items-center gap-6 border-b border-border px-2">
              {['w-16', 'w-10', 'w-14'].map((width, i) => (
                <Skeleton key={i} className={`h-2.5 ${width} ${i === 0 ? 'mr-auto' : ''}`} />
              ))}
            </div>
            {Array.from({ length: 14 }, (_, i) => (
              <div
                key={i}
                className="flex h-(--table-row-h) items-center gap-6 border-b border-border-soft px-2 last:border-b-0"
              >
                <Skeleton className="h-3 flex-1" style={{ maxWidth: `${46 - (i % 4) * 6}%` }} />
                <Skeleton className="ml-auto h-3 w-14" />
                <Skeleton className="h-3 w-8" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
