'use client'

import { ExternalLink, MessageSquare, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { DateText } from '@/components/ui/relative-time'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { formatNumber, hostOf, humanise } from '@/lib/format'
import type { LedgerSource } from '@/lib/api/types'
import { useApiAction } from '@/hooks/use-api-action'
import { apiVoid } from '@/lib/api/client'

/**
 * One source's record: what it is, what it covers, and how to open it.
 *
 * Everything the card list leaves out lives here — the identifiers, the key
 * claims and the concepts it covers — because none of them is something anyone
 * scans a list for.
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

  const { run: remove, pending: deleting } = useApiAction(
    () =>
      apiVoid(
        `/api/experts/${encodeURIComponent(slug)}/sources/${source.id}`,
        { method: 'DELETE' },
        'Could not remove that source.'
      ),
    {
      error: 'Could not remove that source.',
      onSuccess: () => {
        setConfirming(false)
        onDeleted?.()
      },
      // The caller re-reads the ledger through `onDeleted`.
      refresh: false,
    }
  )

  return (
    <div className="space-y-4 text-sm">
      <div>
        <h3 className="min-w-0 flex-1 font-medium text-fg">{source.title}</h3>
        {source.author && <p className="mt-0.5 text-xs text-fg-3">{source.author}</p>}
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        <Field label="Type">{humanise(source.source_type)}</Field>
        {source.content_type && <Field label="Content">{humanise(source.content_type)}</Field>}
        {source.source_tier && <Field label="Tier">{humanise(source.source_tier)}</Field>}
        {source.difficulty !== null && <Field label="Difficulty">{source.difficulty}</Field>}
        <Field label="Passages">{formatNumber(source.passage_count)}</Field>
        {source.text_chars !== null && (
          <Field label="Characters">{formatNumber(source.text_chars)}</Field>
        )}
        <Field label="Added">
          <DateText iso={source.created_at} />
        </Field>
      </dl>

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
        description="Its passages go too, so answers will stop citing it."
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
