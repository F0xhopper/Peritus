import Link from "next/link";
import { MessageSquareIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ExpertStatus } from "@/lib/api/types";

// Chat entry point, gated on the expert being ready. Used from the expert
// detail header and the experts table so the gating rule lives in one place.

export function ChatButton({
  slug,
  status,
  size = "sm",
  variant = "default",
  label = "Chat",
}: {
  slug: string;
  status: ExpertStatus;
  size?: "xs" | "sm" | "default";
  variant?: "default" | "outline" | "ghost";
  label?: string;
}) {
  if (status === "ready") {
    return (
      <Button
        size={size}
        variant={variant}
        nativeButton={false}
        render={<Link href={`/experts/${slug}/chat`} />}
      >
        <MessageSquareIcon />
        {label}
      </Button>
    );
  }

  return (
    <Tooltip>
      {/* A disabled button swallows pointer events, so the tooltip hangs off a
          focusable wrapper instead — otherwise the explanation is unreachable. */}
      <TooltipTrigger
        render={<span tabIndex={0} className="inline-flex rounded-lg" />}
      >
        <Button size={size} variant={variant} disabled>
          <MessageSquareIcon />
          {label}
        </Button>
      </TooltipTrigger>
      <TooltipContent>Available when the expert is ready</TooltipContent>
    </Tooltip>
  );
}
