import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

/** Mirrors ExpertCard's block structure — avatar header, bio + concept wells,
 * info-row footer — so the swap from skeleton to content doesn't reflow the
 * grid. Dimensions echo the real card: a size-16 avatar, 5.25rem content
 * wells, four footer rows. */
export function ExpertCardSkeleton() {
  return (
    <Card className="h-full">
      <CardHeader className="grid-cols-[minmax(0,1fr)_auto]">
        <div className="flex min-w-0 items-center gap-3">
          <Skeleton className="size-16 shrink-0 rounded-full" />
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-24" />
          </div>
        </div>
        <Skeleton className="size-8 shrink-0 justify-self-end rounded-lg" />
      </CardHeader>

      <Separator />

      <CardContent className="flex flex-1 flex-col gap-3">
        <div className="flex min-h-[5.25rem] flex-col gap-1.5">
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-2/3" />
        </div>
        <div className="flex min-h-[5.25rem] flex-col gap-1.5">
          <Skeleton className="h-3.5 w-40" />
          <Skeleton className="h-3.5 w-32" />
          <Skeleton className="h-3.5 w-36" />
        </div>
      </CardContent>

      <Separator />

      <CardContent className="flex flex-col gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="flex items-center justify-between">
            <Skeleton className="h-3.5 w-20" />
            <Skeleton className="h-3.5 w-12" />
          </div>
        ))}
      </CardContent>
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
