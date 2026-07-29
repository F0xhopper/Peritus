import Link from "next/link";
import { Button } from "@/components/ui/button";

// The four audit views read as one record, so they carry a shared nav rather
// than living as unrelated pages hung off the expert.

const TABS = [
  { segment: "", label: "Overview" },
  { segment: "sources", label: "Sources" },
  { segment: "discovery", label: "Discovery" },
  { segment: "coverage", label: "Coverage" },
  { segment: "contradictions", label: "Disagreements" },
] as const;

export function AuditNav({
  slug,
  active,
}: {
  slug: string;
  active: (typeof TABS)[number]["segment"];
}) {
  return (
    <nav className="flex flex-wrap items-center gap-1 border-b border-border pb-3">
      {TABS.map(({ segment, label }) => (
        <Button
          key={segment}
          size="sm"
          variant={segment === active ? "secondary" : "ghost"}
          // Required whenever `render` supplies a non-<button> element — see
          // components/auth/google-sign-in.tsx for the same fix.
          nativeButton={false}
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
