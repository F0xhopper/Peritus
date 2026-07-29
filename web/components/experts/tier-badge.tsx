import type { ExpertTier } from "@/lib/api/types";

// The `[lite]` bracket notation was a terminal convention — a shell's way of
// marking a token. A printed page marks the same thing by setting it small and
// wide in capitals, so the brackets are gone and the tracking does the work.
//
// No box either: the same label voice already sets tier apart from running
// text, and a filled pill on top of that just re-draws a boundary the
// typography drew for free. Same voice the card footer already uses for tier.

export function TierBadge({ tier }: { tier: ExpertTier }) {
  return <span className="text-eyebrow text-muted-foreground">{tier}</span>;
}
