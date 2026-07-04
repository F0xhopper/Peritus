import { Badge } from "@/components/ui/badge";
import { StatusDot } from "@/components/experts/status-dot";
import type { ExpertStatus } from "@/lib/api/types";

export function StatusBadge({ status }: { status: ExpertStatus }) {
  return (
    <Badge variant="outline" className="gap-1.5 font-mono">
      <StatusDot status={status} />
      {status}
    </Badge>
  );
}
