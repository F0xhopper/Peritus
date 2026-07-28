import { CircleHelpIcon } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { AuditCount } from "@/lib/api/types";

// The single most important component on the audit surface.
//
// Peritus returns `{count: null, unavailable_reason: "..."}` for anything it
// does not actually persist. Rendering that as "0" would invent a number in an
// evidence record — the exact failure the whole product claims to avoid. So a
// missing count reads as "not recorded" and carries the reason for why.

export function NotRecorded({ reason }: { reason?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            tabIndex={0}
            className="inline-flex cursor-help items-center gap-1 text-muted-foreground/70 italic"
          />
        }
      >
        not recorded
        <CircleHelpIcon className="size-3" aria-hidden />
      </TooltipTrigger>
      {reason ? (
        <TooltipContent className="max-w-sm text-pretty">{reason}</TooltipContent>
      ) : null}
    </Tooltip>
  );
}

/** A funnel count that may legitimately be absent. */
export function StageCount({ stage }: { stage: AuditCount }) {
  if (stage.count === null) {
    return <NotRecorded reason={stage.unavailable_reason} />;
  }
  return <span className="tabular-nums">{stage.count.toLocaleString()}</span>;
}
