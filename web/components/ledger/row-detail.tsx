'use client'

import { ExternalLink, MessageSquare, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { DateText } from '@/components/ui/relative-time'
import { Button } from '@/components/ui/button'
import { Chip } from '@/components/ui/chip'
import { Dialog } from '@/components/ui/dialog'
import { cn } from '@/lib/cn'
import { describeDiscovery, describeTextRead, sourceProvider } from '@/lib/source-kind'
import { formatNumber, formatScore, hostOf, humanise } from '@/lib/format'
import type { LedgerSource } from '@/lib/api/types'

/**
 * One source's full record.
 *
 * The two fields the card list leaves out — rubric version and the identifiers
 * — live here, along with the parts of the trail that only matter once you have
 * picked a row: which search found it, what it was first scored at before
 * review, and how much of its text was actually read.
 *
 * Two provenance details are called out rather than listed flatly, because
 * they change how a reader should weigh the row:
 *
 * - **A reviewed row is not a less reliable row.** It is the one place in the
 *   ledger where a borderline decision was made twice, by a stronger model
 *   reading far more of the source.
 * - **A duplicate's zeros are not a quality verdict.** A source dropped by
 *   fingerprinting was never judged on merit.
 */
export function RowDetail({
  source,
  slug,
  onAsk,
  onDeleted,
}: {
  source: LedgerSource
  slug: string
  onAsk?: (title: string) => void
  /** Present only for the owner. Without it there is no Remove button. */
  onDeleted?: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const isDuplicate = source.drop_reason?.startsWith('duplicate of') ?? false

  const remove = async () => {
    setDeleting(true)
    try {
      const res = await fetch(`/api/experts/${encodeURIComponent(slug)}/sources/${source.id}`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error()
      setConfirming(false)
      onDeleted?.()
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="flex items-start justify-between gap-2">
          <h3 className="min-w-0 flex-1 font-medium text-fg">{source.title}</h3>
          {source.decision === 'accepted' ? (
            <Chip tone="ok">Kept</Chip>
          ) : (
            <Chip tone="bad">Dropped</Chip>
          )}
        </div>
        {source.author && <p className="mt-0.5 text-xs text-fg-3">{source.author}</p>}
      </div>

      {source.drop_reason && (
        <div className={cn('rounded-card px-2.5 py-2', isDuplicate ? 'bg-raised' : 'bg-bad/8')}>
          <p className={cn('text-xs', isDuplicate ? 'text-fg-3' : 'text-bad')}>
            {source.drop_reason}
          </p>
          {isDuplicate && (
            <p className="mt-1 text-xs text-fg-3">
              Dropped by content fingerprinting, so its zero scores are not a quality verdict — it
              was never judged on merit.
            </p>
          )}
        </div>
      )}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        <Field label="Type">{humanise(source.source_type)}</Field>
        {source.content_type && <Field label="Content">{humanise(source.content_type)}</Field>}
        <Field label="Quality">{formatScore(source.quality_score)}</Field>
        <Field label="Relevance">{formatScore(source.relevance_score)}</Field>
        {source.source_tier && <Field label="Tier">{humanise(source.source_tier)}</Field>}
        {source.difficulty !== null && <Field label="Difficulty">{source.difficulty}</Field>}
        <Field label="Passages">{formatNumber(source.passage_count)}</Field>
        {source.text_chars !== null && (
          <Field label="Characters">{formatNumber(source.text_chars)}</Field>
        )}
        <Field label="Added">
          <DateText iso={source.created_at} />
        </Field>
        {source.rubric_version && <Field label="Screening rules">{source.rubric_version}</Field>}
      </dl>

      {source.reviewed && (
        <div className="rounded-card bg-raised px-2.5 py-2">
          <p className="text-xs font-medium text-fg-2">Reviewed a second time</p>
          <p className="mt-1 text-xs text-fg-3">
            First pass scored q{formatScore(source.first_pass_quality)} r
            {formatScore(source.first_pass_relevance)}; {source.review_model ?? 'a stronger model'}{' '}
            re-read it and settled on q{formatScore(source.quality_score)} r
            {formatScore(source.relevance_score)}. The second verdict stands.
          </p>
        </div>
      )}

      {source.full_text_method && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">Text read</p>
          <p className="mt-1 text-xs">
            {source.full_text_method === 'abstract' ? (
              <span className="text-warn">
                Abstract only — this source was judged, and answers questions, on its abstract.
              </span>
            ) : (
              <span className="text-fg-2">{describeTextRead(source.full_text_method)}</span>
            )}
          </p>
        </div>
      )}

      {source.discovered_via && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">How it was found</p>
          <p className="mt-1 text-xs text-fg-2">
            {describeDiscovery(source.discovered_via)} · via {sourceProvider(source.source_type)}
          </p>
          {source.gap_filled_for_concept && (
            <p className="mt-1 text-xs text-fg-3">
              This search ran only because{' '}
              <span className="text-fg">{source.gap_filled_for_concept}</span> had no accepted
              source yet.
            </p>
          )}
          {source.snowball_seed_urls && source.snowball_seed_urls.length > 0 && (
            <p className="mt-1 text-xs text-fg-3">
              Followed from {source.snowball_seed_urls.length} citing source
              {source.snowball_seed_urls.length === 1 ? '' : 's'}.
            </p>
          )}
        </div>
      )}

      {source.covered_concepts.length > 0 && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">Covers</p>
          <p className="mt-1 text-xs leading-relaxed">
            {source.covered_concepts.map((concept, index) => (
              <span key={concept}>
                {index > 0 && <span className="text-fg-4"> · </span>}
                <span className="text-fg">{concept}</span>
              </span>
            ))}
          </p>
        </div>
      )}

      {source.key_claims.length > 0 && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">Key claims</p>
          <ul className="mt-1 space-y-1 text-xs text-fg-2">
            {source.key_claims.map((claim, index) => (
              <li key={index} className="flex gap-1.5">
                <span aria-hidden="true" className="text-fg-4">
                  ·
                </span>
                <span className="min-w-0 flex-1">{claim}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(source.doi || source.arxiv_id || source.identifiers) && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">Identifiers</p>
          <dl className="mt-1 space-y-0.5 font-mono text-xs">
            {source.doi && (
              <div className="flex gap-2">
                <dt className="text-fg-3">doi</dt>
                <dd className="min-w-0 truncate text-fg-2">{source.doi}</dd>
              </div>
            )}
            {source.arxiv_id && (
              <div className="flex gap-2">
                <dt className="text-fg-3">arxiv</dt>
                <dd className="text-fg-2">{source.arxiv_id}</dd>
              </div>
            )}
            {source.identifiers &&
              Object.entries(source.identifiers)
                .filter(([key]) => key !== 'doi')
                .map(([key, value]) => (
                  <div key={key} className="flex gap-2">
                    <dt className="text-fg-3">{key}</dt>
                    <dd className="min-w-0 truncate text-fg-2">{value}</dd>
                  </div>
                ))}
          </dl>
        </div>
      )}

      <div className="flex flex-wrap gap-2 border-t border-border-soft pt-3">
        {source.url && (
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-(--row-h) items-center gap-1.5 rounded-row border border-border px-2.5 text-xs text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
          >
            <ExternalLink className="size-3" />
            {hostOf(source.url) ?? 'Open source'}
          </a>
        )}
        {onAsk && (
          <Button variant="outline" size="sm" onClick={() => onAsk(source.title)}>
            <MessageSquare className="size-3" />
            Ask about this
          </Button>
        )}
        {onDeleted && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setConfirming(true)}
            className="text-bad"
          >
            <Trash2 className="size-3" />
            Remove
          </Button>
        )}
      </div>

      <Dialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Remove this source?"
        description="Its passages go too, so answers will stop citing it. The build's screening record keeps the row."
        disablePointerDismissal
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Keep it
            </Button>
            <Button variant="danger" loading={deleting} onClick={() => void remove()} minWidth={92}>
              Remove
            </Button>
          </>
        }
      >
        <p className="text-sm text-fg-3">{source.title}</p>
      </Dialog>
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
