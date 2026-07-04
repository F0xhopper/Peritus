import { notFound } from "next/navigation";
import { BotIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { StatTile } from "@/components/experts/stat-tile";
import { StatusBadge } from "@/components/experts/status-badge";
import { TierBadge } from "@/components/experts/tier-badge";
import { ComingSoon } from "@/components/coming-soon";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LayersIcon, NetworkIcon, FileTextIcon } from "lucide-react";
import { MOCK_EXPERTS } from "@/lib/mock-data";

export default async function ExpertDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const expert = MOCK_EXPERTS.find((e) => e.name === slug);

  if (!expert) {
    notFound();
  }

  return (
    <>
      <PageHeader
        icon={BotIcon}
        title={expert.name}
        action={
          <div className="flex items-center gap-2">
            <StatusBadge status={expert.status} />
            <TierBadge tier={expert.tier} />
          </div>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile icon={FileTextIcon} label="Sources" value={expert.source_count} />
        <StatTile icon={LayersIcon} label="Chunks" value={expert.chunk_count} />
        <StatTile icon={NetworkIcon} label="Graph nodes" value={expert.node_count} />
      </div>

      <Card className="rounded-lg">
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            Persona
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {expert.persona_name ? (
            <>
              <div className="text-sm">
                <span className="font-medium">{expert.persona_name}</span>
                <span className="text-muted-foreground">
                  {" "}
                  — {expert.persona_style}
                </span>
              </div>
              <p className="text-sm text-muted-foreground">
                {expert.persona_bio}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {expert.key_concepts.map((concept) => (
                  <Badge key={concept} variant="outline" className="font-mono">
                    {concept}
                  </Badge>
                ))}
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Persona not generated yet — available once the build reaches
              &quot;ready&quot;.
            </p>
          )}
        </CardContent>
      </Card>

      <ComingSoon
        phase="phase 5"
        description="Chat, Sources, and Build log tabs land here once the dashboard shell and auth wiring are reviewed."
      />
    </>
  );
}
