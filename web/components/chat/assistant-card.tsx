'use client'

import { Check, Copy, RotateCcw, ScrollText } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { CitationList, CitedText, numberCitations } from '@/components/chat/citations'
import { PopoverContent, PopoverRoot, PopoverTrigger } from '@/components/ui/popover'
import { Block, COMPONENTS, closeOpenMarkdown, splitBlocks } from '@/components/chat/markdown'
import { Collapse } from '@/components/ui/collapse'
import { cn } from '@/lib/cn'
import { displayName } from '@/lib/persona'
import type { Citation, ChatRetrievalAuditEvent, ExpertSummary } from '@/lib/api/types'

/**
 * One answer.
 *
 * No bubbles: an answer is a card on `--panel` with the persona's 20px avatar
 * and name on the first line, the body, and a small action row. The user's own
 * prompt is plain text between cards, with no card of its own — it is not
 * something the product is asserting, so it does not get a surface.
 *
 * While streaming, completed blocks go through memoised Markdown and only the
 * trailing block re-parses, with whatever it has left open closed for display
 * (`closeOpenMarkdown`) — so the answer is formatted as it arrives, not raw
 * syntax that snaps into shape at the end.
 */
export function AssistantCard({
  expert,
  content,
  citations,
  dangling,
  streaming,
  interrupted,
  audit,
  hasContradiction,
  onSelectCitation,
  selectedCitation,
  onRegenerate,
  className,
}: {
  expert: Pick<ExpertSummary, 'name' | 'persona_name' | 'topic' | 'avatar'>
  content: string
  citations: Citation[]
  dangling: number[]
  streaming?: boolean
  interrupted?: boolean
  audit?: ChatRetrievalAuditEvent | null
  hasContradiction?: boolean
  onSelectCitation: (citation: Citation) => void
  selectedCitation: number | null
  onRegenerate?: () => void
  className?: string
}) {
  const [copied, setCopied] = useState(false)
  const [showTrail, setShowTrail] = useState(false)

  // 1, 2, 3 in the order this answer cites them, rather than the passage index.
  const numbered = useMemo(() => numberCitations(content, citations), [content, citations])
  // An answer that ends mid-sentence with nothing saying so looks finished. The
  // server marks the cases it knows about as interrupted; this catches the rest
  // (a length cut recorded before the stop reason was kept).
  const cutShort = !streaming && !interrupted && endsMidSentence(content)

  const blocks = splitBlocks(content)
  // While streaming the last block is still being written; when finished, all
  // of them are complete.
  const completed = streaming ? blocks.slice(0, -1) : blocks
  const trailing = streaming ? blocks[blocks.length - 1] : null

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked — the user can still select the text */
    }
  }

  return (
    <article
      className={cn(
        'cv-auto rounded-card bg-panel p-3 md:p-4',
        'motion-safe:animate-in motion-safe:duration-(--dur-2) motion-safe:fade-in',
        className
      )}
      // An intrinsic size so `content-visibility: auto` does not collapse an
      // off-screen card to zero and destroy the scroll position.
      style={{ containIntrinsicSize: 'auto 200px' }}
    >
      <header className="mb-2 flex items-center gap-2">
        <Avatar expert={expert} size={20} />
        <span className="min-w-0 truncate text-sm font-medium text-fg">{displayName(expert)}</span>
        {hasContradiction && (
          <Explained
            label="Disputed"
            tone="warn"
            explanation="Sources this expert read were judged to disagree about something in this answer. Open the citations to see which says what."
          />
        )}
        {(interrupted || cutShort) && (
          <Explained
            label={interrupted ? 'Interrupted' : 'Cut short'}
            tone="muted"
            explanation={
              interrupted
                ? 'This answer stopped before it finished — the connection dropped or it was stopped. Ask again for a complete answer.'
                : 'This answer ends mid-sentence, so part of it is missing. Ask again for a complete answer.'
            }
          />
        )}
      </header>

      <div className="text-base leading-relaxed text-fg-2">
        {completed.map((block, index) => (
          <MarkdownWithCitations
            key={index}
            source={block}
            citations={numbered}
            dangling={dangling}
            onSelect={onSelectCitation}
            selected={selectedCitation}
          />
        ))}
        {trailing !== null &&
          (closeOpenMarkdown(trailing).trim() ? (
            // The caret is drawn by `.md-caret` at the end of the last
            // paragraph or list item, wherever the Markdown put it.
            <div className="md-caret">
              <MarkdownWithCitations
                source={closeOpenMarkdown(trailing)}
                citations={numbered}
                dangling={dangling}
                onSelect={onSelectCitation}
                selected={selectedCitation}
              />
            </div>
          ) : (
            <span
              aria-hidden="true"
              className="animate-caret inline-block h-[1em] w-[2px] translate-y-[0.15em] bg-expert"
            />
          ))}
      </div>

      {cutShort && onRegenerate && (
        <p className="mt-3 text-sm text-fg-3">
          This answer stops mid-sentence.{' '}
          <button
            type="button"
            onClick={onRegenerate}
            className="text-fg underline underline-offset-2"
          >
            Ask again
          </button>
        </p>
      )}

      {citations.length > 0 && (
        <details className="group mt-3">
          <summary className="cursor-pointer list-none text-xs text-fg-3 transition-colors duration-(--dur-1) hover:text-fg-2">
            {/* Passages, because that is what each [n] opens — several can come
                from one source. */}
            {citations.length} {citations.length === 1 ? 'passage' : 'passages'} cited
          </summary>
          <CitationList
            citations={numbered}
            onSelect={onSelectCitation}
            selected={selectedCitation}
            className="mt-2"
          />
        </details>
      )}

      {/* Spacing, not a rule, between the answer and its actions: the actions
          are the only row of icons in the card, and a hairline across every
          answer in a long conversation is a page ruled like a ledger. */}
      {!streaming && (
        <footer className="mt-3 flex items-center gap-1">
          <IconAction onClick={() => void copy()} label={copied ? 'Copied' : 'Copy'}>
            {copied ? <Check className="size-3.5 text-ok" /> : <Copy className="size-3.5" />}
          </IconAction>
          {onRegenerate && (
            // "Ask again", not "Regenerate": it asks the question as a new turn
            // rather than replacing this answer, and the label should say so.
            <IconAction onClick={onRegenerate} label="Ask again">
              <RotateCcw className="size-3.5" />
            </IconAction>
          )}
          {audit && (
            <IconAction
              onClick={() => setShowTrail((v) => !v)}
              label={showTrail ? 'Hide how this was answered' : 'Show how this was answered'}
              expanded={showTrail}
            >
              <ScrollText className="size-3.5" />
            </IconAction>
          )}
        </footer>
      )}

      {audit && (
        <Collapse open={showTrail}>
          <RetrievalTrail audit={audit} />
        </Collapse>
      )}
    </article>
  )
}

/**
 * A Markdown block whose text nodes have `[n]` markers turned into chips.
 *
 * Markdown first, then citations inside the text — the other way round would
 * put React elements into the Markdown source and they would be escaped.
 */
function MarkdownWithCitations({
  source,
  citations,
  dangling,
  onSelect,
  selected,
}: {
  source: string
  citations: Citation[]
  dangling: number[]
  onSelect: (citation: Citation) => void
  selected: number | null
}) {
  // No markers in this block: the memoised Markdown path, which is the common
  // case and the one that has to stay cheap.
  if (!/\[\d{1,3}\]/.test(source)) return <Block source={source} />

  return (
    <CitedBlock
      source={source}
      citations={citations}
      dangling={dangling}
      onSelect={onSelect}
      selected={selected}
    />
  )
}

/** `[n]` → a Markdown link to `#cite-n`, unless it already is a link's text. */
const CITE_MARKER = /\[(\d{1,3})\](?!\()/g
const CITE_HREF = /^#cite-(\d{1,3})$/

/**
 * A block with citation markers, still parsed as Markdown.
 *
 * It used to be rendered as one plain paragraph so the chips could be spliced
 * into the text — which printed every bold lead-in and list in a cited block
 * as literal `**` and `-`, and answers cite in almost every paragraph. Instead
 * each marker becomes a link to `#cite-n` and the `a` renderer draws the chip,
 * so the Markdown and the citations both survive.
 */
function CitedBlock({
  source,
  citations,
  dangling,
  onSelect,
  selected,
}: {
  source: string
  citations: Citation[]
  dangling: number[]
  onSelect: (citation: Citation) => void
  selected: number | null
}) {
  // Kept stable across the parent's renders, so a streamed token does not
  // re-parse every cited block above it: `onSelect` is a fresh closure and
  // `dangling` a fresh `[]` on each render, so neither may be a dependency.
  const select = useRef(onSelect)
  useEffect(() => {
    select.current = onSelect
  })
  const danglingKey = dangling.join(',')

  const components = useMemo(
    () => ({
      ...COMPONENTS,
      a: (props: { href?: string; children?: React.ReactNode }) => {
        const cite = props.href ? CITE_HREF.exec(props.href) : null
        if (!cite) return COMPONENTS.a(props)
        return (
          <CitedText
            text={`[${cite[1]}]`}
            citations={citations}
            dangling={danglingKey ? danglingKey.split(',').map(Number) : []}
            onSelect={(citation) => select.current(citation)}
            selected={selected}
          />
        )
      },
    }),
    [citations, danglingKey, selected]
  )

  return <Block source={source.replace(CITE_MARKER, '[$1](#cite-$1)')} components={components} />
}

function IconAction({
  onClick,
  label,
  expanded,
  children,
}: {
  onClick: () => void
  label: string
  expanded?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-expanded={expanded}
      title={label}
      className="grid size-(--icon-btn) place-items-center rounded-row text-fg-3 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
    >
      {children}
    </button>
  )
}

/**
 * The answer's retrieval trail.
 *
 * Rendered as counts with the passages behind them — "grounded in 6 of 23
 * retrieved passages". Deliberately **not** as a grounding or faithfulness
 * percentage: there is no calibration set behind such a number, so it would be
 * a fabrication dressed as a metric (audit-api.md is explicit about this).
 */
function RetrievalTrail({ audit }: { audit: ChatRetrievalAuditEvent }) {
  const considered = audit.passages_considered
  const cited = audit.passages_cited

  return (
    <div className="mt-3 space-y-2 text-xs text-fg-3">
      {typeof considered === 'number' && typeof cited === 'number' && (
        <p>
          Grounded in <span className="text-fg-2">{cited}</span> of{' '}
          <span className="text-fg-2">{considered}</span> retrieved passages.
        </p>
      )}
      {Array.isArray(audit.subqueries) && audit.subqueries.length > 0 && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">Searched for</p>
          <ul className="mt-0.5 space-y-0.5">
            {audit.subqueries.map((query) => (
              <li key={query} className="font-mono text-fg-3">
                {query}
              </li>
            ))}
          </ul>
        </div>
      )}
      {audit.coverage_verdict && (
        <p>
          <span className="text-fg-3">Coverage: </span>
          {audit.coverage_verdict}
        </p>
      )}
      {Array.isArray(audit.follow_ups) && audit.follow_ups.length > 0 && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">Follow-ups</p>
          <ul className="mt-0.5 space-y-0.5">
            {audit.follow_ups.map((query) => (
              <li key={query} className="font-mono text-fg-3">
                {query}
              </li>
            ))}
          </ul>
        </div>
      )}
      {audit.persisted === false && (
        <p className="text-fg-3">
          This trail was not persisted — it is available for this session only.
        </p>
      )}
    </div>
  )
}

/** A small status chip whose meaning is a tap or a hover away — never hover-only. */
function Explained({
  label,
  tone,
  explanation,
}: {
  label: string
  tone: 'warn' | 'muted'
  explanation: string
}) {
  return (
    <PopoverRoot>
      <PopoverTrigger
        render={
          // The button is the hit area — 44px tall under a coarse pointer — and
          // the small pill inside it is what shows, so the header keeps its size
          // on a mouse and a thumb still has something to hit.
          <button
            type="button"
            className="group/chip inline-flex shrink-0 items-center pointer-coarse:min-h-11"
          >
            <span
              className={cn(
                'rounded-chip px-1.5 text-xs transition-colors duration-(--dur-1)',
                tone === 'warn'
                  ? 'bg-warn/12 text-warn group-hover/chip:bg-warn/20'
                  : 'bg-raised text-fg-2 group-hover/chip:bg-border'
              )}
            >
              {label}
            </span>
          </button>
        }
      />
      <PopoverContent side="bottom">
        <p className="max-w-64 text-xs leading-relaxed text-fg-2">{explanation}</p>
      </PopoverContent>
    </PopoverRoot>
  )
}

/**
 * True when the answer's last block is prose that stops without finishing its
 * sentence. Lists, tables, code and headings legitimately end without a full
 * stop, so only a closing paragraph is judged.
 */
export function endsMidSentence(content: string): boolean {
  const blocks = splitBlocks(content.trim())
  const last = blocks[blocks.length - 1]?.trim() ?? ''
  if (!last || /^(```|~~~|#|\||>|[-*+]\s|\d+[.)]\s)/.test(last)) return false
  // Drop trailing citation markers and emphasis, then look at the final character.
  const tail = last.replace(/(\s*\[\d{1,3}\])+\s*$/, '').replace(/[*_`)\]"'’”]+$/, '')
  return /[\p{L}\p{N},;:—–-]$/u.test(tail)
}
