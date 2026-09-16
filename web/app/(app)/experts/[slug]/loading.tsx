import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/**
 * The Overview: the 720px document — the 48px avatar with the name and topic,
 * the properties block as label · value pairs, then the prose sections.
 */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar crumb titleWidth="w-16" action />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[720px] px-4 pt-5 pb-16 md:px-6">
          <div className="flex items-start gap-4">
            <Skeleton className="size-12 rounded-card" />
            <div className="min-w-0 flex-1">
              <Skeleton className="h-7 w-52" />
              <Skeleton className="mt-2 h-3.5 w-36" />
            </div>
          </div>
          <div className="mt-6 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5">
            {/* Six rows, which is what a ready expert has. Eight shifted
                *About* down by two rows the moment the real page arrived. */}
            {['w-40', 'w-56', 'w-16', 'w-20', 'w-36', 'w-16'].map((width, i) => (
              <div key={i} className="contents">
                <Skeleton className="ml-auto h-3.5 w-16" />
                <Skeleton className={`h-3.5 ${width}`} />
              </div>
            ))}
          </div>
          {[4, 3].map((lines, section) => (
            <section key={section} className="mt-8">
              <Skeleton className="h-5 w-32" />
              <div className="mt-3 space-y-2">
                {Array.from({ length: lines }, (_, i) => (
                  <Skeleton key={i} className={`h-3.5 ${i === lines - 1 ? 'w-2/3' : 'w-full'}`} />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </>
  )
}
