import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/**
 * The Knowledge page: the toolbar, then the List's table — the view every width
 * below a fine-pointer laptop opens on, and the one whose shape is known before
 * the map is laid out.
 */
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
          {/* The real table's box: the same hairline, so the swap changes
              nothing but the contents. */}
          <div className="overflow-hidden rounded-card border border-border-soft bg-panel">
            <div className="flex h-10 items-center gap-6 border-b border-border-soft px-4">
              {['w-16', 'w-10', 'w-14'].map((width, i) => (
                <Skeleton key={i} className={`h-2.5 ${width} ${i === 0 ? 'mr-auto' : ''}`} />
              ))}
            </div>
            {Array.from({ length: 14 }, (_, i) => (
              <div
                key={i}
                className="flex h-(--table-row-h) items-center gap-6 border-b border-border-soft px-4 last:border-b-0"
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
