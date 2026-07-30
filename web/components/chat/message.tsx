"use client";

import * as React from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { UnplugIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { CitationList } from "@/components/chat/citation-list";
import { RetrievalTrail } from "@/components/chat/retrieval-trail";
import type { RetrievalTrail as RetrievalTrailData } from "@/components/chat/use-chat-stream";
import type { Citation } from "@/lib/api/types";

// Assistant output is rendered through react-markdown with GFM only —
// `rehype-raw` is deliberately absent, so any HTML the model emits stays
// escaped text. That is also what closes the XSS question for model output.

const MARKDOWN_PLUGINS = [remarkGfm];

// The API still reports `has_contradiction` per answer, and the chat prompt
// still uses it to shape how the model writes — but it no longer surfaces as a
// footnote under the answer. A flag raised on every answer touching two
// sources that disagree reads as a defect report on the answer rather than as
// a property of the literature, and the answers already say so in prose where
// it matters ("here's a genuine tension in the sources").

export function Message({
  role,
  content,
  citations,
  interrupted,
  trail,
  messageKey,
  streaming,
}: {
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  interrupted: boolean;
  trail?: RetrievalTrailData | null;
  messageKey: string;
  streaming?: boolean;
}) {
  const [highlighted, setHighlighted] = React.useState<number | null>(null);

  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-measure rounded-lg bg-muted px-3.5 py-2.5 font-serif text-[0.9375rem] leading-[1.6] whitespace-pre-wrap">
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
          // Measure, not percentage. Line length is a property of the type —
          // ~70 characters of Literata — so it stays put as the window widens
          // instead of stretching answers into unreadable full-bleed lines.
          "max-w-measure font-serif text-[0.9375rem] leading-[1.7]",
          // Prose-ish spacing without a typography plugin dependency.
          "[&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2",
          // Code keeps the mono face and tabular figures — it is the one
          // place in an answer that is data rather than prose.
          "[&_code]:rounded-xs [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.85em] [&_code]:[font-variant-numeric:lining-nums_tabular-nums]",
          "[&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-xs [&_pre]:bg-muted [&_pre]:p-3",
          "[&_pre_code]:bg-transparent [&_pre_code]:p-0",
          "[&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5",
          "[&_li]:my-1 [&_li]:pl-1",
          "[&_p]:my-3 first:[&_p]:mt-0 last:[&_p]:mb-0",
          // Section heads in the display face, sentence case — an answer is
          // still prose, so its subheads whisper rather than announce.
          "[&_h1]:mt-5 [&_h1]:mb-2 [&_h1]:font-display [&_h1]:text-[1.0625rem] [&_h1]:font-semibold [&_h1]:tracking-wide",
          "[&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:font-display [&_h2]:text-[0.9375rem] [&_h2]:font-semibold [&_h2]:tracking-wide",
          // Third level drops to the reading face in italic, the way a book
          // runs a minor head into the text rather than adding another size.
          "[&_h3]:mt-4 [&_h3]:mb-1.5 [&_h3]:font-serif [&_h3]:text-[0.9375rem] [&_h3]:font-semibold [&_h3]:italic",
          // Quoted source material, set as a book sets an extract: italic,
          // indented, with a hairline rather than a heavy bar.
          "[&_blockquote]:my-3 [&_blockquote]:border-l [&_blockquote]:border-border [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-muted-foreground",
          "[&_table]:my-3 [&_table]:w-full [&_table]:text-[0.8125rem] [&_table]:[font-variant-numeric:lining-nums_tabular-nums]",
          "[&_th]:border-b [&_th]:border-border [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-display [&_th]:text-[0.6875rem] [&_th]:tracking-[0.14em] [&_th]:uppercase",
          "[&_td]:border-b [&_td]:border-border/50 [&_td]:px-2 [&_td]:py-1.5",
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
            // A hairline typesetter's caret, not the fat block a terminal
            // blinks — same affordance, without the console accent.
            className="ml-0.5 inline-block h-[1.05em] w-px translate-y-[0.15em] animate-pulse bg-primary"
            aria-hidden
          />
        )}
      </div>

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

      {trail && (
        <div className="mt-2">
          <RetrievalTrail trail={trail} />
        </div>
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
