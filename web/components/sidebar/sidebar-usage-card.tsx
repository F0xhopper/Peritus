import { Card } from "@/components/ui/card";
import type { ExpertSummary, ExpertTier } from "@/lib/api/types";

const TIERS: ExpertTier[] = ["lite", "standard", "pro"];
const BAR_WIDTH = 10;

function asciiBar(count: number, max: number) {
  const filled = max === 0 ? 0 : Math.round((count / max) * BAR_WIDTH);
  return "█".repeat(filled) + "░".repeat(BAR_WIDTH - filled);
}

export function SidebarUsageCard({ experts }: { experts: ExpertSummary[] }) {
  const counts = TIERS.map((tier) => ({
    tier,
    count: experts.filter((e) => e.tier === tier).length,
  }));
  const max = Math.max(1, ...counts.map((c) => c.count));

  return (
    <Card className="gap-2 rounded-lg p-3 group-data-[collapsible=icon]:hidden">
      <div className="text-xs tracking-wide text-muted-foreground uppercase">
        Experts by tier
      </div>
      <div className="flex flex-col gap-1 text-xs">
        {counts.map(({ tier, count }) => (
          <div key={tier} className="flex items-center gap-2">
            <span className="w-16 shrink-0 text-muted-foreground">
              {tier}
            </span>
            <span className="text-primary" aria-hidden>
              {asciiBar(count, max)}
            </span>
            <span className="tabular-nums">{count}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
