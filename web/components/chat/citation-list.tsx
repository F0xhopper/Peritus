"use client";

import { cn } from "@/lib/utils";
import type { Citation } from "@/lib/api/types";

/** Per-message footer listing the passages the answer actually cited.
 * Rendered from stored JSONB, never parsed out of the answer text. */
export function CitationList({
  citations,
  messageKey,
  highlighted,
}: {
  citations: Citation[];
  /** Namespaces the anchor ids so several messages can coexist on one page. */
  messageKey: string;
  highlighted: number | null;
}) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-3 border-t border-border/60 pt-2">
      <p className="text-eyebrow mb-2 text-muted-foreground">Sources</p>
      <ol className="flex flex-col gap-1">
        {citations.map((citation) => (
          <li
            key={citation.n}
            id={`cite-${messageKey}-${citation.n}`}
            className={cn(
              "flex gap-2 rounded-sm px-1 py-0.5 text-xs text-muted-foreground transition-colors",
              highlighted === citation.n && "bg-primary/10 text-foreground",
            )}
          >
            <span className="font-mono text-primary">[{citation.n}]</span>
            <span>{citation.label}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
