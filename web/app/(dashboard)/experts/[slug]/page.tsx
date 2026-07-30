import { notFound } from "next/navigation";
import { BotIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { AuditNav } from "@/components/audit/audit-nav";
import { ExpertProfileHeader } from "@/components/experts/expert-profile-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConceptList } from "@/components/experts/concept-list";
import { PersonaCard } from "@/components/experts/persona-card";
import { StatCard } from "@/components/audit/stat-card";
import { getExpert, getCoverage } from "@/lib/api/data";
import type { CoverageStrength } from "@/lib/api/types";

const STRENGTH: Record<
  CoverageStrength,
  { label: string; variant: "default" | "secondary" | "outline" | "destructive" }
> = {
  strong: { label: "Strong", variant: "default" },
  adequate: { label: "Adequate", variant: "secondary" },
  thin: { label: "Thin", variant: "outline" },
  absent: { label: "No sources", variant: "destructive" },
};

export default async function ExpertDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const [expert, coverage] = await Promise.all([
    getExpert(slug),
    getCoverage(slug),
  ]);

  if (!expert) {
    notFound();
  }

  const concepts = coverage && !coverage.key_concepts_unavailable_reason
    ? coverage.concepts
    : null;

  return (
    <>
      <PageHeader icon={BotIcon} title={expert.topic} />

      <ExpertProfileHeader expert={expert} />

      <AuditNav slug={expert.name} active="" />

      <PersonaCard name={expert.persona_name} bio={expert.persona_bio} />

      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            Concepts
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {concepts ? (
            <>
              {/* How well-supported each concept is, not just its name — the
                  strength label is the fact a reader actually wants when
                  scanning this list. */}
              <div className="grid gap-4 sm:grid-cols-4">
                <StatCard label="Strong" value={coverage!.summary.strong} />
                <StatCard label="Adequate" value={coverage!.summary.adequate} />
                <StatCard label="Thin" value={coverage!.summary.thin} />
                <StatCard label="No sources" value={coverage!.summary.absent} />
              </div>
              <ul className="flex flex-col divide-y divide-border">
                {concepts.map((c) => (
                  <li
                    key={c.concept}
                    className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0"
                  >
                    <span className="font-medium">{c.concept}</span>
                    <Badge
                      variant={STRENGTH[c.strength].variant}
                      className="font-normal"
                    >
                      {STRENGTH[c.strength].label}
                    </Badge>
                  </li>
                ))}
              </ul>
            </>
          ) : expert.key_concepts.length > 0 ? (
            <ConceptList
              concepts={expert.key_concepts}
              className="[&_li]:overflow-visible [&_li]:whitespace-normal"
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              No key concepts recorded yet.
            </p>
          )}
        </CardContent>
      </Card>
    </>
  );
}
