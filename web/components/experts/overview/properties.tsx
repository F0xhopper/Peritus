'use client'

import Link from 'next/link'

import { Property } from '@/components/experts/overview/section'
import { DateText } from '@/components/ui/relative-time'
import { StatusDot, dotState, stateLabel, statusTextClass } from '@/components/ui/status-dot'
import { depthHint } from '@/lib/build/copy'
import { formatInt, humanise } from '@/lib/format'
import type { BuildStatus, ExpertWithCatalog } from '@/lib/api/types'

/**
 * What this expert *is*, as a definition list.
 *
 * Status and Depth always; the corpus rows only when there is a corpus to
 * count. **A failed or still-building expert shows neither** — a failed expert
 * has no sources to have assembled, and "Sources 0 · Passages 0" under a
 * running build is a fabricated zero, which is the one thing this product's
 * numbers may never be (web-production.md, rule 2). From `chat_ready` the
 * counts are real and can show.
 *
 * Status is one row, not two. It used to be "Status: Ready" above "Readiness:
 * Graph-ready — retrieval expands with concepts", which read as the same fact
 * said twice.
 *
 * **The counts are links.** The Knowledge page's List and Map are behind those
 * numbers, and a number that is a dead end invites reading it as the whole
 * story. Last built goes to the build it came from, which is otherwise
 * unreachable once the build has finished.
 */
export function OverviewProperties({
  expert,
  buildStatus,
  failed,
}: {
  expert: ExpertWithCatalog
  buildStatus: BuildStatus | null
  failed: boolean
}) {
  const state = dotState(expert.status, expert.readiness, expert.build_active)
  const statusText =
    state === 'ready' && expert.readiness === 'graph_ready'
      ? 'Ready · concept map built'
      : stateLabel(state)
  const building = state === 'queued' || state === 'building'
  const inFlight = building || state === 'chat-ready'
  const showCorpus = !failed && !building
  const base = `/experts/${expert.name}`
  // `updated_at` on the job is when the build stopped; `created_at` on the
  // expert is when someone typed the topic, which a rebuild leaves behind.
  const builtAt = buildStatus?.updated_at ?? expert.created_at

  return (
    <dl className="mt-6 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
      <Property label="Status">
        <span className="inline-flex items-center gap-1.5">
          <StatusDot state={state} />
          <span className={statusTextClass[state]}>{statusText}</span>
        </span>
        {/* While it runs, the status is also the way to watch it. */}
        {inFlight && buildStatus && (
          <>
            <span aria-hidden="true" className="mx-1.5 text-fg-4">
              ·
            </span>
            <PropertyLink href={`${base}/build`}>View build</PropertyLink>
          </>
        )}
      </Property>
      <Property label="Depth">
        <span className="text-fg-2">{humanise(expert.tier)}</span>
        <span className="ml-1.5 text-xs text-fg-3">{depthHint(expert.tier)}</span>
      </Property>
      {showCorpus && (
        <>
          <Property label="Sources">
            <PropertyLink href={`${base}/knowledge?view=list`}>
              {formatInt(expert.source_count)}
            </PropertyLink>
          </Property>
          <Property label="Passages">
            <span className="text-fg-2">{formatInt(expert.chunk_count)}</span>
          </Property>
          {/* Not "Concepts": `node_count` is every node in the graph, and two
              thirds of those are claims — sentences. The map counts concepts. */}
          {expert.node_count > 0 && (
            <Property label="Graph">
              <PropertyLink href={`${base}/knowledge?view=map`}>
                {formatInt(expert.node_count)}
                <span className="text-fg-3">
                  {' concepts and claims · '}
                  {formatInt(expert.edge_count)} links
                </span>
              </PropertyLink>
            </Property>
          )}
        </>
      )}
      <Property label={buildStatus ? 'Last built' : 'Created'}>
        {buildStatus ? (
          <PropertyLink href={`${base}/build`}>
            <DateText iso={builtAt} />
          </PropertyLink>
        ) : (
          <DateText iso={builtAt} className="text-fg-2" />
        )}
      </Property>
    </dl>
  )
}

/** A value that is also a way in. Underlined on hover only, as the concepts are. */
function PropertyLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="text-fg-2 underline-offset-2 transition-colors duration-(--dur-1) hover:text-fg hover:underline"
    >
      {children}
    </Link>
  )
}
