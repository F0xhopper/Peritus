import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/** All chats: groups headed by an expert, each a panel of rows. */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar titleWidth="w-12" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-3xl px-4 pt-4 pb-10 md:px-6">
          <Skeleton className="h-7 w-20" />
          <Skeleton className="mt-2 h-3.5 w-72 max-w-full" />
          <div className="mt-5 space-y-6">
            {[3, 1, 2].map((rows, group) => (
              <section key={group}>
                <div className="flex h-(--row-h) items-center gap-2">
                  <Skeleton className="size-5 rounded-chip" />
                  <Skeleton className="h-3.5 w-36" />
                </div>
                <div className="mt-2 space-y-0.5 rounded-card border border-border-soft bg-panel p-1">
                  {Array.from({ length: rows }, (_, i) => (
                    <div key={i} className="flex h-(--row-h) items-center gap-2 px-2">
                      <Skeleton className="h-3.5 flex-1" style={{ maxWidth: `${70 - i * 12}%` }} />
                      <Skeleton className="ml-auto h-3 w-24" />
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
