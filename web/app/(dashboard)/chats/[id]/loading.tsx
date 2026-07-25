import { Skeleton } from "@/components/ui/skeleton";

export default function ChatLoading() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-border/60 pb-3">
        <Skeleton className="size-7 rounded-lg" />
        <div className="flex flex-1 flex-col gap-1.5">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 py-4">
        <div className="flex justify-end">
          <Skeleton className="h-9 w-56 rounded-lg" />
        </div>
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-4/6" />
        </div>
      </div>
      <div className="border-t border-border/60 pt-3">
        <div className="mx-auto w-full max-w-3xl">
          <Skeleton className="h-14 w-full rounded-lg" />
        </div>
      </div>
    </div>
  );
}
