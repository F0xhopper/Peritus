"use client";

import * as React from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangleIcon, UnplugIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { CitationList } from "@/components/chat/citation-list";
import type { Citation } from "@/lib/api/types";

// Assistant output is rendered through react-markdown with GFM only —
// `rehype-raw` is deliberately absent, so any HTML the model emits stays
// escaped text. That is also what closes the XSS question for model output.

const MARKDOWN_PLUGINS = [remarkGfm];

export function Message({
  role,
  content,
  citations,
  hasContradiction,
  interrupted,
  messageKey,
  streaming,
}: {
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  hasContradiction: boolean;
  interrupted: boolean;
  messageKey: string;
  streaming?: boolean;
}) {
  const [highlighted, setHighlighted] = React.useState<number | null>(null);

  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg rounded-br-sm bg-muted px-3 py-2 text-sm whitespace-pre-wrap">
          {content}
        </div>
      </div>
    );
  }

  const citedNumbers = new Set((citations ?? []).map((c) => c.n));

  const jumpToCitation = (n: number) => {
    setHighlighted(n);
    document
      .getElementById(`cite-${messageKey}-${n}`)
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    window.setTimeout(() => setHighlighted(null), 1600);
  };

  return (
    <div className="flex flex-col">
      <div
        className={cn(
          "max-w-[92%] text-sm",
          // Prose-ish spacing without a typography plugin dependency.
          "[&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2",
          "[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.85em]",
          "[&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-muted [&_pre]:p-3",
          "[&_pre_code]:bg-transparent [&_pre_code]:p-0",
          "[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5",
          "[&_li]:my-0.5",
          "[&_p]:my-2 first:[&_p]:mt-0 last:[&_p]:mb-0",
          "[&_h1]:mt-3 [&_h1]:mb-1.5 [&_h1]:text-base [&_h1]:font-medium",
          "[&_h2]:mt-3 [&_h2]:mb-1.5 [&_h2]:text-sm [&_h2]:font-medium",
          "[&_h3]:mt-3 [&_h3]:mb-1.5 [&_h3]:text-sm [&_h3]:font-medium",
          "[&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
          "[&_table]:my-2 [&_table]:w-full [&_table]:text-xs",
          "[&_th]:border-b [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:text-left",
          "[&_td]:border-b [&_td]:border-border/50 [&_td]:px-2 [&_td]:py-1",
        )}
      >
        <Markdown
          remarkPlugins={MARKDOWN_PLUGINS}
          components={{
            // Citation markers are rewritten at the text-node level so they
            // survive wherever the model puts them (mid-sentence, in a list,
            // inside a table cell).
            p: ({ children }) => (
              <p>{renderCitations(children, citedNumbers, jumpToCitation)}</p>
            ),
            li: ({ children }) => (
              <li>{renderCitations(children, citedNumbers, jumpToCitation)}</li>
            ),
            td: ({ children }) => (
              <td>{renderCitations(children, citedNumbers, jumpToCitation)}</td>
            ),
          }}
        >
          {content}
        </Markdown>
        {streaming && (
          <span
            className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-primary"
            aria-hidden
          />
        )}
      </div>

      {hasContradiction && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-500">
          <AlertTriangleIcon className="size-3.5" />
          Sources disagree on part of this answer.
        </p>
      )}

      {interrupted && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <UnplugIcon className="size-3.5" />
          Answer interrupted.
        </p>
      )}

      {citations && citations.length > 0 && (
        <CitationList
          citations={citations}
          messageKey={messageKey}
          highlighted={highlighted}
        />
      )}
    </div>
  );
}

const CITATION_RE = /\[(\d{1,3})\]/g;

/** Replace `[n]` markers in text nodes with clickable chips, leaving any
 * already-rendered elements (bold, links, code) untouched. */
function renderCitations(
  children: React.ReactNode,
  cited: Set<number>,
  onJump: (n: number) => void,
): React.ReactNode {
  return React.Children.map(children, (child, childIndex) => {
    if (typeof child !== "string") return child;

    const parts: React.ReactNode[] = [];
    let cursor = 0;
    CITATION_RE.lastIndex = 0;

    for (let m = CITATION_RE.exec(child); m; m = CITATION_RE.exec(child)) {
      const n = Number(m[1]);
      // Only numbers backed by a real citation become chips; anything else is
      // ordinary text that happened to look like a marker.
      if (!cited.has(n)) continue;

      if (m.index > cursor) parts.push(child.slice(cursor, m.index));
      parts.push(
        <button
          key={`${childIndex}-${m.index}`}
          type="button"
          onClick={() => onJump(n)}
          aria-label={`Jump to source ${n}`}
          className="mx-px inline-flex min-w-4 cursor-pointer justify-center rounded-sm bg-primary/10 px-1 align-super font-mono text-[0.65em] leading-relaxed text-primary hover:bg-primary/20"
        >
          {n}
        </button>,
      );
      cursor = m.index + m[0].length;
    }

    if (parts.length === 0) return child;
    if (cursor < child.length) parts.push(child.slice(cursor));
    return parts;
  });
}
