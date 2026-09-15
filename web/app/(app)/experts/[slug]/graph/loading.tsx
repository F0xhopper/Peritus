import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/**
 * The graph: a canvas, not a document. The floating search field and the node
 * limit control sit where the real ones do; the canvas itself is left as the
 * page ground, since a grey slab the size of the viewport reads as an error.
 */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar crumb titleWidth="w-12" />
      <div className="relative min-h-0 flex-1">
        <Skeleton className="absolute top-3 left-3 h-8 w-56 rounded-row" />
        <Skeleton className="absolute top-3 right-3 hidden h-8 w-52 rounded-row lg:block" />
        <Skeleton className="absolute bottom-3 left-3 h-3 w-48" />
      </div>
    </>
  )
}
