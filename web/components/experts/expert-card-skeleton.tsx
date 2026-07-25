import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/** Mirrors ExpertCard's block structure so the swap from skeleton to content
 * doesn't reflow the grid. */
export function ExpertCardSkeleton() {
  return (
    <Card className="h-full rounded-lg">
      <CardHeader className="flex items-start gap-3">
        <div className="flex flex-1 flex-col gap-1.5">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-3 w-24" />
        </div>
        <Skeleton className="size-4 shrink-0 rounded-sm" />
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-2/3" />
        </div>
        <div className="flex min-h-[2.875rem] flex-wrap content-start gap-1.5">
          <Skeleton className="h-5 w-28 rounded-4xl" />
          <Skeleton className="h-5 w-20 rounded-4xl" />
          <Skeleton className="h-5 w-24 rounded-4xl" />
          <Skeleton className="h-5 w-16 rounded-4xl" />
        </div>
      </CardContent>
      <CardFooter className="mt-auto justify-between">
        <Skeleton className="h-3 w-28" />
        <div className="flex items-center gap-2">
          <Skeleton className="h-3 w-12" />
          <Skeleton className="size-7 rounded-lg" />
        </div>
      </CardFooter>
    </Card>
  );
}

export function ExpertsGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
      {Array.from({ length: count }, (_, i) => (
        <ExpertCardSkeleton key={i} />
      ))}
    </div>
  );
}
