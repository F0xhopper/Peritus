'use client'

import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/cn'

/**
 * An answer, rendered as Markdown one block at a time.
 *
 * An answer is split into top-level blocks and each gets its own memoised
 * `Block`, keyed by index. That is the whole streaming-performance design: a
 * token arriving re-renders only the *trailing* block, so a long answer never
 * re-parses the Markdown it has already rendered. Without it, every token
 * re-parses the entire answer and the frame budget is gone by paragraph three.
 *
 * The split has to respect Markdown's own structure, or it breaks what it
 * splits: a blank line inside a fenced code block, between two items of one
 * list, or before an indented continuation paragraph is *not* a block
 * boundary. Splitting there cut code blocks in half, restarted numbered lists at
 * 1, and threw a list item's second paragraph out of the list.
 *
 * The trailing, still-growing block is rendered as Markdown too, through
 * `closeOpenMarkdown` — so a half-written `**bo` shows as bold rather than as
 * literal asterisks, and nothing reads as raw syntax while the answer arrives.
 */

type Props = { children?: React.ReactNode }

export const COMPONENTS = {
  // `[n]` citation markers are turned into `#cite-n` links before parsing, and
  // `CitedBlock` swaps this renderer for one that draws the chip.
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-fg underline decoration-fg-4 underline-offset-2 hover:decoration-fg-2"
    >
      {children}
    </a>
  ),
  p: ({ children }: Props) => <p className="my-3 first:mt-0 last:mb-0">{children}</p>,
  // Headings step down in size *and* weight so an answer's outline reads at a
  // glance. `#` in an answer is still only a section heading — the page owns the
  // h1 — so every level renders one rank lower.
  h1: ({ children }: Props) => (
    <h3 className="mt-6 mb-2 text-lg font-semibold text-fg first:mt-0">{children}</h3>
  ),
  h2: ({ children }: Props) => (
    <h3 className="mt-6 mb-2 text-[1.0625rem] font-semibold text-fg first:mt-0">{children}</h3>
  ),
  h3: ({ children }: Props) => (
    <h4 className="mt-5 mb-1.5 text-base font-semibold text-fg first:mt-0">{children}</h4>
  ),
  h4: ({ children }: Props) => (
    <h5 className="mt-4 mb-1 text-base font-medium text-fg first:mt-0">{children}</h5>
  ),
  strong: ({ children }: Props) => <strong className="font-semibold text-fg">{children}</strong>,
  em: ({ children }: Props) => <em className="italic">{children}</em>,
  // `start` is passed through: an ordered list that resumes at 4 must say 4.
  ol: ({ children, start }: Props & { start?: number }) => (
    <ol
      start={start}
      className="my-3 list-decimal space-y-1.5 pl-6 marker:text-fg-3 first:mt-0 last:mb-0 [&_ol]:my-1.5 [&_ul]:my-1.5"
    >
      {children}
    </ol>
  ),
  ul: ({ children }: Props) => (
    <ul className="my-3 list-disc space-y-1.5 pl-5 marker:text-fg-4 first:mt-0 last:mb-0 [&_ol]:my-1.5 [&_ul]:my-1.5 [&_ul]:list-[circle]">
      {children}
    </ul>
  ),
  li: ({ children }: Props) => (
    // A loose list wraps each item in <p>; those take list spacing, not
    // paragraph spacing, or every item floats a line apart.
    <li className="pl-1 [&>p]:my-1.5">{children}</li>
  ),
  blockquote: ({ children }: Props) => (
    <blockquote className="my-3 border-l-2 border-border pl-3.5 text-fg-3 first:mt-0 last:mb-0 [&_strong]:text-fg-2">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-5 border-border-soft" />,
  code: ({ className: c, children }: { className?: string; children?: React.ReactNode }) => (
    <code
      className={cn(
        'rounded-[4px] bg-raised px-1 py-0.5 font-mono text-[0.875em] text-fg',
        c,
      )}
    >
      {children}
    </code>
  ),
  pre: ({ children }: Props) => (
    // The inline `code` style is undone inside a block: a fenced block is one
    // surface, not a pill per line.
    <pre className="my-3 overflow-x-auto rounded-card bg-raised px-3 py-2.5 font-mono text-xs leading-relaxed text-fg-2 first:mt-0 last:mb-0 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-[length:inherit] [&_code]:text-inherit">
      {children}
    </pre>
  ),
  table: ({ children }: Props) => (
    // Tables are one of the three things allowed to scroll horizontally, and
    // only inside their own container.
    <div className="my-3 overflow-x-auto rounded-row border border-border-soft first:mt-0 last:mb-0">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  th: ({ children }: Props) => (
    <th className="border-b border-border bg-raised/50 px-2.5 py-1.5 text-left text-xs font-medium whitespace-nowrap text-fg-2">
      {children}
    </th>
  ),
  td: ({ children }: Props) => (
    <td className="border-b border-border-soft px-2.5 py-1.5 align-top [tr:last-child_&]:border-b-0">
      {children}
    </td>
  ),
}

export const Block = memo(function Block({
  source,
  components = COMPONENTS,
}: {
  source: string
  /** Overrides for one block — the cited-block renderer swaps `a`. */
  components?: typeof COMPONENTS
}) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {source}
    </ReactMarkdown>
  )
})

const FENCE = /^\s{0,3}(```|~~~)/
const LIST_ITEM = /^\s{0,3}(?:[-*+]|\d{1,9}[.)])\s/
const INDENTED = /^(?: {2,}|\t)\S/

/**
 * Split an answer into top-level Markdown blocks, at blank lines that really
 * are block boundaries — never inside a fence, never before an indented
 * continuation, and never between two items of the same list.
 */
export function splitBlocks(text: string): string[] {
  const lines = text.split('\n')
  const blocks: string[] = []
  let current: string[] = []
  let inFence = false
  let lastListLine = false

  const flush = () => {
    // Trailing blank lines belong to no block.
    while (current.length && current[current.length - 1].trim() === '') current.pop()
    if (current.length) blocks.push(current.join('\n'))
    current = []
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (FENCE.test(line)) inFence = !inFence

    if (!inFence && line.trim() === '') {
      let next = i + 1
      while (next < lines.length && lines[next].trim() === '') next++
      const upcoming = lines[next]
      const continues =
        upcoming !== undefined &&
        (INDENTED.test(upcoming) || (lastListLine && LIST_ITEM.test(upcoming)))
      if (!continues && current.length) {
        flush()
        continue
      }
      current.push(line)
      continue
    }

    current.push(line)
    if (!inFence && line.trim() !== '') {
      // Whether this block is (still) a list, for the next blank line to ask.
      if (LIST_ITEM.test(line)) lastListLine = true
      else if (!INDENTED.test(line)) lastListLine = false
    }
  }
  flush()
  return blocks.length ? blocks : ['']
}

/**
 * Close what a half-streamed block has left open, for display only: an
 * unterminated code fence, `**strong**` or `` `code` ``, and a citation marker
 * cut off mid-number. The stored answer is never touched.
 */
export function closeOpenMarkdown(text: string): string {
  let out = text.replace(/\[\d{0,3}$/, '')
  const fences = out.split('\n').filter((line) => FENCE.test(line)).length
  if (fences % 2 === 1) return `${out}\n\`\`\``
  // Inline markers, ignoring anything inside inline code.
  const prose = out.replace(/`[^`\n]*`/g, '')
  if ((prose.match(/`/g) ?? []).length % 2 === 1) out += '`'
  const strongs = (prose.match(/\*\*/g) ?? []).length
  // Single `*` emphasis: what is left once `**` pairs and line-start bullets are
  // taken out. Closed inside any open `**`, so `**bold *it` nests correctly.
  const singles = (prose.replace(/\*\*/g, '').replace(/^\s*[*+-]\s/gm, '').match(/\*/g) ?? [])
    .length
  if (singles % 2 === 1) out += '*'
  if (strongs % 2 === 1) out += '**'
  // A dangling list marker or heading hash with nothing after it yet renders as
  // an empty bullet or a stray "#"; hold it back until its text arrives.
  return out.replace(/(^|\n)\s{0,3}(?:[-*+]|#{1,6}|\d{1,9}[.)])\s*$/, '$1')
}
