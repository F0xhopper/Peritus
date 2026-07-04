import { BrainCircuitIcon, CheckCircle2Icon, LoaderCircleIcon, XCircleIcon } from "lucide-react";
import { StatTile } from "@/components/experts/stat-tile";
import { ExpertsTable } from "@/components/experts/experts-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MOCK_EXPERTS } from "@/lib/mock-data";

export function ProductPreview() {
  const preview = MOCK_EXPERTS.slice(0, 4);

  return (
    <section className="mx-auto max-w-5xl px-4 py-20">
      <h2 className="text-lg font-medium">The dashboard</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        Every expert you build, one place to check status, sources, and
        quality.
      </p>
      <div className="mt-8 overflow-hidden rounded-lg bg-card ring-1 ring-foreground/10">
        <div className="flex items-center gap-1.5 border-b border-border/60 px-3 py-2">
          <span className="size-2 rounded-full bg-foreground/20" />
          <span className="size-2 rounded-full bg-foreground/35" />
          <span className="size-2 rounded-full bg-foreground/50" />
          <span className="ml-2 text-xs text-muted-foreground">
            peritus.app/dashboard
          </span>
        </div>
        <div
          className="pointer-events-none flex select-none flex-col gap-4 p-4 sm:p-6"
          aria-hidden
        >
          <div className="grid gap-4 sm:grid-cols-4">
            <StatTile icon={BrainCircuitIcon} label="Total experts" value={6} />
            <StatTile icon={CheckCircle2Icon} label="Ready" value={3} />
            <StatTile icon={LoaderCircleIcon} label="In progress" value={2} />
            <StatTile icon={XCircleIcon} label="Failed" value={1} />
          </div>
          <Card className="rounded-lg">
            <CardHeader>
              <CardTitle className="text-sm text-muted-foreground">
                Recent experts
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ExpertsTable experts={preview} />
            </CardContent>
          </Card>
        </div>
      </div>
    </section>
  );
}
