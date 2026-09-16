'use client'

import { ExternalLink, MessageSquare } from 'lucide-react'
import Link from 'next/link'

import { Button } from '@/components/ui/button'
import { hostOf, humanise } from '@/lib/format'
import type { Citation, LedgerSource } from '@/lib/api/types'

/**
 * The cited passage, in the context panel.
 *
 * The citation label the stream sends is the passage's own text plus its
 * source's title; the source row behind it is fetched by the page and passed in
 * where it is known. Where it is not, the label alone is still worth showing:
 * a citation that opens nothing is worse than a citation that opens a quote.
 */
export function PassagePanel({
  citation,
  source,
  slug,
  onAsk,
}: {
  citation: Citation
  source: LedgerSource | null
  slug: string
  onAsk?: (about: string) => void
}) {
  return (
    <div className="space-y-3 text-sm">
      <div>
        <p className="text-label tracking-[0.04em] text-fg-3 uppercase">Passage {citation.n}</p>
        {/* The cited span itself, washed in the expert's colour. */}
        <blockquote className="mt-1.5 rounded-card bg-expert-soft p-2.5 text-fg-2">
          {citation.label}
        </blockquote>
      </div>

      {source ? (
        <>
          <div>
            <p className="font-medium text-fg">{source.title}</p>
            {source.author && <p className="mt-0.5 text-xs text-fg-3">{source.author}</p>}
          </div>

          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
            <Field label="Type">{humanise(source.source_type)}</Field>
            {source.source_tier && <Field label="Tier">{humanise(source.source_tier)}</Field>}
            {source.doi && <Field label="DOI">{source.doi}</Field>}
          </dl>

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
              View in Sources
            </Link>
            {onAsk && (
              <Button variant="ghost" size="sm" onClick={() => onAsk(source.title)}>
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
