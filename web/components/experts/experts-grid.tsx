import Link from "next/link";
import { PlusIcon, SparklesIcon } from "lucide-react";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Button } from "@/components/ui/button";
import { ExpertCard } from "@/components/experts/expert-card";
import type { ExpertSummary } from "@/lib/api/types";

export function ExpertsGrid({ experts }: { experts: ExpertSummary[] }) {
  if (experts.length === 0) return <ExpertsEmpty />;

  // 3-up waits for 2xl. At xl the sidebar leaves ~990px, and a third column
  // squeezes the title to ~120px — and the title now shares that row with an
  // avatar, so a name truncates to a first name and an initial, which defeats
  // the point of leading with the person.
  return (
    <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
      {experts.map((expert) => (
        <ExpertCard key={expert.id} expert={expert} />
      ))}
    </div>
  );
}

export function ExpertsEmpty() {
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SparklesIcon />
        </EmptyMedia>
        <EmptyTitle>No experts yet</EmptyTitle>
        <EmptyDescription>
          An expert reads a topic&apos;s sources, builds a knowledge graph over
          them, and answers with citations. Building the first one takes a few
          minutes.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button nativeButton={false} render={<Link href="/experts/new" />}>
          <PlusIcon />
          Build your first expert
        </Button>
      </EmptyContent>
    </Empty>
  );
}

/** Newest first. Queued and building experts are also the newest ones, so
 * recency puts the experts you are waiting on at the top without needing a
 * separate status sort. */
export function sortExperts(experts: ExpertSummary[]): ExpertSummary[] {
  return [...experts].sort((a, b) => b.created_at.localeCompare(a.created_at));
}
