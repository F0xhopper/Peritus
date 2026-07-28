import { notFound } from "next/navigation";
import { GitCompareArrowsIcon, HourglassIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { AuditNav } from "@/components/audit/audit-nav";
import { Card, CardContent } from "@/components/ui/card";
import { ContradictionCard } from "@/components/audit/contradiction-card";
import { MethodNote } from "@/components/audit/method-note";
import { getContradictions } from "@/lib/api/data";

export default async function ContradictionsPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const report = await getContradictions(slug, { limit: 25 });

  if (!report) notFound();

  return (
    <>
      <PageHeader icon={GitCompareArrowsIcon} title="Where sources disagree" />

      <AuditNav slug={slug} active="contradictions" />

      {/* The load-bearing branch. `computed: false` means the concept graph has
          not been extracted yet, so an empty list means "not looked for" — the
          one thing this page must never render as "none found". */}
      {!report.computed ? (
        <Card className="rounded-lg border-dashed">
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <HourglassIcon className="size-5 text-muted-foreground" />
            <p className="font-medium">Not analysed yet</p>
            <p className="max-w-md text-sm text-pretty text-muted-foreground">
              This corpus is searchable, but its concept graph is still being
              extracted. Disagreements between sources are found during that
              stage, so none have been looked for yet.
            </p>
            <p className="text-xs text-muted-foreground">
              Readiness: {report.readiness.replace(/_/g, " ")}
            </p>
            {report.unavailable_reason ? (
              <MethodNote>{report.unavailable_reason}</MethodNote>
            ) : null}
          </CardContent>
        </Card>
      ) : report.contradictions.length === 0 ? (
        <Card className="rounded-lg border-dashed">
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <p className="font-medium">No disagreements found</p>
            <p className="max-w-md text-sm text-pretty text-muted-foreground">
              The concept graph was extracted and no contradicting relationships
              were recorded between sources in this corpus. That is a statement
              about this corpus, not about the literature.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat
              label="Disagreements"
              value={report.summary?.contradictions ?? 0}
            />
            <Stat
              label="Concepts involved"
              value={report.summary?.concepts_involved ?? 0}
            />
            <Stat
              label="Of all relationships"
              value={
                report.summary?.share_of_relationships != null
                  ? `${(report.summary.share_of_relationships * 100).toFixed(1)}%`
                  : "—"
              }
            />
          </div>

          {report.note ? <MethodNote>{report.note}</MethodNote> : null}

          <div className="flex flex-col gap-4">
            {report.contradictions.map((item) => (
              <ContradictionCard key={item.edge_id} item={item} />
            ))}
          </div>

          {report.page.has_more ? (
            <p className="text-xs text-muted-foreground">
              Showing {report.page.returned} of {report.page.total_matching}.
            </p>
          ) : null}
        </>
      )}
    </>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="gap-2 rounded-lg p-4">
      <span className="text-eyebrow text-muted-foreground">{label}</span>
      <span className="font-display text-2xl font-medium tabular-nums lining-nums">
        {value}
      </span>
    </Card>
  );
}
