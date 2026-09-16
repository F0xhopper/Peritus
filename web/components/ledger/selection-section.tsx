import type { SelectionBlock } from '@/lib/api/types'
import { cn } from '@/lib/cn'
import { formatNumber, formatPercent, plural } from '@/lib/format'
import {
  describeChannelStatus,
  describeMustHave,
  describeMustHaveFor,
  ledgerByOutcome,
  mustHaveGroups,
  mustHaveTone,
} from '@/lib/selection'

/**
 * The Sources page's Selection section: what the corpus is made of, whether the
 * plan's must-have works made it in, which searches failed, and what happened
 * to every ranked candidate. All of it comes from the screening-flow report's
 * `selection` block; the arithmetic lives in `lib/selection.ts`.
 */
const TONE_CLASS = { ok: 'text-ok', warn: 'text-warn', bad: 'text-bad' } as const

export function SelectionSection({ selection }: { selection: SelectionBlock | null }) {
  if (!selection) return null

  if (!selection.available) {
    return (
      <section aria-labelledby="selection-heading" className="rounded-card bg-panel p-3 md:p-4">
        <h2 id="selection-heading" className="text-sm font-medium text-fg">
          Selection
        </h2>
        <p className="mt-1 text-xs leading-relaxed text-fg-3">{selection.unavailable_reason}</p>
      </section>
    )
  }

  const corpus = selection.corpus
  const groups = corpus ? mustHaveGroups(corpus) : []
  const failed = Object.entries(selection.failed_channels ?? {})
  const outcomes = selection.candidate_ledger
    ? ledgerByOutcome(selection.candidate_ledger.rows)
    : []

  return (
    <section
      aria-labelledby="selection-heading"
      className="space-y-4 rounded-card bg-panel p-3 md:p-4"
    >
      <h2 id="selection-heading" className="text-sm font-medium text-fg">
        Selection
      </h2>

      {corpus && (
        <div className="space-y-1 text-sm text-fg-2">
          <p>
            {plural(corpus.sources, 'source')}: {formatPercent(corpus.primary_share)} primary,{' '}
            {formatPercent(corpus.secondary_share)} secondary,{' '}
            {formatPercent(corpus.tertiary_share)} tertiary ·{' '}
            {formatPercent(corpus.abstract_only_share)} abstract only
          </p>
          <p className="text-xs text-fg-3">
            {formatNumber(corpus.junk_fetched)} fetched{' '}
            {corpus.junk_fetched === 1 ? 'source was' : 'sources were'} off-topic
            {corpus.concepts_without_primary.length > 0 &&
              ` · no primary source for ${corpus.concepts_without_primary.join(', ')}`}
          </p>
        </div>
      )}

      {groups.map((group) => (
        <div key={group.scope}>
          <h3 className="flex flex-wrap items-baseline gap-x-2 text-label tracking-[0.04em] text-fg-3 uppercase">
            {group.title}
            <span className="tracking-normal normal-case">
              {group.found} of {group.total} found
            </span>
          </h3>
          <ul className="mt-1.5 space-y-1.5">
            {group.works.map((work, index) => {
              const detail = group.scope === 'concept' ? describeMustHaveFor(work) : ''
              return (
                <li
                  key={`${work.title}-${index}`}
                  className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm"
                >
                  <span className="min-w-0">
                    <span className="text-fg">{work.title}</span>
                    {work.author && <span className="text-fg-3"> — {work.author}</span>}
                    {detail && <span className="block text-xs text-fg-3">for {detail}</span>}
                  </span>
                  <span className={cn('shrink-0 text-xs', TONE_CLASS[mustHaveTone(work.status)])}>
                    {describeMustHave(work.status)}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      ))}

      {failed.length > 0 && (
        <p className="text-sm text-warn">
          Searches that failed:{' '}
          {failed.map(([name, status]) => `${name} (${describeChannelStatus(status)})`).join(', ')}
        </p>
      )}

      {outcomes.length > 0 && (
        <div>
          <h3 className="text-label tracking-[0.04em] text-fg-3 uppercase">Ranked candidates</h3>
          <dl className="mt-1.5 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
            {outcomes.map((row) => (
              <div key={row.outcome ?? 'unrecorded'} className="contents">
                <dt className="text-fg-2">{row.label}</dt>
                <dd className="text-right font-mono text-fg">{formatNumber(row.count)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {selection.note && <p className="text-xs leading-relaxed text-fg-3">{selection.note}</p>}
    </section>
  )
}
