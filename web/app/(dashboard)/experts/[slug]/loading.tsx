import { BotIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// Covers this segment and everything under it (build, chat, graph, sources) that
// does not define its own loading state. Each of those pages awaits getExpert()
// plus a second fetch, so without this the shell renders and the content region
// stays blank until both land.
//
// The header is drawn for real rather than skeletoned: the icon and the frame are
// identical on every one of those pages, so showing them immediately gives the
// navigation somewhere to land instead of a grey box that shifts.

export default function ExpertLoading() {
  return (
    <>
      <PageHeader icon={BotIcon} title="Loading…" />

      {/* Profile header */}
      <div className="flex items-start gap-4">
        <Skeleton className="size-12 shrink-0 rounded-full" />
        <div className="flex flex-1 flex-col gap-2">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-3 w-32" />
        </div>
      </div>

      {/* Section nav */}
      <div className="flex gap-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-7 w-20 rounded-lg" />
        ))}
      </div>

      <Card>
        <CardHeader>
          <Skeleton className="h-3.5 w-24" />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-3/4" />
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-20 rounded-lg" />
        ))}
      </div>
    </>
  );
}
