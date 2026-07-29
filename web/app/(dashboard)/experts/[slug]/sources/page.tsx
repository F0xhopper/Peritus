import { notFound } from "next/navigation";
import Link from "next/link";
import { ScrollTextIcon, CheckIcon, LayersIcon, XIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { AuditNav } from "@/components/audit/audit-nav";
import { StatTile } from "@/components/experts/stat-tile";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SourceTable } from "@/components/audit/source-table";
import { SearchProvenance } from "@/components/audit/search-provenance";
import { MethodNote } from "@/components/audit/method-note";
import { ExportMenu } from "@/components/audit/export-menu";
import { getCorpusReport } from "@/lib/api/data";
import type { SourceDecision, SourceSort } from "@/lib/api/types";

const DECISIONS: SourceDecision[] = ["all", "accepted", "rejected"];
const DECISION_LABELS: Record<SourceDecision, string> = {
  all: "All",
  accepted: "Kept",
  rejected: "Dropped",
};

function isDecision(v: string | undefined): v is SourceDecision {
  return v != null && (DECISIONS as string[]).includes(v);
}

export default async function SourcesPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ decision?: string; sort?: string }>;
}) {
  const { slug } = await params;
  const sp = await searchParams;
  const decision: SourceDecision = isDecision(sp.decision) ? sp.decision : "all";

  const report = await getCorpusReport(slug, {
    decision,
    sort: (sp.sort as SourceSort | undefined) ?? "decision",
    limit: 200,
  });

  if (!report) notFound();

  const { totals, thresholds, provenance } = report;

  return (
    <>
      <PageHeader
        icon={ScrollTextIcon}
        title="Sources"
        action={<ExportMenu slug={slug} decision={decision} />}
      />

      <AuditNav slug={slug} active="sources" />

      <MethodNote>{report.method_statement}</MethodNote>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile icon={LayersIcon} label="Considered" value={totals.considered} />
        <StatTile icon={CheckIcon} label="Kept" value={totals.accepted} />
        <StatTile icon={XIcon} label="Dropped" value={totals.rejected} />
      </div>

      {!provenance.complete ? (
        <Card className="rounded-lg border-dashed">
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              Incomplete provenance
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
              {Object.entries(provenance.missing)
                .filter(([, n]) => n > 0)
                .map(([field, n]) => (
                  <li key={field}>
                    <span className="tabular-nums text-foreground">{n}</span>{" "}
                    missing {field.replace(/_/g, " ")}
                  </li>
                ))}
            </ul>
            <MethodNote>{provenance.note}</MethodNote>
          </CardContent>
        </Card>
      ) : null}

      <SearchProvenance
        searches={report.by_search.searches}
        note={report.by_search.note}
      />

      <Card className="rounded-lg">
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <CardTitle className="text-sm text-muted-foreground">
            Every source considered
          </CardTitle>
          <div className="flex items-center gap-1">
            {DECISIONS.map((d) => (
              <Button
                key={d}
                size="sm"
                variant={d === decision ? "secondary" : "ghost"}
                nativeButton={false}
                render={
                  <Link
                    href={
                      d === "all"
                        ? `/experts/${slug}/sources`
                        : `/experts/${slug}/sources?decision=${d}`
                    }
                  />
                }
              >
                {DECISION_LABELS[d]}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <SourceTable
            sources={report.sources}
            qualityMin={thresholds.quality_min}
            relevanceMin={thresholds.relevance_min}
          />
          {report.page.has_more ? (
            <p className="text-xs text-muted-foreground">
              Showing {report.page.returned} of {report.page.total_matching}.
              Export for the complete list.
            </p>
          ) : null}
          <MethodNote>{thresholds.note}</MethodNote>
        </CardContent>
      </Card>
    </>
  );
}
