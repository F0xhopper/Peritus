import Link from "next/link";
import {
  LayoutDashboardIcon,
  BrainCircuitIcon,
  CheckCircle2Icon,
  LoaderCircleIcon,
  XCircleIcon,
  PlusIcon,
} from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { StatTile } from "@/components/experts/stat-tile";
import { ExpertsTable } from "@/components/experts/experts-table";
import { BuildsChart } from "@/components/charts/builds-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MOCK_BUILDS_OVER_TIME, MOCK_EXPERTS } from "@/lib/mock-data";

export default function DashboardPage() {
  const total = MOCK_EXPERTS.length;
  const ready = MOCK_EXPERTS.filter((e) => e.status === "ready").length;
  const inProgress = MOCK_EXPERTS.filter(
    (e) => e.status === "building" || e.status === "queued",
  ).length;
  const failed = MOCK_EXPERTS.filter((e) => e.status === "failed").length;

  const recent = [...MOCK_EXPERTS]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 5);

  return (
    <>
      <PageHeader
        icon={LayoutDashboardIcon}
        title="Dashboard"
        action={
          <Button size="sm" nativeButton={false} render={<Link href="/experts/new" />}>
            <PlusIcon />
            New expert
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile icon={BrainCircuitIcon} label="Total experts" value={total} />
        <StatTile icon={CheckCircle2Icon} label="Ready" value={ready} />
        <StatTile
          icon={LoaderCircleIcon}
          label="In progress"
          value={inProgress}
        />
        <StatTile icon={XCircleIcon} label="Failed" value={failed} />
      </div>

      <Card className="rounded-lg">
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            Builds over time
          </CardTitle>
        </CardHeader>
        <CardContent>
          <BuildsChart data={MOCK_BUILDS_OVER_TIME} />
        </CardContent>
      </Card>

      <Card className="rounded-lg">
        <CardHeader className="flex items-center justify-between">
          <CardTitle className="text-sm text-muted-foreground">
            Recent experts
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            nativeButton={false}
            render={<Link href="/experts" />}
          >
            View all
          </Button>
        </CardHeader>
        <CardContent>
          <ExpertsTable experts={recent} />
        </CardContent>
      </Card>
    </>
  );
}
