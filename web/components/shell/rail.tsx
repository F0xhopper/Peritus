'use client'

import { Plus, Settings, Home } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { Avatar } from '@/components/identity/avatar'
import { useShell } from '@/components/shell/shell-context'
import { isBuilding } from '@/components/ui/status-dot'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/cn'
import { displayName, subtitle } from '@/lib/persona'
import type { ConversationSummary, ExpertSummary, Me } from '@/lib/api/types'

/**
 * The outermost navigation: one avatar per expert, the way servers work in
 * Discord. Experts are the top-level unit, and everything else in the app
 * belongs to whichever one is selected here.
 *
 * The active bar slides on `translateY` — a single transform on one absolutely
 * positioned element, so no layout is involved and it costs nothing on a
 * phone. It is derived from the active index rather than measured, which is why
 * every row in this column has to be a fixed height.
 *
 * The rail is honest about its limit: it works to about fifteen experts and
 * then relies on scrolling and the Home list. That matches a product where
 * builds cost credits.
 */

const AVATAR_SIZE = 40
const HEADER_SLOTS = 1 // the Home button above the list

export function Rail({
  experts,
  conversations,
  me,
  className,
}: {
  experts: ExpertSummary[]
  /**
   * Only to answer "whose chat is this?". A conversation's URL does not name an
   * expert, so without this the rail went blank the moment you opened a chat —
   * the one place in the app where you most need to know which expert is
   * talking.
   */
  conversations: ConversationSummary[]
  me: Me | null
  className?: string
}) {
  const pathname = usePathname()
  const activeSlug = useActiveSlug(conversations)
  const activeIndex = experts.findIndex((e) => e.name === activeSlug)
  const homeActive = pathname === '/experts' || pathname === '/chats'

  // The bar's own offset, in slots rather than pixels: the slot pitch is
  // `--rail-slot`, which is 8px taller on a touch pointer, so multiplying it
  // here in JavaScript would put the bar beside the wrong avatar on an iPad.
  const activeSlot = homeActive ? 0 : activeIndex >= 0 ? activeIndex + HEADER_SLOTS : null

  return (
    <nav
      aria-label="Experts"
      className={cn(
        'relative flex w-rail flex-col items-center gap-2 bg-panel py-2',
        className,
      )}
    >
      {/* The one moving thing in the shell. `--fg`, not the expert colour: it
          marks *where you are*, which is not a property of the expert. */}
      <span
        aria-hidden="true"
        style={{
          transform: `translateY(calc(var(--rail-slot) * ${activeSlot ?? 0} + 8px))`,
        }}
        className={cn(
          'pointer-events-none absolute top-2 left-0 h-8 w-[3px] rounded-r-full bg-fg',
          'transition-transform duration-(--dur-3) ease-(--ease-out)',
          activeSlot === null && 'opacity-0',
        )}
      />

      <div className="flex w-full flex-col items-center gap-2 overflow-y-auto overscroll-contain pan-y">
        <Tooltip content="Home" side="right">
          <Link
            href="/experts"
            aria-current={homeActive ? 'page' : undefined}
            className={cn(
              'grid size-(--rail-item) place-items-center rounded-card text-fg-3',
              'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg',
              homeActive && 'bg-raised text-fg',
            )}
          >
            <Home className="size-4" />
          </Link>
        </Tooltip>

        {experts.map((expert) => (
          <RailAvatar key={expert.id} expert={expert} active={expert.name === activeSlug} />
        ))}

        <Tooltip content="Build a new expert" side="right">
          <Link
            href="/experts/new"
            aria-label="Build a new expert"
            className={cn(
              'grid size-(--rail-item) place-items-center rounded-card text-fg-3',
              'border border-dashed border-border',
              'transition-colors duration-(--dur-1) hover:border-expert hover:text-expert',
              pathname === '/experts/new' && 'border-expert text-expert',
            )}
          >
            <Plus className="size-4" />
          </Link>
        </Tooltip>
      </div>

      <div className="mt-auto flex flex-col items-center gap-2 pt-2">
        <Tooltip content="Settings" side="right">
          <Link
            href="/settings"
            aria-label="Settings"
            className={cn(
              'grid size-(--rail-item) place-items-center rounded-card text-fg-3',
              'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg',
              pathname.startsWith('/settings') && 'bg-raised text-fg',
            )}
          >
            <Settings className="size-4" />
          </Link>
        </Tooltip>
        {me && (
          <Tooltip content={me.email ?? 'Account'} side="right">
            <Link
              href="/settings"
              aria-label="Account"
              // A 32px circle inside a hit area that grows with the pointer:
              // the initial reads as an avatar, not as a button, so the box is
              // what has to reach 44px on touch rather than the circle.
              className="grid size-(--icon-btn) place-items-center text-fg-3 transition-colors duration-(--dur-1) hover:text-fg"
            >
              <span className="grid size-8 place-items-center rounded-full bg-raised text-xs font-medium text-fg-2">
                {(me.email ?? '?').slice(0, 1).toUpperCase()}
              </span>
            </Link>
          </Tooltip>
        )}
      </div>
    </nav>
  )
}

function RailAvatar({ expert, active }: { expert: ExpertSummary; active: boolean }) {
  const building = isBuilding(expert)
  const failed = expert.status === 'failed'

  return (
    <Tooltip
      side="right"
      content={
        <span className="block">
          <span className="block text-fg">{displayName(expert)}</span>
          {subtitle(expert) && <span className="mt-0.5 block text-fg-3">{subtitle(expert)}</span>}
        </span>
      }
    >
      <Link
        href={`/experts/${expert.name}`}
        prefetch
        // The tooltip is a *visual* label: it appears on hover, and it is a
        // description rather than a name. Without this the rail was a column of
        // links each announced as "link" — the app's whole top-level navigation
        // unusable without sight of it.
        aria-label={[displayName(expert), subtitle(expert)].filter(Boolean).join(' — ')}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'relative grid size-(--rail-item) place-items-center rounded-card',
          'transition-opacity duration-(--dur-1)',
          active ? 'opacity-100' : 'opacity-70 hover:opacity-100',
        )}
      >
        <Avatar expert={expert} size={AVATAR_SIZE} eager />
        {building && (
          // A pulsing ring while a build runs. Static under reduced motion.
          <span
            aria-hidden="true"
            className="animate-pulse-dot pointer-events-none absolute inset-0 rounded-card ring-2 ring-warn"
          />
        )}
        {failed && (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full bg-bad ring-2 ring-panel"
          />
        )}
      </Link>
    </Tooltip>
  )
}

/**
 * The expert whose pages the shell should show: named by an `/experts/…` path,
 * or — on a chat — found in the shell's chat list, or published by the chat
 * page itself when the chat is too new or too old to be in that list.
 */
export function useActiveSlug(conversations: ConversationSummary[]): string | null {
  const pathname = usePathname()
  const { chatExpert } = useShell()
  return (
    slugFromPath(pathname) ??
    slugFromChat(pathname, conversations) ??
    (chatExpert && pathname === `/chats/${chatExpert.chatId}` ? chatExpert.slug : null)
  )
}

/** The expert a `/chats/[id]` path belongs to, via the shell's own chat list. */
export function slugFromChat(
  pathname: string,
  conversations: ConversationSummary[],
): string | null {
  const match = /^\/chats\/([^/]+)/.exec(pathname)
  if (!match) return null
  return conversations.find((c) => c.id === match[1])?.expert_slug ?? null
}

/** The expert slug a path belongs to, or null on Home and the account pages. */
export function slugFromPath(pathname: string): string | null {
  const match = /^\/experts\/([^/]+)/.exec(pathname)
  if (!match) return null
  // `/experts/new` is the build form, not an expert.
  return match[1] === 'new' ? null : decodeURIComponent(match[1])
}
