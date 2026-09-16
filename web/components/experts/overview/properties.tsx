'use client'

import { Property } from '@/components/experts/overview/section'
import { DateText } from '@/components/ui/relative-time'
import { StatusDot, dotState, stateLabel, statusTextClass } from '@/components/ui/status-dot'
import { humanise, plural } from '@/lib/format'
import type { ExpertWithCatalog } from '@/lib/api/types'

/**
 * What this expert *is*, as a definition list.
 *
 * Status and Depth always; the corpus rows only when there is a corpus. **A
 * failed build shows neither** — a failed expert has no sources to have
 * assembled, and rows reading "0 sources" describe a corpus that was never
 * attempted.
 *
 * Status is one row, not two. It used to be "Status: Ready" above "Readiness:
 * Graph-ready — retrieval expands with concepts", which read as the same fact
 * said twice.
 */
export function OverviewProperties({
  expert,
  failed,
}: {
  expert: ExpertWithCatalog
  failed: boolean
}) {
  const state = dotState(expert.status, expert.readiness, expert.build_active)
  const statusText =
    state === 'ready' && expert.readiness === 'graph_ready'
      ? 'Ready · concept map built'
      : stateLabel(state)

  return (
    <dl className="mt-6 grid grid-cols-1 gap-x-6 gap-y-2 text-sm min-[480px]:grid-cols-[auto_1fr]">
      <Property label="Status">
        <span className="inline-flex items-center gap-1.5">
          <StatusDot state={state} />
          <span className={statusTextClass[state]}>{statusText}</span>
        </span>
      </Property>
      <Property label="Depth">
        <span className="text-fg-2">{humanise(expert.tier)}</span>
      </Property>
      {!failed && (
        <>
          <Property label="Sources">
            <span className="text-fg-2">{expert.source_count}</span>
          </Property>
          <Property label="Passages">
            <span className="text-fg-2">{expert.chunk_count}</span>
          </Property>
          {expert.node_count > 0 && (
            <Property label="Concepts">
              <span className="text-fg-2">
                {plural(expert.node_count, 'concept')} · {plural(expert.edge_count, 'link')}
              </span>
            </Property>
          )}
        </>
      )}
      <Property label="Built">
        <DateText iso={expert.created_at} className="text-fg-2" />
      </Property>
    </dl>
  )
}
