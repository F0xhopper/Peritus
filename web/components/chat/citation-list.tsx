"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import type { Citation } from "@/lib/api/types";

/** Per-message footer listing the passages the answer actually cited.
 * Rendered from stored JSONB, never parsed out of the answer text.
 *
 * Markers are grouped by the source they point at. Retrieval routinely returns
 * four or five passages from one book, and listing them as four identical
 * lines — "The Intelligent Investor — Exa · Q:7.0" repeated — made a five-source
 * answer look like a ten-source one and buried the sources that appeared once.
 * Grouped, the list says how many distinct works the answer rests on, which is
 * the number that means something. Every marker keeps its own anchor, so
 * clicking `[4]` in the prose still lands on the right row. */
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
  const groups = React.useMemo(() => groupByLabel(citations), [citations]);

  if (citations.length === 0) return null;

  return (
    <div className="mt-3 border-t border-border/60 pt-2">
      <p className="text-eyebrow mb-2 text-muted-foreground">
        Sources
        {groups.length !== citations.length ? (
          <span className="ml-2 tracking-normal normal-case opacity-70">
            {groups.length} of {citations.length} passages
          </span>
        ) : null}
      </p>
      <ol className="flex flex-col gap-1">
        {groups.map((group) => {
          const lit = group.numbers.includes(highlighted ?? -1);
          return (
            <li
              key={group.numbers.join("-")}
              className={cn(
                "flex gap-2 rounded-sm px-1 py-0.5 text-xs text-muted-foreground transition-colors",
                lit && "bg-primary/10 text-foreground",
              )}
            >
              <span className="flex shrink-0 gap-1 font-mono text-primary">
                {group.numbers.map((n) => (
                  // One anchor per marker, so `jumpToCitation` still resolves
                  // every number the prose can contain.
                  <span key={n} id={`cite-${messageKey}-${n}`}>
                    [{n}]
                  </span>
                ))}
              </span>
              <span>{group.label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

interface CitationGroup {
  label: string;
  numbers: number[];
}

function groupByLabel(citations: Citation[]): CitationGroup[] {
  const groups: CitationGroup[] = [];
  // Keyed on source_id where the API supplied one — two passages from the same
  // work can carry slightly different labels — and on the label otherwise.
  const index = new Map<string, CitationGroup>();

  for (const citation of citations) {
    const key =
      citation.source_id !== null
        ? `id:${citation.source_id}`
        : `label:${citation.label}`;
    const existing = index.get(key);
    if (existing) {
      existing.numbers.push(citation.n);
    } else {
      const group = { label: citation.label, numbers: [citation.n] };
      index.set(key, group);
      groups.push(group);
    }
  }

  return groups;
}
