import Link from "next/link";
import { TriangleAlertIcon } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { StatusDot } from "@/components/experts/status-dot";
import { TierBadge } from "@/components/experts/tier-badge";
import { ConceptChips } from "@/components/experts/concept-chips";
import { ChatButton } from "@/components/chat/chat-button";
import { formatCompact, formatQuality } from "@/lib/format";
import type { ExpertSummary } from "@/lib/api/types";

// Replaces the experts table. The table could only show `topic` plus build
// telemetry, which is identically shaped for every expert — the fields that
// actually tell two experts apart (persona, bio, key concepts) don't fit in a
// cell.
//
// The card leads with `topic`, not `name`: `name` is the URL slug
// ("stoic-philosophy"), and leading with a kebab-case identifier buries the
// readable phrase directly beneath it. The slug still reaches the reader as
// the subtitle whenever there's no persona to put there.

export function ExpertCard({ expert }: { expert: ExpertSummary }) {
  return (
    <Card className="relative h-full rounded-lg transition-colors hover:bg-muted/20">
      <CardHeader className="flex items-start gap-3">
        <Monogram expert={expert} />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {/* CardTitle is a plain block in this style, so the row is built
              here — an inline <a> has no width to truncate against. */}
          <CardTitle className="flex min-w-0 items-center gap-1.5">
            <StatusDot status={expert.status} />
            <span className="sr-only">{expert.status}: </span>
            {/* Stretched link: the pseudo-element covers the whole card, so
                the card is one big hit target while staying a single link with
                a single accessible name. Anything else interactive on the card
                opts back above it with `relative z-10`. */}
            {/* min-w-0 is load-bearing: a flex item defaults to
                min-width:auto, so without it `truncate` never engages and a
                long topic runs out under the tier badge. */}
            <Link
              href={`/experts/${expert.name}`}
              className="min-w-0 flex-1 truncate rounded-lg outline-none after:absolute after:inset-0 after:rounded-lg after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-ring"
            >
              {expert.topic}
            </Link>
          </CardTitle>
          <CardDescription className="line-clamp-1 text-xs">
            {subtitle(expert)}
          </CardDescription>
        </div>
        <TierBadge tier={expert.tier} />
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3">
        <ExpertCardBody expert={expert} />
      </CardContent>

      <CardFooter className="mt-auto justify-between gap-3">
        <MetricStrip expert={expert} />
        {/* Only ready experts get an action. A grid of disabled Chat buttons is
            noise — the body already says what a pending expert is doing. */}
        {expert.status === "ready" ? (
          <div className="relative z-10 shrink-0">
            <ChatButton slug={expert.name} status={expert.status} size="xs" variant="outline" />
          </div>
        ) : null}
      </CardFooter>
    </Card>
  );
}

/** A per-expert visual anchor. Two cards of similar-length text are hard to
 * tell apart in peripheral vision; a fixed glyph block is not. */
function Monogram({ expert }: { expert: ExpertSummary }) {
  return (
    <span
      aria-hidden
      className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted/60 text-xs font-medium text-muted-foreground ring-1 ring-foreground/10"
    >
      {initials(expert)}
    </span>
  );
}

function ExpertCardBody({ expert }: { expert: ExpertSummary }) {
  if (expert.status === "failed") {
    return (
      <Notice icon={<TriangleAlertIcon className="size-3.5" />}>
        Build failed — open the expert for the error and to rebuild.
      </Notice>
    );
  }

  if (expert.status === "queued" || expert.status === "building") {
    return <Notice icon={<Spinner className="size-3.5" />}>{buildLabel(expert)}</Notice>;
  }

  return (
    <>
      {/* Fixed two-line wells for the bio and the chips, so the footers line up
          across a grid row instead of stepping with content length. */}
      <p className="line-clamp-2 min-h-[2.625rem] text-sm text-muted-foreground">
        {expert.persona_bio ?? "No persona summary was generated for this expert."}
      </p>
      <ConceptChips concepts={expert.key_concepts} className="min-h-[2.875rem]" />
    </>
  );
}

/** Status is carried by an icon plus words, never by color — this theme is
 * fully monochromatic (see globals.css). Fills the content well so a pending
 * card doesn't read as a half-empty version of a ready one. */
function Notice({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-1 items-center gap-2 rounded-lg bg-muted/40 px-3 py-3 text-muted-foreground">
      <span className="flex shrink-0 items-center">{icon}</span>
      <p className="text-sm">{children}</p>
    </div>
  );
}

function subtitle(expert: ExpertSummary): string {
  if (!expert.persona_name) return expert.name;
  return expert.persona_style
    ? `${expert.persona_name} · ${expert.persona_style}`
    : expert.persona_name;
}

function initials(expert: ExpertSummary): string {
  const words = expert.topic.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return expert.name.slice(0, 2).toUpperCase();
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

function buildLabel(expert: ExpertSummary): string {
  if (expert.status === "queued") return "Queued for build.";
  // No percentage exists to show — the build reports counts, not progress — so
  // the card states what has landed so far rather than faking a progress bar.
  return expert.source_count > 0
    ? `Building — ${expert.source_count} sources ingested.`
    : "Building — gathering sources.";
}

/** Sources and quality only. Chunk and node counts are build telemetry: they
 * push this strip onto a second line at three-column widths and they answer no
 * question the reader has while choosing an expert. The detail page has them. */
function MetricStrip({ expert }: { expert: ExpertSummary }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5 truncate text-xs text-muted-foreground">
      <span className="text-foreground">{formatCompact(expert.source_count)}</span>
      sources
      <span className="text-muted-foreground/40">·</span>
      <span className="text-foreground">{formatQuality(expert.avg_quality)}</span>
      quality
    </div>
  );
}
