"use client";

import { cn } from "@/lib/utils";

/** Retrieval progress ("Searching knowledge base…") shown while the pipeline
 * runs, before the first token arrives. */
export function StatusLine({
  message,
  className,
}: {
  message: string;
  className?: string;
}) {
  return (
    <p
      className={cn(
        "flex items-center gap-2 text-sm text-muted-foreground",
        className,
      )}
    >
      <span
        className="size-1.5 animate-pulse rounded-full bg-primary"
        aria-hidden
      />
      <span className="animate-pulse">{message}</span>
    </p>
  );
}
