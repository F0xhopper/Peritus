import Link from "next/link";
import { ArrowUpRightIcon, MessageSquareIcon, TriangleAlertIcon } from "lucide-react";
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
import { ConceptList } from "@/components/experts/concept-list";
import { ExpertMenu } from "@/components/experts/expert-menu";
import { formatCompact } from "@/lib/format";
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
//
// The whole card opens the chat, not the detail page. Chatting is what an
// expert is *for*; the detail page is a spec sheet you consult occasionally,
// so it gets the small explicit link in the footer rather than the 300px-wide
// hit target. A card whose surface went to the spec sheet while the action it
// exists for was a 60px button in the corner had that backwards.
//
// Only a ready expert can be chatted with, so a pending or failed card opens
// its build page instead — the live stage view while it runs, and the durable
// event log (including the failure) once it has stopped.

export function ExpertCard({ expert }: { expert: ExpertSummary }) {
  const ready = expert.status === "ready";
  // A card that isn't ready opens its build page, not its spec sheet: while it
  // is queued or building that is the only surface with anything live to say,
  // and once it has failed it is the only one holding the error log.
  const href = ready
    ? `/experts/${expert.name}/chat`
    : `/experts/${expert.name}/build`;

  return (
    <Card className="relative h-full rounded-lg transition-[background-color,box-shadow] hover:bg-muted/25 hover:ring-foreground/25">
      <CardHeader className="flex items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {/* CardTitle is a plain block in this style, so the row is built
              here — an inline <a> has no width to truncate against. */}
          <CardTitle className="flex min-w-0 items-center gap-1.5">
            {/* Ready is the boring default, and a bright dot on every healthy
                card spends the grid's attention budget on nothing. Only the
                statuses that want something from you get a mark; the state is
                still announced to screen readers on every card. */}
            {ready ? null : <StatusDot status={expert.status} />}
            <span className="sr-only">{expert.status}: </span>
            {/* Stretched link: the pseudo-element covers the whole card, so
                the card is one big hit target while staying a single link with
                a single accessible name. Anything else interactive on the card
                opts back above it with `relative z-10`. */}
            {/* min-w-0 is load-bearing: a flex item defaults to
                min-width:auto, so without it `truncate` never engages and a
                long topic runs out under the corner icon. */}
            <Link
              href={href}
              className="min-w-0 flex-1 truncate rounded-lg outline-none after:absolute after:inset-0 after:rounded-lg after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-ring"
            >
              {/* Names the destination, since the visible text is a topic and
                  not an action: "Chat with Stoic Philosophy". */}
              <span className="sr-only">{ready ? "Chat with " : "Open "}</span>
              {expert.topic}
            </Link>
          </CardTitle>
          <CardDescription className="line-clamp-1 text-xs">
            {subtitle(expert)}
          </CardDescription>
        </div>
        {/* Says where the card goes before you click it — the tier badge used
            to hold this corner, which spent the card's strongest position on
            its least-consulted field. Tier moved to the footer strip. */}
        <DestinationHint ready={ready} />
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3">
        <ExpertCardBody expert={expert} />
      </CardContent>

      <CardFooter className="mt-auto justify-between gap-3">
        <MetricStrip expert={expert} />
        {/* Every interactive control on the card lives here, above the
            stretched link. Keeping the destructive one down here rather than in
            the header also keeps it away from the title. */}
        <div className="relative z-10 flex shrink-0 items-center gap-1">
          {/* The card already goes to the chat, so the detail page needs its
              own way in. Ready experts only — a pending card *is* the detail
              link. */}
          {ready ? (
            <Link
              href={`/experts/${expert.name}`}
              className="rounded-lg text-xs text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
            >
              Details
              <span className="sr-only"> for {expert.topic}</span>
            </Link>
          ) : null}
          <ExpertMenu slug={expert.name} topic={expert.topic} />
        </div>
      </CardFooter>
    </Card>
  );
}

function DestinationHint({ ready }: { ready: boolean }) {
  const Icon = ready ? MessageSquareIcon : ArrowUpRightIcon;
  return (
    <Icon
      aria-hidden
      className="size-4 shrink-0 text-muted-foreground/50 transition-colors group-hover/card:text-foreground"
    />
  );
}

function ExpertCardBody({ expert }: { expert: ExpertSummary }) {
  if (expert.status === "failed") {
    // Now that the card routes to the build page, the durable event log really
    // is one click away — so this can say so.
    return (
      <Notice icon={<TriangleAlertIcon className="size-3.5" />}>
        Build failed. Open for the log.
      </Notice>
    );
  }

  if (expert.status === "queued" || expert.status === "building") {
    return <Notice icon={<Spinner className="size-3.5" />}>{buildLabel(expert)}</Notice>;
  }

  return (
    <>
      {/* Fixed wells — four lines of bio, two rows of chips — so the footers
          line up across a grid row instead of stepping with content length.
          Four lines fits a typical generated bio whole; at two it was cut
          mid-sentence on nearly every expert. */}
      <p className="line-clamp-4 min-h-[5.25rem] text-sm text-muted-foreground">
        {expert.persona_bio ?? "No persona summary was generated for this expert."}
      </p>
      <ConceptList concepts={expert.key_concepts} max={3} className="min-h-[5.25rem]" />
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

function buildLabel(expert: ExpertSummary): string {
  if (expert.status === "queued") return "Queued for build.";
  // No percentage exists to show — the build reports counts, not progress — so
  // the card states what has landed so far rather than faking a progress bar.
  return expert.source_count > 0
    ? `Building — ${expert.source_count} sources ingested.`
    : "Building — gathering sources.";
}

/** Sources and tier. Chunk and node counts are build telemetry: they push this
 * strip onto a second line at three-column widths and they answer no question
 * the reader has while choosing an expert. Average source quality is gone from
 * the card for a related reason — it's a number about the corpus, not about
 * whether this is the expert you want. Both live on the detail page.
 * Tier rides here rather than in a header badge — it's a fact about the build,
 * scanned in the same pass as the count, not a headline. */
function MetricStrip({ expert }: { expert: ExpertSummary }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5 truncate text-xs text-muted-foreground">
      {/* Tabular so the counts align down a grid column — running prose
          takes the proportional default. */}
      <span className="text-foreground tabular-nums lining-nums">
        {formatCompact(expert.source_count)}
      </span>
      sources
      <span className="text-muted-foreground/40">·</span>
      {/* The bulleted list above is capped at three, so the total is not
          readable from it — this is the only place the full count appears. */}
      <span className="text-foreground tabular-nums lining-nums">
        {formatCompact(expert.key_concepts.length)}
      </span>
      concepts
      <span className="text-muted-foreground/40">·</span>
      {/* Same voice as <TierBadge>, without the box — tier is a label here. */}
      <span className="font-display text-[0.6875rem] tracking-[0.14em] uppercase">
        {expert.tier}
      </span>
    </div>
  );
}
