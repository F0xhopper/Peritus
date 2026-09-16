'use client'

import { Plus, Settings, Home } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { Avatar } from '@/components/identity/avatar'
import { ExpertSidebar } from '@/components/shell/expert-sidebar'
import { Sheet } from '@/components/shell/sheet'
import { useShell } from '@/components/shell/shell-context'
import { cn } from '@/lib/cn'

import { useActiveSlug } from '@/components/shell/rail'
import { isBuilding } from '@/components/ui/status-dot'
import type { ConversationSummary, CreditState, ExpertSummary, Me } from '@/lib/api/types'

/**
 * The one navigation surface below `md`.
 *
 * The rail folds into a horizontal strip of avatars across the top — Home
 * first, `+` last — with the expert sidebar's content unchanged underneath, and
 * settings at the bottom. There is deliberately no bottom tab bar: the reading
 * surface has to stay as tall as possible on a phone, which is the same choice
 * Obsidian mobile makes.
 *
 * The drawer's hover-only affordances have tap forms by construction — the
 * rail's tooltips become the expert names in the list below.
 */
export function NavDrawer({
  experts,
  conversations,
  credits,
  me,
}: {
  experts: ExpertSummary[]
  conversations: ConversationSummary[]
  credits: CreditState | null
  me: Me | null
}) {
  const { navOpen, setNavOpen, navTriggerRef } = useShell()
  const pathname = usePathname()
  const activeSlug = useActiveSlug(conversations)

  return (
    <Sheet
      open={navOpen}
      onOpenChange={setNavOpen}
      side="left"
      title="Navigation"
      hideTitle
      swipeToOpen
      finalFocus={navTriggerRef}
      // Up to `lg`, not `md`: between 768 and 1023px the expert sidebar is gone
      // too, and without the drawer a tablet in portrait had no route to an
      // expert's Sources, Graph, Settings or chats except the command palette.
      className="lg:hidden"
    >
      {/* Any link inside the drawer closes it, including one that navigates to
          the page already open — `usePathname` does not change there, so the
          Sheet's own close-on-navigation never fires and the drawer would sit
          over the page the user just asked for. */}
      <div
        className="-mt-1 flex flex-col gap-3"
        onClick={(event) => {
          if ((event.target as Element).closest('a')) setNavOpen(false)
        }}
      >
        {/* The rail, horizontal — only where the real rail is not on screen. */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 md:hidden">
          <Link
            href="/experts"
            aria-label="Home"
            className={cn(
              'grid size-10 shrink-0 place-items-center rounded-card text-fg-3',
              pathname === '/experts' ? 'bg-raised text-fg' : 'hover:bg-raised'
            )}
          >
            <Home className="size-4" />
          </Link>
          {experts.map((expert) => (
            <Link
              key={expert.id}
              href={`/experts/${expert.name}`}
              aria-label={expert.persona_name ?? expert.topic}
              className={cn(
                'relative grid size-10 shrink-0 place-items-center rounded-card',
                expert.name === activeSlug ? 'opacity-100' : 'opacity-70'
              )}
            >
              <Avatar expert={expert} size={40} />
              {isBuilding(expert) && (
                <span
                  aria-hidden="true"
                  className="animate-pulse-dot pointer-events-none absolute inset-0 rounded-card ring-2 ring-warn"
                />
              )}
            </Link>
          ))}
          <Link
            href="/experts/new"
            aria-label="Build a new expert"
            className="grid size-10 shrink-0 place-items-center rounded-card border border-dashed border-border text-fg-3"
          >
            <Plus className="size-4" />
          </Link>
        </div>

        <div className="-mx-3 border-t border-border-soft md:hidden" />

        {/* The sidebar's content, unchanged. */}
        <div className="-mx-3 min-h-0">
          <ExpertSidebar
            experts={experts}
            conversations={conversations}
            credits={credits}
            className="bg-transparent"
          />
        </div>

        <div className="-mx-3 mt-auto border-t border-border-soft" />
        <Link
          href="/settings"
          className="flex h-(--row-h) items-center gap-2 rounded-row px-1.5 text-sm text-fg-2 hover:bg-raised"
        >
          <Settings className="size-4 text-fg-3" />
          <span className="min-w-0 flex-1 truncate">{me?.email ?? 'Settings'}</span>
        </Link>
      </div>
    </Sheet>
  )
}
