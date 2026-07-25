import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatTile({
  icon: Icon,
  label,
  value,
  className,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  className?: string;
}) {
  return (
    <Card className={cn("gap-2 rounded-lg p-4", className)}>
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="size-3.5" />
        <span className="text-eyebrow">{label}</span>
      </div>
      {/* Tabular, so the figure holds the same width whatever the count is
          and the three tiles in a row stay optically aligned. */}
      <div className="font-display text-2xl font-medium tabular-nums lining-nums">
        {value}
      </div>
    </Card>
  );
}
