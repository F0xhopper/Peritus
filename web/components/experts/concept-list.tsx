import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// Replaces the chip row. Concepts are a table of contents for what an expert
// covers — a list of things, read down — and pills set them side by side like
// tags, which made a long concept and a short one compete for the same line
// and forced every one of them to truncate mid-phrase.
//
// A real <ul> with markers also means a screen reader announces "list, 5
// items" instead of five unrelated inline spans.
//
// On a card the list is capped and the tail goes behind a +N, because card
// height has to be predictable across a grid row. On the detail page there is
// no cap: that is the page you open precisely to read all of them.

export function ConceptList({
  concepts,
  max,
  className,
}: {
  concepts: string[];
  /** Omit to render every concept. */
  max?: number;
  className?: string;
}) {
  const shown = max === undefined ? concepts : concepts.slice(0, max);
  const rest = max === undefined ? [] : concepts.slice(max);

  if (concepts.length === 0) {
    return (
      <p className={cn("text-sm text-muted-foreground/70 italic", className)}>
        No key concepts were extracted.
      </p>
    );
  }

  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      {/* Deliberately not a flex container: flex items generate no ::marker
          box, so `list-disc` renders nothing at all inside one. Normal flow
          plus space-y is what actually produces bullets. */}
      <ul className="ml-4 list-disc space-y-1 text-sm text-muted-foreground marker:text-muted-foreground/40">
        {shown.map((concept) => (
          // The clip goes on an inner span, never on the <li> itself: an
          // `overflow: hidden` list item hides its own outside ::marker, which
          // is a silent way to end up with a bulleted list that has no bullets.
          <li key={concept}>
            <span className="block truncate">{concept}</span>
          </li>
        ))}
      </ul>
      {rest.length > 0 ? (
        <Tooltip>
          {/* z-10 lifts the trigger above the card's stretched link, which
              otherwise swallows the hover that opens the tooltip. */}
          <TooltipTrigger
            render={
              <span
                tabIndex={0}
                className="relative z-10 ml-4 w-fit cursor-default text-xs text-muted-foreground/70 underline decoration-dotted underline-offset-4"
              />
            }
          >
            +{rest.length} more
          </TooltipTrigger>
          <TooltipContent>{rest.join(", ")}</TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}
