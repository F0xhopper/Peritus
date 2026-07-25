import Link from "next/link";
import { UsersIcon, PlusIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ExpertsGrid, sortExperts } from "@/components/experts/experts-grid";
import { FailedBuildsAlert } from "@/components/experts/failed-builds-alert";
import { Button } from "@/components/ui/button";
import { getExperts } from "@/lib/api/data";

export default async function ExpertsPage() {
  // Real data, not MOCK_EXPERTS: these cards carry a Chat action, and a Chat
  // button on a fictional expert would 404 on click.
  const experts = await getExperts();

  return (
    <>
      <PageHeader
        icon={UsersIcon}
        title="Experts"
        action={
          <Button size="sm" nativeButton={false} render={<Link href="/experts/new" />}>
            <PlusIcon />
            New expert
          </Button>
        }
      />
      <FailedBuildsAlert experts={experts} />
      <ExpertsGrid experts={sortExperts(experts)} />
    </>
  );
}
