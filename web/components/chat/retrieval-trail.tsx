import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { RetrievalTrail as Trail } from "@/components/chat/use-chat-stream";

// The answer's audit trail: how many passages were retrieved, and how many the
// answer actually cited.
//
// Deliberately a COUNT, not a percentage. A grounding/faithfulness score was
// removed from answers on purpose and must not come back — a ratio invites
// reading as a confidence figure, which there is no calibration to support.
// "Grounded in 6 of 23 retrieved passages" is a fact; "74% grounded" is a claim.

export function RetrievalTrail({ trail }: { trail: Trail }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            tabIndex={0}
            className="inline-flex cursor-help items-center gap-1 text-xs text-muted-foreground"
          />
        }
      >
        Cited {trail.cited} of {trail.in_context} passages
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-pretty">
        {trail.retrieved} passages were retrieved, {trail.unique} unique.{" "}
        {trail.in_context} were placed in the prompt and the answer cited{" "}
        {trail.cited}. This is a record of what the answer drew on, not a
        measure of how good it is.
      </TooltipContent>
    </Tooltip>
  );
}
