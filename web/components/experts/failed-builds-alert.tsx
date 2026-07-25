import Link from "next/link";
import { TriangleAlertIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { ExpertSummary } from "@/lib/api/types";

// Conditional, never a permanent counter: a "0 failed" tile that reads zero
// most days trains people to stop looking at it. Sits above the grid on
// /experts, next to the experts it is about.

export function FailedBuildsAlert({ experts }: { experts: ExpertSummary[] }) {
  const failed = experts.filter((expert) => expert.status === "failed");
  if (failed.length === 0) return null;

  return (
    <Alert variant="destructive">
      <TriangleAlertIcon />
      <AlertTitle>
        {failed.length} {failed.length === 1 ? "build" : "builds"} failed
      </AlertTitle>
      <AlertDescription>
        {failed.map((expert, i) => (
          <span key={expert.id}>
            {i > 0 ? ", " : null}
            <Link href={`/experts/${expert.name}`}>{expert.name}</Link>
          </span>
        ))}
        {" — open "}
        {failed.length === 1 ? "it" : "them"} for the error and to rebuild.
      </AlertDescription>
    </Alert>
  );
}
