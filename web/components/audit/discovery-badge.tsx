import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { DiscoveryMethod } from "@/lib/api/types";

// Search provenance — which search produced this source.
//
// This is the field a tool that starts from a bibliographic database export
// cannot have, because there every record arrived the same way. `gapfill` is
// the sharpest of the three: a search that exists only because a named concept
// had no accepted source.

const LABELS: Record<string, { label: string; hint: string }> = {
  plan: {
    label: "planned",
    hint: "Found by the planned first-pass search for this topic.",
  },
  snowball: {
    label: "snowballed",
    hint: "Found by following high-citation references out of a discovered preprint.",
  },
  gapfill: {
    label: "gap-fill",
    hint: "Found by a targeted re-search that ran only because a key concept had no accepted source.",
  },
};

export function DiscoveryBadge({
  method,
  concept,
  raw,
}: {
  method: DiscoveryMethod;
  concept: string | null;
  raw: string | null;
}) {
  if (!method) {
    return (
      <Tooltip>
        <TooltipTrigger
          render={
            <span
              tabIndex={0}
              className="cursor-help text-xs text-muted-foreground/70 italic"
            />
          }
        >
          not recorded
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-pretty">
          This source predates discovery provenance being persisted, so which
          search produced it is unknown.
        </TooltipContent>
      </Tooltip>
    );
  }

  const meta = LABELS[method] ?? { label: raw ?? method, hint: "" };

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Badge
            variant={method === "gapfill" ? "default" : "outline"}
            className="cursor-help font-normal"
          />
        }
      >
        {meta.label}
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-pretty">
        {meta.hint}
        {concept ? (
          <>
            {" "}
            The uncovered concept was <strong>{concept}</strong>.
          </>
        ) : null}
      </TooltipContent>
    </Tooltip>
  );
}
