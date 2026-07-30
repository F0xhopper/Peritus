import { notFound } from "next/navigation";
import { HourglassIcon, NetworkIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { AuditNav } from "@/components/audit/audit-nav";
import { ExpertProfileHeader } from "@/components/experts/expert-profile-header";
import { KnowledgeGraph } from "@/components/experts/knowledge-graph";
import { Card, CardContent } from "@/components/ui/card";
import { getExpert, getExpertGraph } from "@/lib/api/data";
import { formatCompact } from "@/lib/format";

export default async function GraphPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const [expert, graph] = await Promise.all([
    getExpert(slug),
    getExpertGraph(slug),
  ]);

  if (!expert) {
    notFound();
  }

  return (
    <>
      <PageHeader icon={NetworkIcon} title="Knowledge graph" />

      <ExpertProfileHeader expert={expert} />

      <AuditNav slug={expert.name} active="graph" />

      {!graph?.computed ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <HourglassIcon className="size-5 text-muted-foreground" />
            <p className="font-medium">Not analysed yet</p>
            <p className="max-w-md text-sm text-pretty text-muted-foreground">
              This corpus is searchable, but its concept graph is still being
              extracted — the graph appears once that stage finishes.
            </p>
            {/* The profile header above counts nodes from the expert record,
                which can outlive the readiness flag this page gates on (a
                build interrupted after extraction, an older row). Saying so is
                better than showing a count and an empty page beside it. */}
            {expert.node_count > 0 ? (
              <p className="max-w-md text-xs text-pretty text-muted-foreground/70">
                {formatCompact(expert.node_count)} concepts are already stored
                for this expert but the extraction stage was never marked
                finished. Rebuilding will complete it.
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : graph.nodes.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <NetworkIcon className="size-5 text-muted-foreground" />
            <p className="font-medium">No concepts extracted</p>
            <p className="max-w-md text-sm text-pretty text-muted-foreground">
              The concept graph finished extraction with nothing in it.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <KnowledgeGraph nodes={graph.nodes} edges={graph.edges} />
        </Card>
      )}

      {graph?.computed && graph.nodes.length > 0 ? (
        <p className="max-w-measure text-xs text-pretty text-muted-foreground">
          {graph.truncated
            ? `Showing the ${formatCompact(graph.nodes.length)} most-connected of ${formatCompact(graph.total_nodes)} concepts — relationships reaching outside that cap are not drawn.`
            : `${formatCompact(graph.total_nodes)} concepts, ${formatCompact(graph.total_edges)} relationships.`}{" "}
          Click a concept to read its relationships, hover to trace them, drag
          to rearrange. Pinch or ⌘-scroll to zoom — a plain scroll moves the
          page.
        </p>
      ) : null}
    </>
  );
}
