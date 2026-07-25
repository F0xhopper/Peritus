import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// The chips are the whole reason experts stop looking alike, so they get a
// fixed budget: `max` chips inline and the tail behind a +N. Letting the row
// wrap freely would make card heights depend on how many concepts the build
// happened to extract.

export function ConceptChips({
  concepts,
  max = 4,
  className,
}: {
  concepts: string[];
  max?: number;
  className?: string;
}) {
  if (concepts.length === 0) return null;

  const shown = concepts.slice(0, max);
  const rest = concepts.slice(max);

  return (
    <div className={cn("flex flex-wrap content-start items-start gap-1.5", className)}>
      {shown.map((concept) => (
        <Badge key={concept} variant="outline" className="max-w-40 truncate">
          {concept}
        </Badge>
      ))}
      {rest.length > 0 ? (
        <Tooltip>
          {/* z-10 lifts the trigger above the card's stretched link, which
              otherwise swallows the hover that opens the tooltip. */}
          <TooltipTrigger
            render={
              <span tabIndex={0} className="relative z-10 inline-flex rounded-4xl" />
            }
          >
            <Badge variant="outline" className="text-muted-foreground">
              +{rest.length}
            </Badge>
          </TooltipTrigger>
          <TooltipContent>{rest.join(", ")}</TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}
