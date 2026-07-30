import Link from "next/link";
import { Button } from "@/components/ui/button";

// The three views read as one record, so they carry a shared nav rather than
// living as unrelated pages hung off the expert. Overview carries the
// persona, general stats, and concepts (with their coverage strength) — the
// things you read; Sources is the full audit trail — a table substantial
// enough to want the page to itself; Graph is reserved for the concept-graph
// visualization.

const TABS = [
  { segment: "", label: "Overview" },
  { segment: "sources", label: "Sources" },
  { segment: "graph", label: "Graph" },
] as const;

export function AuditNav({
  slug,
  active,
}: {
  slug: string;
  active: (typeof TABS)[number]["segment"];
}) {
  return (
    // These are separate server-rendered routes, not a client Tabs panel, so
    // the nav stays Link-based — but reads as the same rounded segmented
    // track as ui/tabs.tsx's TabsList, for the same "current view" affordance.
    <nav className="inline-flex w-fit flex-wrap items-center gap-1 rounded-lg bg-muted p-[3px]">
      {TABS.map(({ segment, label }) => (
        <Button
          key={segment}
          size="sm"
          variant="ghost"
          // Required whenever `render` supplies a non-<button> element — see
          // components/auth/google-sign-in.tsx for the same fix.
          nativeButton={false}
          className={
            segment === active
              ? "rounded-md bg-background text-foreground shadow-sm"
              : "rounded-md text-muted-foreground"
          }
          render={
            <Link href={`/experts/${slug}${segment ? `/${segment}` : ""}`} />
          }
        >
          {label}
        </Button>
      ))}
    </nav>
  );
}
