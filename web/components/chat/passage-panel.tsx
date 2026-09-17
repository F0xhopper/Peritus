'use client'

import { ExternalLink, MessageSquare } from 'lucide-react'
import Link from 'next/link'

import { PassageContext } from '@/components/chat/passage-context'
import { Button } from '@/components/ui/button'
import { describeDifficulty, describeTextRead, sourceKind } from '@/lib/source-kind'
import { hostOf, humanise } from '@/lib/format'
import type { Citation, LedgerSource } from '@/lib/api/types'

/**
 * The cited passage, in the context panel.
 *
 * **It quotes the passage.** The panel is titled "Cited passage" and for a long
 * time the thing in its blockquote was the citation *label* — which the API
 * built as "Title — Exa · Q:8.5". So the one place in the product that promises
 * to show you the evidence showed a title, a vendor name and a screening score,
 * three times over, and two citations from one source were indistinguishable.
 * The API now sends the passage text; where an older stored answer has none,
 * the source's title is the honest fallback and the blockquote is dropped
 * rather than filled with something that is not a quotation.
 *
 * **The number is the one on the chip.** Chips are numbered per answer (1, 2,
 * 3 in order of first use) while `n` is the retrieval index, so heading this
 * panel with `n` meant clicking **2** and opening "Passage 7".
 *
 * **And the passage is shown in its source.** Where the citation says which
 * chunk it is, the paragraphs either side of it load underneath — see
 * `PassageContext`. That is the difference between quoting the evidence and
 * showing it.
 */
export function PassagePanel({
  citation,
  source,
  slug,
  siblings = [],
  onAsk,
}: {
  citation: Citation
  source: LedgerSource | null
  slug: string
  /** Other citations in this answer from the same source, for "also cited as". */
  siblings?: Citation[]
  onAsk?: (about: string) => void
}) {
  const shown = citation.display ?? citation.n
  const title = source?.title ?? citation.label

  return (
    <div className="space-y-3 text-sm">
      <div>
        <p className="text-label tracking-[0.04em] text-fg-3 uppercase">
          Passage {shown}
          {title && <span className="normal-case"> of {title}</span>}
        </p>
        {citation.text ? (
          // The cited span itself, washed in the expert's colour.
          <blockquote className="mt-1.5 rounded-card bg-expert-soft p-2.5 text-fg-2">
            {citation.text}
          </blockquote>
        ) : (
          <p className="mt-1.5 text-xs text-fg-3">
            This answer was saved before passages were kept with their citations, so the text is not
            here. The source is below.
          </p>
        )}
        {siblings.length > 0 && (
          <p className="mt-1.5 text-xs text-fg-3">
            This source is also cited as{' '}
            {siblings.map((sibling, index) => (
              <span key={sibling.n}>
                {index > 0 && ', '}
                <span className="font-mono text-fg-2">[{sibling.display ?? sibling.n}]</span>
              </span>
            ))}
            .
          </p>
        )}
      </div>

      {source ? (
        <>
          <div>
            <p className="font-medium text-fg">{source.title}</p>
            {source.author && <p className="mt-0.5 text-xs text-fg-3">{source.author}</p>}
          </div>

          {/* One vocabulary with the Sources page: what it *is* comes from
              `sourceKind`, never the fetcher key — this panel used to say
              "Type: Exa", where the table said "Kind: Paper". */}
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
            <Field label="Kind">{sourceKind(source.source_type)}</Field>
            {source.source_tier && (
              <Field label="Tier">{humanise(source.source_tier)} source</Field>
            )}
            {source.full_text_method && (
              <Field label="Read">
                {source.full_text_method === 'abstract' ? (
                  // Worth flagging: an abstract-only source was judged, and is
                  // answering questions, on its abstract alone.
                  <span className="text-warn">Abstract only</span>
                ) : (
                  describeTextRead(source.full_text_method)
                )}
              </Field>
            )}
            {source.difficulty !== null && (
              <Field label="Level">{describeDifficulty(source.difficulty)}</Field>
            )}
            {source.doi && <Field label="DOI">{source.doi}</Field>}
          </dl>

          {/* Older answers carry no `chunk_id`, so there is nothing to centre a
              window on; the quote above stands alone, as it did before. */}
          {citation.chunk_id !== null && citation.chunk_id !== undefined && (
            <PassageContext slug={slug} sourceId={source.id} chunkId={citation.chunk_id} />
          )}

          <div className="flex flex-wrap gap-2">
            {source.url && (
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-(--row-h) items-center gap-1.5 rounded-row border border-border px-2.5 text-xs text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
              >
                <ExternalLink className="size-3" />
                {hostOf(source.url) ?? 'Open'}
              </a>
            )}
            <Link
              href={`/experts/${slug}/sources?source=${source.id}`}
              className="inline-flex h-(--row-h) items-center rounded-row border border-border px-2.5 text-xs text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
            >
              See the source
            </Link>
            {onAsk && (
              <Button variant="outline" size="sm" onClick={() => onAsk(source.title)}>
                <MessageSquare className="size-3" />
                Ask about this
              </Button>
            )}
          </div>
        </>
      ) : (
        <p className="text-xs text-fg-3">
          The full record for this passage&rsquo;s source is on the{' '}
          <Link href={`/experts/${slug}/sources`} className="text-fg underline underline-offset-2">
            Sources page
          </Link>
          .
        </p>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-fg-3">{label}</dt>
      <dd className="truncate text-fg-2">{children}</dd>
    </div>
  )
}
