import Link from "next/link";
import { UsersIcon, PlusIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ExpertsBrowser } from "@/components/experts/experts-browser";
import { ExpertsEmpty, sortExperts } from "@/components/experts/experts-grid";
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
      {/* "No experts at all" is decided here rather than in the browser: it is
          the only state where the search/filter shell has nothing to browse,
          and the empty screen's build button is the whole page. */}
      {experts.length === 0 ? (
        <ExpertsEmpty />
      ) : (
        <ExpertsBrowser experts={sortExperts(experts)} />
      )}
    </>
  );
}
