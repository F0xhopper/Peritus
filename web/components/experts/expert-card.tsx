'use client'

import { LogOut, MessageSquare, MoreHorizontal, Orbit, Settings, Trash2, Users } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { ViewTransition } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { Button } from '@/components/ui/button'
import { ConfirmDelete } from '@/components/experts/confirm-delete'
import {
  MenuContent,
  MenuItem,
  MenuLinkItem,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
} from '@/components/ui/menu'
import { StatusDot, dotState, stateLabel, statusTextClass } from '@/components/ui/status-dot'
import { useLeaveExpert } from '@/hooks/use-leave-expert'
import { useStartChat } from '@/hooks/use-start-chat'
import { canManage } from '@/lib/access'
import { cn } from '@/lib/cn'
import { firstSentence, formatInt } from '@/lib/format'
import { displayName, subtitle } from '@/lib/persona'
import type { ExpertSummary } from '@/lib/api/types'
import { useApiAction } from '@/hooks/use-api-action'
import { apiVoid } from '@/lib/api/client'

/**
 * One expert on Home.
 *
 * No border and no left rule. The card is a raised surface on the page's own
 * ground, which is the whole of its grouping — a grid of cards each wearing a
 * hairline box *and* a 2px coloured bar on its left was a page made of lines,
 * and the bars were the loudest colour in the product for information the
 * avatar beside them already carried.
 *
 * The ⋯ menu is visible at all times under `(hover: none)` and on hover
 * otherwise: a hover-only affordance on a touch device is an affordance that
 * does not exist.
 */
export function ExpertCard({
  expert,
  stagger,
}: {
  expert: ExpertSummary
  /** Index for the first-paint stagger, or null for no animation. */
  stagger: number | null
}) {
  const [confirming, setConfirming] = useState(false)
  const base = `/experts/${expert.name}`
  const chattable = expert.readiness !== 'pending'
  // The About text's first sentence — who this expert is, in a line or two.
  const description = firstSentence(expert.persona_bio)
  const { start: startChat, starting: startingChat } = useStartChat(expert.name)
  const state = dotState(expert.status, expert.readiness, expert.build_active)
  const owner = canManage(expert)
  const { leave } = useLeaveExpert(expert.name, displayName(expert))

  const { run: remove, pending: deleting } = useApiAction(
    () =>
      apiVoid(
        `/api/experts/${encodeURIComponent(expert.name)}`,
        { method: 'DELETE' },
        'Could not delete that expert.'
      ),
    {
      success: `Deleted ${displayName(expert)}`,
      error: 'Could not delete that expert.',
      onSuccess: () => setConfirming(false),
    }
  )

  return (
    <>
      <div
        style={{
          // 40ms apart, capped at eight by the caller.
          animationDelay: stagger !== null ? `${stagger * 40}ms` : undefined,
        }}
        className={cn(
          // A column, so the stats row sits on the bottom edge and lines up across
          // a grid row whether or not a card has a description.
          'group relative flex flex-col rounded-card bg-panel p-3',
          'transition-colors duration-(--dur-1) hover:bg-raised',
          stagger !== null &&
            'motion-safe:animate-in motion-safe:duration-(--dur-2) motion-safe:fill-mode-backwards motion-safe:fade-in motion-safe:slide-in-from-bottom-1'
        )}
      >
        {/* Right padding keeps a long name clear of the absolutely placed ⋯ menu. */}
        <Link
          href={base}
          prefetch
          className="flex min-h-(--row-h) items-start gap-2.5 pr-(--icon-btn-sm)"
        >
          {/* The shared element for the move to the Overview header. */}
          <ViewTransition name={`sigil-${expert.name}`}>
            <span>
              <Avatar expert={expert} size={32} />
            </span>
          </ViewTransition>
          <span className="min-w-0 flex-1">
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate text-sm font-medium text-fg">{displayName(expert)}</span>
              {!owner && (
                <span title="Shared with you" className="inline-flex shrink-0 text-fg-3">
                  <Users className="size-3" aria-hidden="true" />
                  <span className="sr-only">Shared with you</span>
                </span>
              )}
            </span>
            {subtitle(expert) && (
              <span className="mt-0.5 block truncate text-xs text-fg-3">{subtitle(expert)}</span>
            )}
            {description && (
              <span className="mt-1.5 line-clamp-2 text-xs leading-snug text-fg-2">
                {description}
              </span>
            )}
          </span>
        </Link>

        {/* One line at a fixed height, with or without the Ask button, so every
            card in the grid lines up. The build date lives on the Overview. */}
        <div className="mt-auto pt-3">
          <dl className="flex min-h-(--icon-btn-sm) items-center gap-x-3 text-xs">
            <div className="flex min-w-0 items-center gap-1">
              <dt className="sr-only">Status</dt>
              <dd className="flex min-w-0 items-center gap-1.5">
                <StatusDot state={state} />
                <span className={cn('truncate', statusTextClass[state])}>{stateLabel(state)}</span>
              </dd>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <dt className="text-fg-3">Sources</dt>
              <dd className="text-fg-2 tabular-nums">{formatInt(expert.source_count)}</dd>
            </div>
            {/* Concepts only once the graph has any: a building expert has
                none yet, and "Concepts 0" beside "Building" reads as a fault. */}
            {expert.node_count > 0 && (
              <div className="flex shrink-0 items-center gap-1">
                <dt className="text-fg-3">Concepts</dt>
                <dd className="text-fg-2 tabular-nums">{formatInt(expert.node_count)}</dd>
              </div>
            )}
            {chattable && (
              // Straight into a new chat from Home, composer focused — no stop at
              // the Overview on the way.
              <Button
                variant="secondary"
                size="sm"
                loading={startingChat}
                onClick={() => void startChat()}
                aria-label={`Ask ${displayName(expert)}`}
                className="ml-auto"
              >
                <MessageSquare className="size-3" />
                Ask
              </Button>
            )}
          </dl>
        </div>

        <MenuRoot>
          <MenuTrigger
            aria-label={`Actions for ${displayName(expert)}`}
            className={cn(
              'absolute top-2 right-2 grid size-(--icon-btn-sm) place-items-center rounded-chip text-fg-3',
              'transition-[opacity,background-color,color] duration-(--dur-1)',
              'hover:bg-raised hover:text-fg',
              // Hidden until hover on a mouse, always present on touch.
              'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
              '[@media(hover:none)]:opacity-100'
            )}
          >
            <MoreHorizontal className="size-3.5" />
          </MenuTrigger>
          <MenuContent>
            {chattable ? (
              <MenuItem onClick={() => void startChat()}>
                <MessageSquare className="size-3.5" />
                Ask
              </MenuItem>
            ) : (
              <MenuLinkItem render={<Link href={base} />}>
                <MessageSquare className="size-3.5" />
                Overview
              </MenuLinkItem>
            )}
            <MenuLinkItem render={<Link href={`${base}/knowledge`} />}>
              <Orbit className="size-3.5" />
              Knowledge
            </MenuLinkItem>
            {owner ? (
              <>
                <MenuLinkItem render={<Link href={`${base}/settings`} />}>
                  <Settings className="size-3.5" />
                  Settings
                </MenuLinkItem>
                <MenuSeparator />
                <MenuItem tone="danger" onClick={() => setConfirming(true)}>
                  <Trash2 className="size-3.5" />
                  Delete
                </MenuItem>
              </>
            ) : (
              <>
                <MenuSeparator />
                {/* Not a delete: the expert is someone else's, and this only
                    takes it out of this workspace. */}
                <MenuItem onClick={() => void leave()}>
                  <LogOut className="size-3.5" />
                  Remove from my experts
                </MenuItem>
              </>
            )}
          </MenuContent>
        </MenuRoot>
      </div>

      {owner && (
        <ConfirmDelete
          expert={expert}
          open={confirming}
          onOpenChange={setConfirming}
          onConfirm={remove}
          deleting={deleting}
        />
      )}
    </>
  )
}
