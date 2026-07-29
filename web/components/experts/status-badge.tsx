import { StatusDot } from "@/components/experts/status-dot";
import type { ExpertStatus } from "@/lib/api/types";

// No box: a status is a fact about the expert, not a control, and setting it
// in the same small tracked caps as every other eyebrow label is what marks
// it as "label voice" — a border around it would be a second, redundant cue
// for the same thing the type already says.

export function StatusBadge({ status }: { status: ExpertStatus }) {
  return (
    <span className="text-eyebrow inline-flex items-center gap-1.5 text-muted-foreground">
      <StatusDot status={status} />
      {status}
    </span>
  );
}
