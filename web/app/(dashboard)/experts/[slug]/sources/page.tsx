import { notFound } from "next/navigation";
import { ScrollTextIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { AuditNav } from "@/components/audit/audit-nav";
import { ExpertProfileHeader } from "@/components/experts/expert-profile-header";
import { SourceManager } from "@/components/experts/source-manager";
import { getExpert, getExpertSources } from "@/lib/api/data";

// One list, one card: add-your-own and found-by-research sources both live
// in SourceManager now, so this page doesn't fetch or render a second,
// overlapping view of the same corpus.

export default async function SourcesPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const [expert, sources] = await Promise.all([
    getExpert(slug),
    getExpertSources(slug),
  ]);

  if (!expert) notFound();

  return (
    <>
      <PageHeader icon={ScrollTextIcon} title="Sources" />

      <ExpertProfileHeader expert={expert} />

      <AuditNav slug={slug} active="sources" />

      {/* Adding material is owner-only upstream, and a build rewrites the
          corpus underneath an ingest — so the panel disables itself rather
          than letting the user find out from a 409. */}
      <SourceManager
        slug={expert.name}
        sources={sources}
        buildInProgress={expert.status === "building" || expert.status === "queued"}
      />
    </>
  );
}
