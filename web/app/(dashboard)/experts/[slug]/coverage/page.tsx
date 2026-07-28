import { notFound } from "next/navigation";
import { TargetIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { AuditNav } from "@/components/audit/audit-nav";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MethodNote } from "@/components/audit/method-note";
import { getCoverage } from "@/lib/api/data";
import type { CoverageStrength } from "@/lib/api/types";

// Where the evidence base is weak. For a reviewer this is the most actionable
// page in the product: it is the difference between "here is what I found" and
// "here is what I found, and here is where it is thin".

const STRENGTH: Record<
  CoverageStrength,
  { label: string; variant: "default" | "secondary" | "outline" | "destructive" }
> = {
  strong: { label: "Strong", variant: "default" },
  adequate: { label: "Adequate", variant: "secondary" },
  thin: { label: "Thin", variant: "outline" },
  absent: { label: "No sources", variant: "destructive" },
};

export default async function CoveragePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const report = await getCoverage(slug);

  if (!report) notFound();

  const { summary, tagging } = report;

  return (
    <>
      <PageHeader icon={TargetIcon} title="Concept coverage" />

      <AuditNav slug={slug} active="coverage" />

      <MethodNote>{report.method_statement}</MethodNote>

      {report.key_concepts_unavailable_reason ? (
        <Card className="rounded-lg border-dashed">
          <CardContent className="py-8">
            <p className="mb-2 font-medium">Coverage cannot be computed</p>
            <MethodNote>{report.key_concepts_unavailable_reason}</MethodNote>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-4">
            <Stat label="Strong" value={summary.strong} />
            <Stat label="Adequate" value={summary.adequate} />
            <Stat label="Thin" value={summary.thin} />
            <Stat label="No sources" value={summary.absent} />
          </div>

          <Card className="rounded-lg">
            <CardHeader>
              <CardTitle className="text-sm text-muted-foreground">
                Per concept
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <ul className="flex flex-col divide-y divide-border">
                {report.concepts.map((c) => {
                  const strength = STRENGTH[c.strength];
                  return (
                    <li
                      key={c.concept}
                      className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0"
                    >
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <span className="font-medium">{c.concept}</span>
                        <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          {c.needed_gap_fill ? (
                            <span>
                              Re-searched after no source covered it
                            </span>
                          ) : null}
                          {c.on_plan === false ? (
                            <span className="italic">
                              tagged but not on the research plan
                            </span>
                          ) : null}
                        </span>
                      </div>
                      <Badge variant={strength.variant} className="font-normal">
                        {strength.label}
                      </Badge>
                    </li>
                  );
                })}
              </ul>
              <MethodNote>{report.classification_rule}</MethodNote>
            </CardContent>
          </Card>

          {tagging.accepted_untagged_legacy > 0 ||
          tagging.accepted_tagged_no_concepts > 0 ? (
            <Card className="rounded-lg border-dashed">
              <CardHeader>
                <CardTitle className="text-sm text-muted-foreground">
                  Sources not reflected above
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                <ul className="flex flex-wrap gap-x-6 gap-y-1 text-muted-foreground">
                  {tagging.accepted_untagged_legacy > 0 ? (
                    <li>
                      <span className="tabular-nums text-foreground">
                        {tagging.accepted_untagged_legacy}
                      </span>{" "}
                      predate concept tagging
                    </li>
                  ) : null}
                  {tagging.accepted_tagged_no_concepts > 0 ? (
                    <li>
                      <span className="tabular-nums text-foreground">
                        {tagging.accepted_tagged_no_concepts}
                      </span>{" "}
                      matched no key concept
                    </li>
                  ) : null}
                </ul>
                <MethodNote>{tagging.note}</MethodNote>
              </CardContent>
            </Card>
          ) : null}
        </>
      )}
    </>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card className="gap-2 rounded-lg p-4">
      <span className="text-eyebrow text-muted-foreground">{label}</span>
      <span className="font-display text-2xl font-medium tabular-nums lining-nums">
        {value}
      </span>
    </Card>
  );
}
