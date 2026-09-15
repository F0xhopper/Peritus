'use client'

import { useVirtualizer } from '@tanstack/react-virtual'
import { ArrowDown, Check, ChevronRight, X } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { cn } from '@/lib/cn'
import { formatScore } from '@/lib/format'
import { STAGE_LABEL, groupRows, type LogRow, type RowGroup } from '@/lib/build/reducer'
import { useIsTabletUp } from '@/hooks/use-media-query'

/**
 * The build log.
 *
 * Virtualised past a few hundred rows (`@tanstack/react-virtual`), because a
 * real build emits one row per source screened and a pro build can run to
 * thousands — and because this is the page a user sits and watches while their
 * credits are being spent, so it has to stay at 60fps on a phone.
 *
 * Three things make it feel right rather than merely work:
 *
 * **At-bottom auto-scroll, done by hand.** New rows scroll into view only while
 * the reader is already within 48px of the end. Scrolled up, rows append with
 * no motion and a *jump to latest* pill appears. `overflow-anchor: none` turns
 * the browser's own anchoring off, so it cannot fight this.
 *
 * **Groups count as one row.** Eleven fetcher lines and four hundred ingest
 * lines each collapse to a single openable summary, which is the difference
 * between a log you can read and a log you can only scroll.
 *
 * **Fixed 20px rows at `md` and up**, measured below it — a wrapped message on
 * a phone is two or three lines tall and a fixed estimate would misplace every
 * row under it.
 */

const ROW_HEIGHT_DESKTOP = 20
const ROW_HEIGHT_ESTIMATE_PHONE = 44
const AT_BOTTOM_SLACK = 48

export function BuildLog({
  rows,
  live,
  reconnecting,
  className,
}: {
  rows: LogRow[]
  live: boolean
  reconnecting: boolean
  className?: string
}) {
  const isTabletUp = useIsTabletUp()
  const scroller = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => new Set())

  const groups = useMemo(() => groupRows(rows), [rows])

  // A group that is open contributes its rows; a closed one contributes a
  // single summary line. This is the list the virtualiser actually measures.
  const items = useMemo<Item[]>(() => {
    const out: Item[] = []
    for (const group of groups) {
      if (group.group && group.rows.length > 1) {
        const open = openGroups.has(group.group)
        out.push({ kind: 'group', key: `g:${group.key}`, group, open })
        if (open) {
          for (const row of group.rows) out.push({ kind: 'row', key: `r:${row.seq}`, row })
        }
      } else {
        for (const row of group.rows) out.push({ kind: 'row', key: `r:${row.seq}`, row })
      }
    }
    return out
  }, [groups, openGroups])

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => (isTabletUp ? ROW_HEIGHT_DESKTOP : ROW_HEIGHT_ESTIMATE_PHONE),
    // Rows wrap below `md`, so their height has to be measured rather than
    // assumed; above it every row is exactly one 20px line.
    measureElement: isTabletUp ? undefined : (element) => element.getBoundingClientRect().height,
    overscan: 12,
    getItemKey: (index) => items[index]?.key ?? index,
  })

  const checkAtBottom = useCallback(() => {
    const element = scroller.current
    if (!element) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    setAtBottom(distance <= AT_BOTTOM_SLACK)
  }, [])

  // Follow the tail only while the reader is at the bottom. `useLayoutEffect`
  // so the scroll happens in the same frame the row is painted — in a
  // `useEffect` the new row is visible one frame before the scroll catches it,
  // which reads as a jitter.
  useLayoutEffect(() => {
    if (!atBottom || items.length === 0) return
    const element = scroller.current
    if (!element) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    // Smooth only within one screen; a long jump is instant (web-design.md §9).
    element.scrollTo({
      top: element.scrollHeight,
      behavior: distance < element.clientHeight ? 'smooth' : 'auto',
    })
  }, [items.length, atBottom])

  useEffect(() => {
    checkAtBottom()
  }, [checkAtBottom])

  const toggleGroup = (key: string) => {
    setOpenGroups((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const jumpToLatest = () => {
    setAtBottom(true)
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }

  return (
    <div className={cn('relative min-h-0 flex-1', className)}>
      <div
        ref={scroller}
        onScroll={checkAtBottom}
        role="log"
        aria-live="off"
        aria-label="Build log"
        className="anchor-none h-full overflow-y-auto overscroll-contain pan-y rounded-card bg-panel font-mono text-xs"
      >
        {items.length === 0 ? (
          <p className="p-3 text-fg-3">Waiting for Peritus to start this build…</p>
        ) : (
          <div style={{ height: virtualizer.getTotalSize() }} className="relative w-full">
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const item = items[virtualRow.index]
              if (!item) return null
              return (
                <div
                  key={virtualRow.key}
                  ref={isTabletUp ? undefined : virtualizer.measureElement}
                  data-index={virtualRow.index}
                  style={{ transform: `translateY(${virtualRow.start}px)` }}
                  className="absolute inset-x-0 top-0"
                >
                  {item.kind === 'group' ? (
                    <GroupSummary
                      group={item.group}
                      open={item.open}
                      onToggle={() => item.group.group && toggleGroup(item.group.group)}
                    />
                  ) : (
                    <Row row={item.row} indent={Boolean(item.row.group)} />
                  )}
                </div>
              )
            })}
          </div>
        )}

        {reconnecting && (
          <p className="px-2 py-1 text-warn">· reconnecting to the build log…</p>
        )}
      </div>

      {/* Rises in only when the reader has scrolled away from the tail. */}
      {!atBottom && (
        <button
          type="button"
          onClick={jumpToLatest}
          className={cn(
            'absolute bottom-3 left-1/2 -translate-x-1/2',
            'inline-flex h-(--icon-btn-sm) items-center gap-1.5 rounded-full border border-border bg-raised px-3',
            'text-xs text-fg-2 shadow-lg shadow-black/25',
            'transition-colors duration-(--dur-1) hover:text-fg',
            'motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-(--dur-2)',
          )}
        >
          <ArrowDown className="size-3" />
          {live ? 'Jump to latest' : 'Jump to the end'}
        </button>
      )}
    </div>
  )
}

type Item =
  | { kind: 'row'; key: string; row: LogRow }
  | { kind: 'group'; key: string; group: RowGroup; open: boolean }

function Row({ row, indent }: { row: LogRow; indent?: boolean }) {
  return (
    <div
      className={cn(
        'flex items-baseline gap-2 px-2 py-0 leading-5 md:h-5 md:overflow-hidden',
        indent && 'pl-5',
      )}
    >
      <span aria-hidden="true" className={cn('w-3 shrink-0 text-center', MARK_COLOUR[row.kind])}>
        {row.kind === 'keep' ? (
          <Check className="inline size-3" />
        ) : row.kind === 'drop' ? (
          <X className="inline size-3" />
        ) : (
          MARK[row.kind]
        )}
      </span>
      <span className="hidden w-32 shrink-0 truncate text-fg-3 md:inline">
        {row.stage ? STAGE_LABEL[row.stage] : ''}
      </span>
      <span className={cn('min-w-0 flex-1 md:truncate', MESSAGE_COLOUR[row.kind])}>
        {row.message}
      </span>
      {row.scores && (
        // The words where there is room for them; a nobody-outside-the-team
        // "q8.5 r9.0" everywhere else, with the meaning on the title.
        <span className="shrink-0 text-fg-3" title="Quality · relevance, each out of 10">
          {row.scores.firstQ !== undefined && row.scores.firstQ !== null && (
            <span className="text-fg-3">
              {formatScore(row.scores.firstQ)}/{formatScore(row.scores.firstR)}{' '}
              <span aria-hidden="true">→</span>{' '}
            </span>
          )}
          <span className="xl:hidden">q</span>
          <span className="hidden xl:inline">quality </span>
          {formatScore(row.scores.q)} <span className="xl:hidden">r</span>
          <span className="hidden xl:inline">· relevance </span>
          {formatScore(row.scores.r)}
        </span>
      )}
    </div>
  )
}

function GroupSummary({
  group,
  open,
  onToggle,
}: {
  group: RowGroup
  open: boolean
  onToggle: () => void
}) {
  const label = GROUP_LABELS[group.group ?? ''] ?? group.group ?? 'group'
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      // `min-h` from the row token on touch: a collapsed group is something a
      // thumb opens, unlike the log's own rows, which are text. There are only
      // ever a handful of groups, so this does not inflate a long log.
      //
      // The 20px desktop form is `pointer-fine:md:` and not plain `md:`,
      // because an iPad is both wide *and* touch — a width-only breakpoint
      // handed it the mouse-sized control.
      className="flex min-h-(--row-h) w-full items-baseline gap-2 px-2 leading-5 text-left transition-colors duration-(--dur-1) hover:bg-raised pointer-fine:md:h-5 pointer-fine:md:min-h-0"
    >
      <ChevronRight
        aria-hidden="true"
        className={cn(
          'size-3 shrink-0 self-center text-fg-4 transition-transform duration-(--dur-2)',
          open && 'rotate-90',
        )}
      />
      <span className="hidden w-32 shrink-0 truncate text-fg-3 md:inline">
        {group.rows[0]?.stage ? STAGE_LABEL[group.rows[0].stage] : ''}
      </span>
      <span className="min-w-0 flex-1 truncate text-fg-3">
        {label} · {group.rows.length} lines
      </span>
    </button>
  )
}

const MARK: Record<string, string> = {
  info: '·',
  stage: '▸',
  warn: '!',
  bad: '×',
  ok: '✓',
  meta: '·',
  keep: '✓',
  drop: '×',
}

const MARK_COLOUR: Record<string, string> = {
  info: 'text-fg-3',
  stage: 'text-fg',
  warn: 'text-warn',
  bad: 'text-bad',
  ok: 'text-ok',
  meta: 'text-fg-3',
  keep: 'text-ok',
  drop: 'text-bad',
}

const MESSAGE_COLOUR: Record<string, string> = {
  info: 'text-fg-3',
  stage: 'text-fg',
  warn: 'text-warn',
  bad: 'text-bad',
  ok: 'text-fg-2',
  meta: 'text-fg-3',
  keep: 'text-fg-2',
  drop: 'text-fg-3',
}

const GROUP_LABELS: Record<string, string> = {
  ingest: 'Reading sources',
  graph: 'Extracting concepts',
}

// `fetchers:<round>` is dynamic, so it is labelled by prefix rather than by a
// literal key.
for (let round = 0; round < 8; round += 1) {
  GROUP_LABELS[`fetchers:${round}`] = `Search results (round ${round + 1})`
}
