import { notFound } from "next/navigation";
import { FilterIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { AuditNav } from "@/components/audit/audit-nav";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StageCount, NotRecorded } from "@/components/audit/not-recorded";
import { MethodNote } from "@/components/audit/method-note";
import { getScreeningFlow } from "@/lib/api/data";
import type { AuditCount } from "@/lib/api/types";

// The funnel: identified → screened → retrieved → assessed.
//
// Two sources of truth that are deliberately not reconciled — the build event
// log (a record of one run, which may be absent) and the sources table (the
// corpus itself, authoritative). Where they disagree, both are shown, because
// silently picking one would hide exactly the thing a reviewer is checking.

const STAGES: { key: keyof ScreeningStages; label: string }[] = [
  { key: "identified", label: "Records identified" },
  { key: "screened_at_triage", label: "Screened at triage" },
  { key: "retrieved_full_text", label: "Retrieved in full" },
  { key: "assessed_at_validation", label: "Assessed for quality" },
];

type ScreeningStages = {
  identified: AuditCount;
  screened_at_triage: AuditCount;
  retrieved_full_text: AuditCount;
  assessed_at_validation: AuditCount;
};

export default async function ScreeningPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const flow = await getScreeningFlow(slug);

  if (!flow) notFound();

  const strategy = flow.search_strategy;

  return (
    <>
      <PageHeader icon={FilterIcon} title="Screening flow" />

      <AuditNav slug={slug} active="screening" />

      <MethodNote>{flow.method_statement}</MethodNote>

      <Card className="rounded-lg">
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            The funnel
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <ol className="flex flex-col gap-3">
            {STAGES.map(({ key, label }) => {
              const stage = flow.stages[key];
              return (
                <li key={key} className="flex flex-col gap-1">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="font-medium">{label}</span>
                    <span className="font-display text-lg">
                      <StageCount stage={stage} />
                    </span>
                  </div>
                  {stage.note ? (
                    <p className="text-xs text-pretty text-muted-foreground">
                      {stage.note}
                    </p>
                  ) : null}
                  {/* The build log and the corpus can legitimately disagree —
                      gap-fill sources are validated after the log's event. */}
                  {key === "assessed_at_validation" &&
                  typeof stage.reported_by_build_log === "number" &&
                  stage.reported_by_build_log !== stage.count ? (
                    <p className="text-xs text-muted-foreground">
                      Build log reported{" "}
                      <span className="tabular-nums">
                        {stage.reported_by_build_log}
                      </span>
                      . {String(stage.build_log_note ?? "")}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </CardContent>
      </Card>

      <Card className="rounded-lg">
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            How the search was run
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
            <div className="flex flex-col">
              <span className="text-eyebrow text-muted-foreground">
                Queries issued
              </span>
              <span className="font-display text-lg tabular-nums">
                {strategy.queries_issued ?? (
                  <NotRecorded reason="No retained build event log." />
                )}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-eyebrow text-muted-foreground">
                Query text
              </span>
              <span className="text-sm">
                <NotRecorded reason={strategy.query_text_unavailable_reason} />
              </span>
            </div>
          </div>

          {strategy.fetchers.length > 0 ? (
            <ul className="flex flex-col divide-y divide-border text-sm">
              {strategy.fetchers.map((f) => (
                <li
                  key={f.fetcher}
                  className="flex items-center justify-between gap-4 py-2 first:pt-0 last:pb-0"
                >
                  <span className={f.skipped ? "text-muted-foreground" : ""}>
                    {f.fetcher}
                    {f.skipped ? (
                      <span className="ml-2 text-xs italic">
                        skipped{f.skip_reason ? ` — ${f.skip_reason}` : ""}
                      </span>
                    ) : null}
                  </span>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {f.candidates_identified ?? 0} found
                    {f.queries_run != null
                      ? ` · ${f.queries_run} quer${f.queries_run === 1 ? "y" : "ies"}`
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          <MethodNote>{strategy.note}</MethodNote>
        </CardContent>
      </Card>
    </>
  );
}
