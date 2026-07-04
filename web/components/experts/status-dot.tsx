import { cn } from "@/lib/utils";
import type { ExpertStatus } from "@/lib/api/types";

// Fully monochromatic: status is carried by glyph shape, never color, so it
// never reads as "color alone" and stays legible without hue.
const STATUS_GLYPH: Record<ExpertStatus, string> = {
  queued: "○",
  building: "◐",
  ready: "●",
  failed: "✕",
};

const STATUS_COLOR: Record<ExpertStatus, string> = {
  queued: "text-status-queued",
  building: "text-status-building",
  ready: "text-status-ready",
  failed: "text-status-failed",
};

const PULSING: ExpertStatus[] = ["queued", "building"];

export function StatusDot({ status }: { status: ExpertStatus }) {
  return (
    <span
      aria-hidden
      className={cn(
        "leading-none select-none",
        STATUS_COLOR[status],
        PULSING.includes(status) && "animate-pulse",
      )}
    >
      {STATUS_GLYPH[status]}
    </span>
  );
}
