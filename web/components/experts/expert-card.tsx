'use client'

import {
  ArrowUpRight,
  LogOut,
  MessageSquare,
  MoreHorizontal,
  Orbit,
  Settings,
  Trash2,
  Users,
} from 'lucide-react'
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
import { displayName } from '@/lib/persona'
import type { ExpertSummary } from '@/lib/api/types'
import { useApiAction } from '@/hooks/use-api-action'
import { apiVoid } from '@/lib/api/client'

/**
 * One expert on Home.
 *
 * Three bands, top to bottom: **who it is** (the avatar at a size that reads as
 * a face rather than a bullet, the name, the subject and a sentence of the
 * About), **what it is made of** (sources,
 * passages, concepts — a full-bleed strip, so the numbers line up across a row
 * of cards) and **what you can do** (its state, and Ask).
 *
 * A hairline box on the page's ground, like every container. There is still no
 * coloured bar: the only hue on the card is its status.
 *
 * Ask is the quiet button until the card is under the pointer, when it becomes
 * the primary one — a grid of white pills would be a page of nothing but
 * buttons, and the card you are pointing at is the one you are about to use.
 * The ⋯ menu is always visible: a hover-only affordance on a touch device is an
 * affordance that does not exist, and the card has the room.
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
  // Still being built: a count of nothing is "not yet", not a finding.
  const pending = state !== 'ready'
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
          // A column, so the two lower bands sit on the bottom edge and line up
          // across a grid row whether or not a card has a description.
          'group relative flex flex-col overflow-hidden rounded-panel border border-border-soft bg-panel',
          'transition-colors duration-(--dur-1) hover:border-border',
          stagger !== null &&
            'motion-safe:animate-in motion-safe:duration-(--dur-2) motion-safe:fill-mode-backwards motion-safe:fade-in motion-safe:slide-in-from-bottom-1'
        )}
      >
        {/* Right padding keeps a long name clear of the absolutely placed ⋯ menu. */}
        <Link href={base} prefetch className="flex flex-1 flex-col p-5">
          <span className="flex items-center gap-4 pr-(--icon-btn-sm)">
            {/* The shared element for the move to the Overview header. */}
            <ViewTransition name={`sigil-${expert.name}`}>
              {/* `flex`, so the avatar is not sitting on a text baseline: a
                  picture has none of its own, and the line box it then got was
                  5px taller than a monogram's. */}
              <span className="flex shrink-0">
                <Avatar expert={expert} size={56} />
              </span>
            </ViewTransition>
            <span className="min-w-0 flex-1">
              {/* The subject is the name, and a subject is often a phrase, so it
                  gets two lines before it is cut. */}
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="line-clamp-2 text-lg leading-snug font-semibold text-fg">
                  {displayName(expert)}
                </span>
                {!owner && (
                  <span title="Shared with you" className="inline-flex shrink-0 text-fg-3">
                    <Users className="size-3.5" aria-hidden="true" />
                    <span className="sr-only">Shared with you</span>
                  </span>
                )}
              </span>
            </span>
          </span>

          {/* Three lines' height whether or not there is text, so the strips
              below line up across a grid row. A build has no persona yet, and
              an empty gap there read as a card that failed to load. */}
          <span className="mt-4 line-clamp-3 min-h-[calc(3lh)] text-sm leading-relaxed text-fg-2">
            {description ??
              (pending ? (
                <span className="text-fg-3">
                  Still reading. Its voice is written once the sources are in.
                </span>
              ) : null)}
          </span>
        </Link>

        <dl className="grid grid-cols-3 divide-x divide-border-soft border-y border-border-soft">
          <Count label="Sources" value={expert.source_count} pending={pending} />
          <Count label="Passages" value={expert.chunk_count} pending={pending} />
          <Count label="Concepts" value={expert.node_count} pending={pending} />
        </dl>

        {/* A fixed height, with or without the Ask button, so every card in the
            grid lines up. The build date lives on the Overview. */}
        <div className="flex min-h-[calc(var(--row-h)+2rem)] items-center gap-3 px-5 py-4">
          <span className="flex min-w-0 items-center gap-2 text-sm">
            <StatusDot state={state} />
            <span className={cn('truncate', statusTextClass[state])}>{stateLabel(state)}</span>
          </span>
          {chattable && (
            // Straight into a new chat from Home, composer focused — no stop at
            // the Overview on the way.
            <Button
              variant="secondary"
              loading={startingChat}
              onClick={() => void startChat()}
              aria-label={`Ask ${displayName(expert)}`}
              className="ml-auto px-4 group-hover:border-accent group-hover:bg-accent group-hover:text-accent-fg"
            >
              Ask
              <ArrowUpRight className="size-3.5" />
            </Button>
          )}
        </div>

        <MenuRoot>
          <MenuTrigger
            aria-label={`Actions for ${displayName(expert)}`}
            className={cn(
              'absolute top-4 right-4 grid size-(--icon-btn-sm) place-items-center rounded-full text-fg-3',
              'transition-[background-color,color] duration-(--dur-1)',
              'hover:bg-raised hover:text-fg'
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

/**
 * One cell of the strip. While a build is running a zero is an em dash — the
 * count has not been made yet, which is what the dash means everywhere else —
 * and "Concepts 0" beside "Building" read as a fault.
 */
function Count({ label, value, pending }: { label: string; value: number; pending: boolean }) {
  return (
    <div className="min-w-0 px-5 py-3.5">
      <dt className="truncate text-label tracking-[0.04em] text-fg-3 uppercase">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tracking-tight text-fg tabular-nums">
        {pending && value === 0 ? '—' : formatInt(value)}
      </dd>
    </div>
  )
}
