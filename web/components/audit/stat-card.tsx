import { Card } from "@/components/ui/card";

// A single labeled number, boxed like a stat tile. Shared across the audit
// views (coverage, disagreements) so the same summary-row shape doesn't get
// redefined per page.

export function StatCard({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <Card className="gap-2 rounded-lg p-4">
      <span className="text-eyebrow text-muted-foreground">{label}</span>
      <span className="font-display text-2xl font-medium tabular-nums lining-nums">
        {value}
      </span>
    </Card>
  );
}
