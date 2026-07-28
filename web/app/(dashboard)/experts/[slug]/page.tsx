import { notFound } from "next/navigation";
import { BotIcon, LayersIcon, NetworkIcon, FileTextIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { AuditNav } from "@/components/audit/audit-nav";
import { StatTile } from "@/components/experts/stat-tile";
import { StatusBadge } from "@/components/experts/status-badge";
import { TierBadge } from "@/components/experts/tier-badge";
import { ExpertMenu } from "@/components/experts/expert-menu";
import { ChatButton } from "@/components/chat/chat-button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConceptList } from "@/components/experts/concept-list";
import { getExpert } from "@/lib/api/data";

export default async function ExpertDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const expert = await getExpert(slug);

  if (!expert) {
    notFound();
  }

  return (
    <>
      <PageHeader
        icon={BotIcon}
        title={expert.topic}
        action={
          <div className="flex items-center gap-2">
            <StatusBadge status={expert.status} />
            <TierBadge tier={expert.tier} />
            <ChatButton slug={expert.name} status={expert.status} />
            {/* Deleting from here leaves nothing to render, so it hands the
                menu somewhere to land. */}
            <ExpertMenu
              slug={expert.name}
              topic={expert.topic}
              redirectTo="/experts"
            />
          </div>
        }
      />

      <AuditNav slug={expert.name} active="" />

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
              {/* Uncapped and unclipped here: this is the page you open to
                  read the whole list, so it wraps rather than truncating. */}
              <div className="mt-1 flex flex-col gap-2">
                <p className="text-eyebrow text-muted-foreground">
                  Key concepts
                </p>
                <ConceptList
                  concepts={expert.key_concepts}
                  className="[&_li]:overflow-visible [&_li]:whitespace-normal"
                />
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
    </>
  );
}
