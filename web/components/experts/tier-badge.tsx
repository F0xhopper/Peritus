import { Badge } from "@/components/ui/badge";
import type { ExpertTier } from "@/lib/api/types";

// The `[lite]` bracket notation was a terminal convention — a shell's way of
// marking a token. A printed page marks the same thing by setting it small and
// wide in capitals, so the brackets are gone and the tracking does the work.

export function TierBadge({ tier }: { tier: ExpertTier }) {
  return (
    <Badge
      variant="secondary"
      className="font-display text-[0.6875rem] tracking-[0.16em] uppercase"
    >
      {tier}
    </Badge>
  );
}
