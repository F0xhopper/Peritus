import Link from "next/link";
import { SearchXIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";

// Six dashboard pages call notFound() for a slug or conversation id that either
// does not exist or belongs to someone else. The API deliberately returns 404
// rather than 403 for another user's rows, so this copy must not imply the thing
// exists and is merely off-limits — "no expert here" is both the honest reading
// and the one that leaks nothing.

export default function DashboardNotFound() {
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SearchXIcon />
        </EmptyMedia>
        <EmptyTitle>Not found</EmptyTitle>
        <EmptyDescription>
          This expert or conversation does not exist. It may have been deleted,
          or the link may be wrong.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button
          variant="outline"
          size="sm"
          nativeButton={false}
          render={<Link href="/experts" />}
        >
          Back to experts
        </Button>
      </EmptyContent>
    </Empty>
  );
}
