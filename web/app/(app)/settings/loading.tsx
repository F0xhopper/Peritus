import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/** Account settings: Account rows, the theme control, then Credits and its price table. */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar titleWidth="w-16" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[560px] px-4 pt-5 pb-10 md:px-6">
          <Skeleton className="h-7 w-28" />
          <section className="mt-8">
            <Skeleton className="h-5 w-24" />
            <LabelledRows widths={['w-44', 'w-64', 'w-36']} />
          </section>
          <section className="mt-10">
            <Skeleton className="h-5 w-28" />
            <Skeleton className="mt-2 h-3.5 w-72 max-w-full" />
            <Skeleton className="mt-3 h-8 w-44 rounded-row" />
            <Skeleton className="mt-2 h-3 w-40" />
          </section>
          <section className="mt-10">
            <Skeleton className="h-5 w-20" />
            <LabelledRows widths={['w-72', 'w-8', 'w-20']} />
            <Skeleton className="mt-5 h-3 w-28" />
            <div className="mt-2 space-y-2">
              {Array.from({ length: 3 }, (_, i) => (
                <div key={i} className="flex justify-between">
                  <Skeleton className="h-3.5 w-20" />
                  <Skeleton className="h-3.5 w-14" />
                </div>
              ))}
            </div>
            <Skeleton className="mt-4 h-8 w-32 rounded-row" />
          </section>
        </div>
      </div>
    </>
  )
}

function LabelledRows({ widths }: { widths: string[] }) {
  return (
    <div className="mt-3 space-y-2">
      {widths.map((width, i) => (
        <div key={i} className="flex items-center gap-4">
          <Skeleton className="h-3.5 w-20" />
          <Skeleton className={`h-3.5 max-w-full ${width}`} />
        </div>
      ))}
    </div>
  )
}
