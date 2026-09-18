'use client'

import { BookOpen, Expand, List, Map as MapIcon, MessageSquare, Plus } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useState } from 'react'

import { RowDetail } from '@/components/ledger/row-detail'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { apiJson, messageFor } from '@/lib/api/client'
import { cn } from '@/lib/cn'
import { formatNumber, humanise } from '@/lib/format'
import { sourceKind } from '@/lib/source-kind'
import type {
  ConceptDepth,
  LedgerSource,
  MapClaim,
  MapConceptDetail,
  MapResponse,
} from '@/lib/api/types'
import type { BrainSelection } from '@/lib/brain/selection'

/**
 * The Knowledge page's right-hand panel, in its four forms — identical in the
 * Map and the List view (docs/plans/expert-brain.md, "The page").
 *
 * Every panel links onward to the others, which is the whole point of joining
 * the two pages: a source names the concepts drawn from it, a concept names the
 * sources that say it, and a key concept names both. Before this the concept
 * panel's one bridge to the sources — "Sources covering this" — matched a node
 * label against a key concept, which happened for no node in any expert, so
 * the button never rendered.
 */

const DEPTH_WORD: Record<ConceptDepth, string> = {
  sets_out: 'Sets out',
  treats: 'Treats',
  mentions: 'Mentions',
}

/** A list inside a panel: a heading and rows that each select something. */
function Section({
  title,
  children,
  tone,
}: {
  title: string
  children: React.ReactNode
  tone?: 'warn'
}) {
  return (
    <div>
      <p
        className={cn(
          'text-label tracking-[0.04em] uppercase',
          tone === 'warn' ? 'text-warn' : 'text-fg-3'
        )}
      >
        {title}
      </p>
      <div className="mt-1">{children}</div>
    </div>
  )
}

function RowButton({
  onClick,
  children,
  meta,
}: {
  onClick: () => void
  children: React.ReactNode
  meta?: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-(--row-h) w-full items-center gap-2 rounded-row px-1 text-left text-xs text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg pointer-fine:min-h-7"
    >
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {meta !== undefined && <span className="shrink-0 text-fg-3">{meta}</span>}
    </button>
  )
}

// ── source ──────────────────────────────────────────────────────────────────

export function SourcePanel({
  sourceId,
  ledger,
  map,
  slug,
  owner,
  asking,
  onAsk,
  onDeleted,
  onSelect,
}: {
  sourceId: number
  /** The source's full record from the list, when it is on the loaded page. */
  ledger: LedgerSource | null
  map: MapResponse | null
  slug: string
  owner: boolean
  asking: boolean
  onAsk: (title: string) => void
  onDeleted?: () => void
  onSelect: (selection: BrainSelection) => void
}) {
  const mapSource = map?.sources.find((source) => source.id === sourceId) ?? null
  const concepts = (map?.concepts ?? [])
    .filter((concept) => concept.source_ids.includes(sourceId))
    .sort((a, b) => b.source_ids.length - a.source_ids.length || a.label.localeCompare(b.label))

  if (!ledger && !mapSource) {
    return <p className="text-sm text-fg-3">This source is not part of this expert any more.</p>
  }

  return (
    <div className="space-y-4 text-sm">
      {ledger ? (
        <RowDetail
          source={ledger}
          slug={slug}
          owner={owner}
          asking={asking}
          onAsk={onAsk}
          onDeleted={onDeleted}
        />
      ) : (
        mapSource && (
          <div>
            <h3 className="font-medium text-fg">{mapSource.title}</h3>
            <p className="mt-0.5 text-xs text-fg-3">
              {[
                mapSource.author,
                sourceKind(mapSource.kind),
                `${formatNumber(mapSource.passage_count)} passages`,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </div>
        )
      )}

      {mapSource && mapSource.tags.length > 0 && map && (
        <Section title="Key concepts">
          {mapSource.tags.map((tag) => (
            <RowButton
              key={tag.key_concept}
              onClick={() => onSelect({ kind: 'keyConcept', index: tag.key_concept })}
              meta={DEPTH_WORD[tag.depth]}
            >
              {map.syllabus.key_concepts[tag.key_concept]?.label}
            </RowButton>
          ))}
        </Section>
      )}

      {map?.computed && (
        <Section title="Concepts from this source">
          {concepts.length === 0 ? (
            <p className="px-1 text-xs text-fg-3">
              None of the concepts on the map were drawn from this source alone or with others.
            </p>
          ) : (
            <>
              {concepts.slice(0, 20).map((concept) => (
                <RowButton
                  key={concept.id}
                  onClick={() => onSelect({ kind: 'concept', id: concept.id })}
                  meta={
                    concept.source_ids.length > 1
                      ? `${concept.source_ids.length} sources`
                      : undefined
                  }
                >
                  {concept.label}
                </RowButton>
              ))}
              {concepts.length > 20 && (
                <p className="mt-0.5 px-1 text-xs text-fg-3">+{concepts.length - 20} more</p>
              )}
            </>
          )}
        </Section>
      )}
    </div>
  )
}

// ── concept ─────────────────────────────────────────────────────────────────

/**
 * A concept in the cloud. Its claims are the heavy part of the map and only one
 * concept is ever open, so they are fetched here rather than shipped with it.
 */
export function ConceptPanel({
  conceptId,
  map,
  slug,
  asking,
  onAsk,
  onSelect,
}: {
  conceptId: number
  map: MapResponse | null
  slug: string
  asking: boolean
  onAsk: (text: string) => void
  onSelect: (selection: BrainSelection) => void
}) {
  const [state, setState] = useState<{
    id: number
    detail: MapConceptDetail | null
    error: string | null
  } | null>(null)

  useEffect(() => {
    let current = true
    apiJson<MapConceptDetail>(
      `/api/experts/${encodeURIComponent(slug)}/map/concepts/${conceptId}`,
      {},
      'Could not load this concept.'
    )
      .then((detail) => {
        if (current) setState({ id: conceptId, detail, error: null })
      })
      .catch((error: unknown) => {
        if (current) {
          setState({
            id: conceptId,
            detail: null,
            error: messageFor(error, 'Could not load this concept.'),
          })
        }
      })
    return () => {
      current = false
    }
  }, [slug, conceptId])

  const onMap = new Set((map?.concepts ?? []).map((concept) => concept.id))
  const drawn = map?.concepts.find((concept) => concept.id === conceptId) ?? null
  const loaded = state?.id === conceptId ? state : null
  const detail = loaded?.detail ?? null
  const label = detail?.label ?? drawn?.label ?? 'Concept'
  const keyIndex = detail?.key_concept ?? drawn?.key_concept ?? null
  const keyConcept = keyIndex !== null ? map?.syllabus.key_concepts[keyIndex] : undefined

  return (
    <div className="space-y-4 text-sm">
      <div>
        <h3 className="font-medium text-fg">{label}</h3>
        {keyConcept ? (
          <button
            type="button"
            onClick={() => onSelect({ kind: 'keyConcept', index: keyConcept.index })}
            className="mt-0.5 text-left text-xs text-fg-3 underline decoration-fg-4 underline-offset-2 hover:text-fg-2"
          >
            {keyConcept.label}
          </button>
        ) : (
          <p className="mt-0.5 text-xs text-fg-3">In no key concept of the syllabus</p>
        )}
      </div>

      {loaded?.error && <p className="text-xs text-bad">{loaded.error}</p>}

      {!loaded && (
        <div className="space-y-2" aria-hidden="true">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-4/5" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      )}

      {detail?.description && (
        <p className="text-xs leading-relaxed text-fg-2">{detail.description}</p>
      )}

      {detail && (
        <Section title="Said by">
          {detail.sources.length === 0 ? (
            <p className="px-1 text-xs text-fg-3">No kept source discusses this any more.</p>
          ) : (
            detail.sources.map((source) => (
              <RowButton
                key={source.id}
                onClick={() => onSelect({ kind: 'source', id: source.id })}
                meta={`${source.passages} ${source.passages === 1 ? 'passage' : 'passages'}`}
              >
                {source.title}
              </RowButton>
            ))
          )}
        </Section>
      )}

      {detail && detail.claims.length > 0 && (
        <Section title={detail.disputes > 0 ? 'Claims — some judged to disagree' : 'Claims'}>
          <ul className="space-y-2.5">
            {detail.claims.slice(0, 12).map((claim) => (
              <ClaimItem key={claim.id} claim={claim} slug={slug} />
            ))}
          </ul>
          {detail.claims.length > 12 && (
            <p className="mt-1 text-xs text-fg-3">+{detail.claims.length - 12} more claims</p>
          )}
        </Section>
      )}

      {detail && detail.part_of.length > 0 && (
        <Section title="Part of, and parts">
          {detail.part_of.map((other) => (
            <RowButton
              key={`${other.relation}:${other.id}`}
              onClick={() => onSelect({ kind: 'concept', id: other.id })}
              meta={other.relation === 'whole' ? 'whole' : 'part'}
            >
              <span className={onMap.has(other.id) ? undefined : 'text-fg-3'}>{other.label}</span>
            </RowButton>
          ))}
        </Section>
      )}

      <div className="flex flex-wrap gap-2 border-t border-border-soft pt-3">
        <Button
          variant="outline"
          size="sm"
          loading={asking}
          onClick={() => onAsk(`What do the sources say about ${label}?`)}
        >
          <MessageSquare className="size-3" />
          Ask about this
        </Button>
      </div>
    </div>
  )
}

/**
 * One claim, with the sources that state it and what it was judged to disagree
 * with. The wording is careful on purpose: "judged to disagree", in *this*
 * corpus — never "contradictions in the literature".
 */
function ClaimItem({ claim, slug }: { claim: MapClaim; slug: string }) {
  return (
    <li className="text-xs">
      <p className={cn('leading-relaxed', claim.disputed ? 'text-fg' : 'text-fg-2')}>
        {claim.text}
      </p>
      {claim.sources.length > 0 && (
        <p className="mt-0.5 flex flex-wrap gap-x-2 text-fg-3">
          {claim.sources.map((source) => (
            <Link
              key={source.source_id}
              href={`/experts/${slug}/sources/${source.source_id}/read?at=${source.chunk_id}`}
              className="inline-flex max-w-full items-center gap-1 underline decoration-fg-4 underline-offset-2 hover:text-fg-2"
            >
              <BookOpen className="size-3 shrink-0" />
              <span className="truncate">{source.title ?? 'Source'}</span>
            </Link>
          ))}
        </p>
      )}
      {claim.relations.map((relation) => (
        <p
          key={`${relation.type}:${relation.claim_id}`}
          className={cn(
            'mt-1 border-l-2 pl-2 leading-relaxed',
            relation.type === 'contradicts' ? 'border-warn text-fg-2' : 'border-border text-fg-3'
          )}
        >
          <span className={relation.type === 'contradicts' ? 'text-warn' : undefined}>
            {relation.type === 'contradicts'
              ? 'Judged to disagree'
              : relation.type === 'qualifies'
                ? 'Qualified by'
                : 'Supported by'}
            {relation.point ? ` about ${relation.point}` : ''}
            {relation.condition ? ` — when ${relation.condition}` : ''}:
          </span>{' '}
          {relation.text}
        </p>
      ))}
    </li>
  )
}

// ── key concept ─────────────────────────────────────────────────────────────

/** "12 sources; 5 set it out, 7 treat it." */
export function coverageInWords(sources: number, depths: Partial<Record<ConceptDepth, number>>) {
  const head = `${sources} ${sources === 1 ? 'source' : 'sources'}`
  const parts = [
    depths.sets_out ? `${depths.sets_out} ${depths.sets_out === 1 ? 'sets' : 'set'} it out` : null,
    depths.treats ? `${depths.treats} ${depths.treats === 1 ? 'treats' : 'treat'} it` : null,
  ].filter(Boolean)
  return parts.length ? `${head}; ${parts.join(', ')}.` : `${head}.`
}

const NAMED_STATUS: Record<string, string> = {
  found: 'in the sources',
  partial: 'in the sources in part',
  missing: 'not in the sources',
}

export function KeyConceptPanel({
  index,
  map,
  view,
  asking,
  onAsk,
  onShowInList,
  onShowOnMap,
  onExpand,
  onSelect,
}: {
  index: number
  map: MapResponse
  view: 'map' | 'list'
  asking: boolean
  onAsk: (text: string) => void
  onShowInList: () => void
  onShowOnMap: () => void
  onExpand: (() => void) | null
  onSelect: (selection: BrainSelection) => void
}) {
  const concept = map.syllabus.key_concepts[index]
  if (!concept) return null
  const inSector = map.concepts.filter((c) => c.key_concept === index)
  const gaps = map.syllabus.gaps
    .map((gap, i) => ({ gap, i }))
    .filter(({ gap }) => gap.key_concept === index)

  return (
    <div className="space-y-4 text-sm">
      <div>
        <h3 className="font-medium text-fg">{concept.label}</h3>
        <p className="mt-0.5 text-xs text-fg-3">
          {concept.facet ? `${concept.facet} · ` : ''}Key concept
        </p>
      </div>

      <p className="text-xs leading-relaxed text-fg-2">
        {coverageInWords(concept.sources, concept.depth_counts)}{' '}
        {concept.met ? (
          <span className="text-fg-3">That meets this expert&rsquo;s target.</span>
        ) : (
          <span className="text-warn">Short of this expert&rsquo;s target.</span>
        )}
      </p>

      {concept.named_text && (
        <Section title="Named primary text">
          <p className="px-1 text-xs text-fg-2">
            <em>{concept.named_text.title ?? 'A named text'}</em>
            {concept.named_text.author ? ` (${concept.named_text.author})` : ''} —{' '}
            <span className={concept.named_text.status === 'missing' ? 'text-warn' : 'text-fg-3'}>
              {NAMED_STATUS[concept.named_text.status] ?? humanise(concept.named_text.status)}
            </span>
          </p>
          {gaps.map(({ gap, i }) => (
            <RowButton key={i} onClick={() => onSelect({ kind: 'gap', index: i })}>
              Where it would be on the map: {gap.title}
            </RowButton>
          ))}
        </Section>
      )}

      {map.computed && (
        <Section title="In this sector">
          <p className="px-1 text-xs text-fg-3">
            {inSector.length} {inSector.length === 1 ? 'concept' : 'concepts'} on the map.
          </p>
          {inSector
            .slice()
            .sort((a, b) => b.source_ids.length - a.source_ids.length)
            .slice(0, 8)
            .map((c) => (
              <RowButton
                key={c.id}
                onClick={() => onSelect({ kind: 'concept', id: c.id })}
                meta={`${c.source_ids.length} ${c.source_ids.length === 1 ? 'source' : 'sources'}`}
              >
                {c.label}
              </RowButton>
            ))}
        </Section>
      )}

      <div className="flex flex-wrap gap-2 border-t border-border-soft pt-3">
        {view === 'map' ? (
          <Button variant="outline" size="sm" onClick={onShowInList}>
            <List className="size-3" />
            Show in list
          </Button>
        ) : (
          <Button variant="outline" size="sm" onClick={onShowOnMap}>
            <MapIcon className="size-3" />
            Show on map
          </Button>
        )}
        {onExpand && (
          <Button variant="ghost" size="sm" onClick={onExpand}>
            <Expand className="size-3" />
            Every concept here
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          loading={asking}
          onClick={() => onAsk(`What do the sources say about ${concept.label}?`)}
        >
          <MessageSquare className="size-3" />
          Ask about this
        </Button>
      </div>
    </div>
  )
}

// ── gap ─────────────────────────────────────────────────────────────────────

/**
 * A text the plan named and the build never found. For an owner it leads to
 * its own remedy — the single most useful thing on the page.
 */
export function GapPanel({
  index,
  map,
  owner,
  onAdd,
  onSelect,
}: {
  index: number
  map: MapResponse
  owner: boolean
  onAdd: () => void
  onSelect: (selection: BrainSelection) => void
}) {
  const gap = map.syllabus.gaps[index]
  if (!gap) return null
  const concept = gap.key_concept !== null ? map.syllabus.key_concepts[gap.key_concept] : null
  const work = (
    <>
      <em>{gap.title}</em>
      {gap.author ? ` (${gap.author})` : ''}
    </>
  )
  return (
    <div className="space-y-4 text-sm">
      <div>
        <h3 className="font-medium text-fg">{gap.title}</h3>
        <p className="mt-0.5 text-xs text-warn">Not in this expert&rsquo;s sources</p>
      </div>
      <p className="text-xs leading-relaxed text-fg-2">
        {gap.kind === 'named_text' && concept ? (
          <>
            The plan named {work} for{' '}
            <button
              type="button"
              onClick={() => onSelect({ kind: 'keyConcept', index: concept.index })}
              className="underline decoration-fg-4 underline-offset-2 hover:text-fg"
            >
              {concept.label}
            </button>
            . It is not in this expert&rsquo;s sources.
          </>
        ) : (
          <>
            The plan named {work} as a work this expert should read. The build looked for it and did
            not find it.
          </>
        )}
      </p>
      {owner && (
        <div className="border-t border-border-soft pt-3">
          <Button variant="secondary" size="sm" onClick={onAdd}>
            <Plus className="size-3" />
            Add a source
          </Button>
          <p className="mt-1.5 text-xs text-fg-3">
            A file, pasted text or a link. Peritus reads it and decides what it covers.
          </p>
        </div>
      )}
    </div>
  )
}
