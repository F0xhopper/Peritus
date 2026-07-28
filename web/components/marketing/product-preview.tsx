import { ScrollTextIcon } from "lucide-react";
import { SectionHeading } from "@/components/marketing/section-heading";

// The build log, not the expert shelf. The shelf is the outcome; the log is the
// product — it is the only place a screening decision is visible today, and it
// is what the positioning is actually about.
//
// Every line below uses the exact format the real log emits (see the reducer in
// components/experts/build-progress.tsx): stage lines, `Triaged N candidates →
// M ranked (budget B).`, and `Kept:` / `Dropped: <title> (Q:x.x R:y.y) —
// <reason>`. Newest first, because the live log reverses. The titles and drop
// reasons are illustrative; the shapes are not.
const LOG = [
  "Coverage gaps: dose-response threshold",
  "Validation done — 24 kept, 17 dropped.",
  "Dropped: Ten things we learned about fasting (Q:3.0 R:6.5) — secondary summary, no primary data",
  "Kept: WHO technical report on intermittent fasting (Q:8.5 R:9.0)",
  "Dropped: r/nutrition thread on 16:8 protocols (Q:2.5 R:7.0) — anecdote, no methodology",
  "Kept: Age-specific effects of intermittent fasting (Q:8.0 R:8.5)",
  "Snowball search added 4 sources.",
  "Triaged 61 candidates → 60 ranked (budget 60).",
  "web: 9 candidates from 3 queries.",
  "pdf: 6 candidates from 2 queries.",
  "Research plan ready — 7 target concepts.",
  "Discovering across 9 fetchers.",
];

export function ProductPreview() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-20">
      <SectionHeading eyebrow="The ledger" title="Every decision, as it happens">
        The build streams each accept and reject while it runs, with the scores
        behind it and the reason for every drop. The same record — plus the
        validator model, the rubric version and the search each source came
        from — is stored against the expert.
      </SectionHeading>
      <div className="mt-10 overflow-hidden rounded-lg bg-card ring-1 ring-border">
        <div className="flex items-center gap-1.5 border-b border-border/60 px-3 py-2">
          <span className="size-2 rounded-full bg-foreground/20" />
          <span className="size-2 rounded-full bg-foreground/35" />
          <span className="size-2 rounded-full bg-foreground/50" />
          <span className="ml-2 font-mono text-xs text-muted-foreground">
            peritus.app/experts/intermittent-fasting/build
          </span>
        </div>
        {/* `inert` rather than aria-hidden: a focusable element inside an
            aria-hidden subtree is reachable by keyboard while invisible to a
            screen reader. inert removes both. */}
        <div className="flex select-none flex-col gap-4 p-4 sm:p-6" inert>
          {/* Mirrors <PageHeader> rather than reusing it: this is a picture of
              the app, and it must not inherit its behaviour inside an inert
              subtree. */}
          <div className="flex items-center justify-between gap-4 border-b border-border pb-3">
            <div className="flex items-center gap-2.5 text-muted-foreground">
              <ScrollTextIcon className="size-3.5" />
              <span className="font-display text-sm font-semibold tracking-[0.18em] text-foreground uppercase">
                Build log
              </span>
            </div>
            <span className="font-mono text-xs text-muted-foreground">
              stage 2 / validate
            </span>
          </div>
          {/* Same treatment as the live log: monospace, small, quiet — a
              transcript rather than a dashboard. */}
          <ul className="flex flex-col gap-1 overflow-x-auto font-mono text-xs whitespace-pre text-muted-foreground">
            {LOG.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
