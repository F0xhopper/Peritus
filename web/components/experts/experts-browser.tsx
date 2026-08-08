"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { SearchIcon, SearchXIcon, XIcon } from "lucide-react";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Button } from "@/components/ui/button";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group";
import { ExpertsGrid } from "@/components/experts/experts-grid";
import { personaLabel } from "@/lib/persona";
import type { ExpertStatus, ExpertSummary } from "@/lib/api/types";

// The grid's client shell: find-an-expert controls, plus the poll that keeps
// building cards honest. The grid itself stays a dumb list — everything about
// *which* experts it shows lives here.
//
// Both controls earn their place by count, not by default. A search box over
// four cards is chrome pretending the page has a scale problem, so it appears
// only once the grid outgrows a glance; the status chips appear only when the
// grid actually holds more than one status, because "All / Ready" over an
// all-ready grid filters nothing.

/** Below this many experts the whole grid fits in a glance and search would
 * only add chrome. */
const SEARCH_MIN = 6;

/** Chip vocabulary, not the raw status enum: queued and building are the same
 * answer to "can I use it yet", so they share a chip. */
type StatusFilter = "all" | "ready" | "building" | "failed";

const FILTER_LABEL: Record<Exclude<StatusFilter, "all">, string> = {
  ready: "Ready",
  building: "Building",
  failed: "Failed",
};

function filterGroup(status: ExpertStatus): Exclude<StatusFilter, "all"> {
  return status === "queued" ? "building" : status;
}

export function ExpertsBrowser({ experts }: { experts: ExpertSummary[] }) {
  const router = useRouter();
  const [query, setQuery] = React.useState("");
  const [status, setStatus] = React.useState<StatusFilter>("all");

  // While anything is queued or building, the server snapshot this page
  // rendered from goes stale in seconds — the card's "N sources ingested"
  // line and the moment it flips to ready both live on the server. refresh()
  // re-renders the server tree in place without touching this component's
  // filter state. Stops itself the moment nothing is in flight, and skips
  // ticks while the tab is hidden.
  const anyInFlight = experts.some(
    (expert) => expert.status === "queued" || expert.status === "building",
  );
  React.useEffect(() => {
    if (!anyInFlight) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, 5000);
    return () => clearInterval(id);
  }, [anyInFlight, router]);

  const counts = React.useMemo(() => {
    const tally: Record<Exclude<StatusFilter, "all">, number> = {
      ready: 0,
      building: 0,
      failed: 0,
    };
    for (const expert of experts) tally[filterGroup(expert.status)] += 1;
    return tally;
  }, [experts]);

  const needle = query.trim().toLowerCase();
  const filtered = experts.filter((expert) => {
    if (status !== "all" && filterGroup(expert.status) !== status) return false;
    if (!needle) return true;
    return haystack(expert).includes(needle);
  });

  const showSearch = experts.length >= SEARCH_MIN;
  const presentGroups = (
    Object.keys(FILTER_LABEL) as Exclude<StatusFilter, "all">[]
  ).filter((group) => counts[group] > 0);
  const showChips = presentGroups.length > 1;

  const clear = () => {
    setQuery("");
    setStatus("all");
  };

  return (
    <div className="flex flex-col gap-4">
      {showSearch || showChips ? (
        <div className="flex flex-wrap items-center gap-2">
          {showSearch ? (
            <InputGroup className="w-full bg-card sm:max-w-xs">
              <InputGroupAddon>
                <SearchIcon />
              </InputGroupAddon>
              <InputGroupInput
                type="search"
                aria-label="Search experts"
                placeholder="Search by name, topic or concept…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              {query ? (
                <InputGroupAddon align="inline-end">
                  <InputGroupButton
                    size="icon-xs"
                    aria-label="Clear search"
                    onClick={() => setQuery("")}
                  >
                    <XIcon />
                  </InputGroupButton>
                </InputGroupAddon>
              ) : null}
            </InputGroup>
          ) : null}
          {showChips ? (
            <div className="flex items-center gap-1" role="group" aria-label="Filter by status">
              <FilterChip
                active={status === "all"}
                onClick={() => setStatus("all")}
              >
                All {experts.length}
              </FilterChip>
              {presentGroups.map((group) => (
                <FilterChip
                  key={group}
                  active={status === group}
                  onClick={() => setStatus(group)}
                >
                  {FILTER_LABEL[group]} {counts[group]}
                </FilterChip>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {filtered.length > 0 ? (
        <ExpertsGrid experts={filtered} />
      ) : (
        <NoMatches query={query.trim()} onClear={clear} />
      )}
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  // aria-pressed rather than tabs: the chips restrict one list in place, they
  // don't switch between panels.
  return (
    <Button
      variant={active ? "secondary" : "ghost"}
      size="sm"
      aria-pressed={active}
      onClick={onClick}
      className="tabular-nums"
    >
      {children}
    </Button>
  );
}

/** Filtered-to-nothing, which is the searcher's dead end, not the new user's —
 * so it offers a way back out of the filter instead of a build button. */
function NoMatches({ query, onClear }: { query: string; onClear: () => void }) {
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SearchXIcon />
        </EmptyMedia>
        <EmptyTitle>No experts match</EmptyTitle>
        <EmptyDescription>
          {query
            ? `Nothing here matches “${query}”. Try a different name, topic or concept.`
            : "Nothing here has that status."}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="outline" onClick={onClear}>
          Clear filters
        </Button>
      </EmptyContent>
    </Empty>
  );
}

/** Everything a card visibly says about an expert, matchable as one string —
 * including the rendered persona label, so searching "dr" behaves the way the
 * grid reads. */
function haystack(expert: ExpertSummary): string {
  return [
    personaLabel(expert.persona_name) ?? "",
    expert.topic,
    expert.name,
    ...expert.key_concepts,
  ]
    .join(" ")
    .toLowerCase();
}
