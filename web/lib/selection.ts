import type { CandidateLedgerRow, CorpusComposition, MustHaveStatus } from '@/lib/api/types'

/**
 * The source-selection block of the screening-flow report, shaped for the
 * Sources page. Pure, so the arithmetic is unit-tested rather than trusted to a
 * component.
 */

/** Fetch outcomes in the order a candidate falls through them. */
const OUTCOME_ORDER = [
  'fetched',
  'content_duplicate',
  'failed',
  'capped',
  'below_floor',
  'budget',
  'not_reached',
] as const

const OUTCOME_LABEL: Record<string, string> = {
  fetched: 'Fetched',
  content_duplicate: 'Duplicate of a fetched text',
  failed: 'Download failed',
  capped: 'Over a per-kind cap',
  below_floor: 'Scored under the fetch floor',
  budget: 'Out of budget',
  not_reached: 'Not reached',
}

export function describeFetchOutcome(outcome: string | null): string {
  if (outcome === null) return 'Not recorded'
  return (
    OUTCOME_LABEL[outcome] ?? outcome.replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase())
  )
}

export const MUST_HAVE_LABEL: Record<MustHaveStatus, string> = {
  found_whole: 'Found in full',
  found_sections: 'Named sections found',
  found_partial: 'Only parts found',
  not_found: 'Not found',
}

export function describeMustHave(status: string): string {
  return MUST_HAVE_LABEL[status as MustHaveStatus] ?? status.replace(/_/g, ' ')
}

export type MustHaveEntry = CorpusComposition['must_have'][number]

/**
 * Whether the corpus holds what the plan asked for. The named sections of a
 * long work count: when the plan asks for qq. 90–97 of a treatise, those
 * questions *are* the work it needs.
 */
export function isMustHaveFound(status: string): boolean {
  return status === 'found_whole' || status === 'found_sections'
}

/** Status as colour: found is ok, parts are amber, nothing is red. */
export function mustHaveTone(status: string): 'ok' | 'warn' | 'bad' {
  if (isMustHaveFound(status)) return 'ok'
  return status === 'found_partial' ? 'warn' : 'bad'
}

export interface MustHaveGroup {
  scope: 'overall' | 'concept'
  title: string
  works: MustHaveEntry[]
  found: number
  total: number
}

/**
 * The must-have works split into the topic's canonical works and the primary
 * texts named per concept, each with its "N of M found". An entry without a
 * scope comes from a build before concept primary texts and is canonical. A
 * group with no works is left out.
 */
export function mustHaveGroups(corpus: CorpusComposition): MustHaveGroup[] {
  const works = corpus.must_have ?? []
  const groups: MustHaveGroup[] = [
    { scope: 'overall', title: 'Canonical works', works: [], found: 0, total: 0 },
    { scope: 'concept', title: 'Primary texts for concepts', works: [], found: 0, total: 0 },
  ]
  for (const work of works) {
    const group = groups[work.scope === 'concept' ? 1 : 0]!
    group.works.push(work)
    group.total += 1
    if (isMustHaveFound(work.status)) group.found += 1
  }
  return groups.filter((group) => group.total > 0)
}

/** "3 of 4": how many must-have works the accepted corpus holds, of either scope. */
export function canonicalFound(corpus: CorpusComposition): { found: number; total: number } {
  const works = corpus.must_have ?? []
  return {
    found: works.filter((work) => isMustHaveFound(work.status)).length,
    total: works.length,
  }
}

/** "natural law · I-II qq. 90–97": what a concept-scope entry is the primary text for. */
export function describeMustHaveFor(work: MustHaveEntry): string {
  const concepts = (work.concepts ?? []).filter(Boolean).join(', ')
  const sections = (work.sections ?? '').trim()
  return [concepts, sections].filter(Boolean).join(' · ')
}

/**
 * Candidates by fetch outcome, summed across rounds and triage statuses.
 * Outcomes the ledger does not use are left out rather than listed as zero.
 */
export function ledgerByOutcome(
  rows: CandidateLedgerRow[]
): { outcome: string | null; label: string; count: number }[] {
  const totals = new Map<string | null, number>()
  for (const row of rows) {
    const key = row.fetch_outcome ?? null
    totals.set(key, (totals.get(key) ?? 0) + (Number.isFinite(row.count) ? row.count : 0))
  }
  const rank = (outcome: string | null) => {
    const index = OUTCOME_ORDER.indexOf(outcome as (typeof OUTCOME_ORDER)[number])
    return index === -1 ? OUTCOME_ORDER.length + (outcome === null ? 1 : 0) : index
  }
  return [...totals.entries()]
    .filter(([, count]) => count > 0)
    .sort((a, b) => rank(a[0]) - rank(b[0]))
    .map(([outcome, count]) => ({ outcome, label: describeFetchOutcome(outcome), count }))
}

const CHANNEL_STATUS: Record<string, string> = {
  timeout: 'timed out',
  rate_limited: 'rate-limited',
  error: 'failed',
  empty: 'found nothing',
  skipped: 'skipped',
}

/** A fetcher status as the build log and the Sources page both phrase it. */
export function describeChannelStatus(status: string): string {
  return CHANNEL_STATUS[status] ?? status.replace(/_/g, ' ')
}
