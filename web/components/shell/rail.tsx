'use client'

import { Plus, Settings, Home } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { Avatar } from '@/components/identity/avatar'
import { UserAvatar } from '@/components/identity/user-avatar'
import { useShell } from '@/components/shell/shell-context'
import { isBuilding } from '@/components/ui/status-dot'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/cn'
import { displayName } from '@/lib/persona'
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
 * Home sits in a cell the height of the top bar, above the same hairline: the
 * rail, the sidebar's search row and the page's bar are one band across the
 * window, and the line under it runs edge to edge.
 *
 * The rail is honest about its limit: it works to about fifteen experts and
 * then relies on scrolling and the Home list. That matches a product where
 * builds cost credits.
 */

const AVATAR_SIZE = 40
const BAR_HEIGHT = 32

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
  const { sidebarCollapsed } = useShell()
  const activeSlug = useActiveSlug(conversations)
  const activeIndex = experts.findIndex((e) => e.name === activeSlug)
  const homeActive = pathname === '/experts' || pathname === '/chats'

  // The bar's own offset, in CSS rather than pixels: the slot pitch is
  // `--rail-slot`, which is 8px taller on a touch pointer, so multiplying it
  // here in JavaScript would put the bar beside the wrong avatar on an iPad.
  // Home is centred in the top-bar cell; an expert is centred on its tile, one
  // `pt-2` below that cell.
  const barOffset = homeActive
    ? `calc((var(--spacing-topbar) - ${BAR_HEIGHT}px) / 2)`
    : activeIndex >= 0
      ? `calc(var(--spacing-topbar) + 0.5rem + var(--rail-slot) * ${activeIndex} + (var(--rail-item) - ${BAR_HEIGHT}px) / 2)`
      : null

  return (
    <nav
      aria-label="Experts"
      // On the ground, like everything else in the window. The navigation's one
      // hairline is on its trailing edge — the sidebar's when that is beside
      // the rail, the rail's own when it is not (below `lg`, or folded away).
      className={cn(
        'relative flex w-rail flex-col items-center border-r border-border-soft bg-bg pb-2',
        !sidebarCollapsed && 'lg:border-r-0',
        className
      )}
    >
      {/* The one moving thing in the shell. `--fg`, not the expert colour: it
          marks *where you are*, which is not a property of the expert. */}
      <span
        aria-hidden="true"
        style={{ transform: `translateY(${barOffset ?? '0px'})`, height: BAR_HEIGHT }}
        className={cn(
          'pointer-events-none absolute top-0 left-0 z-10 w-[3px] rounded-r-full bg-fg',
          'transition-transform duration-(--dur-3) ease-(--ease-out)',
          barOffset === null && 'opacity-0'
        )}
      />

      <div className="grid h-topbar w-full shrink-0 place-items-center border-b border-border-soft">
        <Tooltip content="Home" side="right">
          <Link
            href="/experts"
            aria-current={homeActive ? 'page' : undefined}
            // No fill when active: the sliding bar already marks where you
            // are, and a second indicator for Home alone made the rail follow
            // two rules at once.
            className={cn(
              'grid size-(--rail-item) place-items-center rounded-card text-fg-3',
              'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg',
              homeActive && 'text-fg'
            )}
          >
            <Home className="size-4" />
          </Link>
        </Tooltip>
      </div>

      <div className="pan-y flex w-full flex-col items-center gap-2 overflow-y-auto overscroll-contain pt-2">
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
              pathname === '/experts/new' && 'border-expert text-expert'
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
              pathname.startsWith('/settings') && 'bg-raised text-fg ring-1 ring-border ring-inset'
            )}
          >
            <Settings className="size-4" />
          </Link>
        </Tooltip>
        {me && (
          <Tooltip content={me.name || me.email || 'Account'} side="right">
            <Link
              href="/settings"
              aria-label="Account"
              // A 32px circle inside a hit area that grows with the pointer:
              // the initial reads as an avatar, not as a button, so the box is
              // what has to reach 44px on touch rather than the circle.
              className="grid size-(--icon-btn) place-items-center text-fg-3 transition-colors duration-(--dur-1) hover:text-fg"
            >
              <UserAvatar name={me.name} email={me.email} avatarUrl={me.avatar_url} size={32} />
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
        aria-label={displayName(expert)}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'relative grid size-(--rail-item) place-items-center rounded-card',
          'transition-opacity duration-(--dur-1)',
          // 85%, not 70%: a found picture at 40px is already dim, and the
          // inactive tiles are the app's only expert list at most widths.
          active ? 'opacity-100' : 'opacity-[0.85] hover:opacity-100'
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
            className="pointer-events-none absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full bg-bad ring-2 ring-bg"
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
  conversations: ConversationSummary[]
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
