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
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { StatusDot } from "@/components/experts/status-dot";
import { ConceptList } from "@/components/experts/concept-list";
import { ExpertMenu } from "@/components/experts/expert-menu";
import { PersonaAvatar } from "@/components/experts/persona-avatar";
import { formatCompact } from "@/lib/format";
import { personaLabel } from "@/lib/persona";
import type { ExpertSummary } from "@/lib/api/types";

// Replaces the experts table. The table could only show `topic` plus build
// telemetry, which is identically shaped for every expert — the fields that
// actually tell two experts apart (persona, bio, key concepts) don't fit in a
// cell.
//
// The card leads with the person: "Dr. Elena Vasquez", topic underneath. What
// you do with an expert is talk to it, and a grid of subject headings reads
// like a filing cabinet — you pick a topic out of a filing cabinet, but you
// ask a question of somebody. The topic is still the second line, so the
// answer to "which of these knows about Stoicism" is one glance away.
//
// Experts without a persona (queued, building, failed) lead with the topic
// instead — there is no name yet, and captioning them "Dr. Stoic Philosophy"
// would invent one. `name` (the URL slug) is the last resort under it.
//
// The whole card opens the detail page — the spec sheet with the persona,
// bio, and corpus stats is what tells two same-topic experts apart, and
// browsing the grid to find the right one is that kind of looking, not yet a
// question you have. Starting a chat is a separate, deliberate act with its
// own destination, so it gets its own explicit button in the corner rather
// than riding the card's whole surface.
//
// Only a ready expert can be chatted with, so a pending or failed card opens
// its build page instead — the live stage view while it runs, and the durable
// event log (including the failure) once it has stopped.

export function ExpertCard({ expert }: { expert: ExpertSummary }) {
  const ready = expert.status === "ready";
  // A card that isn't ready opens its build page, not its spec sheet: while it
  // is queued or building that is the only surface with anything live to say,
  // and once it has failed it is the only one holding the error log.
  const href = ready ? `/experts/${expert.name}` : `/experts/${expert.name}/build`;
  const persona = personaLabel(expert.persona_name);
  const heading = persona ?? expert.topic;

  return (
    <Card className="relative h-full rounded-lg transition-colors hover:bg-muted/40">
      <CardHeader className="flex items-start gap-3">
        <PersonaAvatar label={heading} />
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
                long name runs out under the corner icon. */}
            <Link
              href={href}
              className="min-w-0 flex-1 truncate rounded-lg outline-none after:absolute after:inset-0 after:rounded-lg after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-ring"
            >
              {/* Names the destination, since the visible text is a person and
                  not an action: "View Dr. Elena Vasquez". */}
              <span className="sr-only">{ready ? "View " : "Open "}</span>
              {heading}
            </Link>
          </CardTitle>
          <CardDescription className="line-clamp-1 text-xs">
            {subtitle(expert, persona)}
          </CardDescription>
        </div>
        {/* The one control that isn't "browse into this card": starting a chat
            has its own destination, so it stays a real button, above the
            stretched link, rather than a hint about where the card goes. */}
        {ready ? (
          <Button
            variant="outline"
            size="sm"
            className="relative z-10 shrink-0"
            nativeButton={false}
            render={<Link href={`/experts/${expert.name}/chat`} />}
          >
            <MessageSquareIcon />
            Chat
          </Button>
        ) : (
          <DestinationHint />
        )}
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3">
        <ExpertCardBody expert={expert} />
      </CardContent>

      <CardFooter className="mt-auto justify-between gap-3">
        <MetricStrip expert={expert} />
        {/* The only remaining footer control: the destructive action stays
            down here, above the stretched link, and away from the title. */}
        <div className="relative z-10 shrink-0">
          <ExpertMenu slug={expert.name} topic={expert.topic} />
        </div>
      </CardFooter>
    </Card>
  );
}

/** Not-ready cards still open the build page on click; this is the only
 * indication of that before you click, since there is no separate button for
 * a destination that isn't chattable yet. */
function DestinationHint() {
  return (
    <ArrowUpRightIcon
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

/** Whatever the heading didn't say. A named expert is captioned with its
 * subject; an unnamed one has only its slug left to give.
 *
 * `persona_style` used to ride here and doesn't any more: it is the expert's
 * whole system-prompt instruction block, hundreds of characters of "cite the
 * passage before you paraphrase it", and a one-line clamp turned that into a
 * sentence fragment on every card. It belongs on the detail page. */
function subtitle(expert: ExpertSummary, persona: string | null): string {
  return persona ? expert.topic : expert.name;
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
