import { Badge } from "@/components/ui/badge";
import type { ExpertTier } from "@/lib/api/types";

export function TierBadge({ tier }: { tier: ExpertTier }) {
  return (
    <Badge variant="secondary" className="font-mono">
      [{tier}]
    </Badge>
  );
}
