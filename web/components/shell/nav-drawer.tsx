'use client'

import { Plus, Settings, Home } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { Avatar } from '@/components/identity/avatar'
import { UserAvatar } from '@/components/identity/user-avatar'
import { ExpertSidebar } from '@/components/shell/expert-sidebar'
import { Sheet } from '@/components/shell/sheet'
import { useShell } from '@/components/shell/shell-context'
import { cn } from '@/lib/cn'

import { useActiveSlug } from '@/components/shell/rail'
import { StatusDot, dotState, isBuilding } from '@/components/ui/status-dot'
import { displayName, subtitle } from '@/lib/persona'
import type { ConversationSummary, CreditState, ExpertSummary, Me } from '@/lib/api/types'

/**
 * The one navigation surface below `md`.
 *
 * The rail folds into a **named list** across the top — Home, one row per
 * expert, then *New expert* — with the expert sidebar's content unchanged
 * underneath, and the account at the bottom. There is deliberately no bottom
 * tab bar: the reading surface has to stay as tall as possible on a phone,
 * which is the same choice Obsidian mobile makes.
 *
 * **Rows, not a strip of tiles.** It was a horizontal row of 40px avatars with
 * `aria-label`s and nothing visible: the rail's tooltips do not exist on touch,
 * two monograms with the same initials are the same grey square, and this
 * column never lists the experts — so switching expert on a phone meant tapping
 * an unlabelled tile and hoping. One row per expert costs a line each, and the
 * rail's own stated limit is about fifteen.
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
  const { navOpen, setNavOpen, navTriggerRef, sidebarCollapsed } = useShell()
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
      // expert's Knowledge, settings or chats except the palette. With
      // the sidebar collapsed the same is true at every width, so the drawer
      // stays available there too.
      className={sidebarCollapsed ? undefined : 'lg:hidden'}
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
        {/* The rail, as rows — only where the real rail is not on screen. */}
        <nav aria-label="Experts" className="md:hidden">
          <DrawerRow
            href="/experts"
            active={pathname === '/experts'}
            icon={<Home className="size-4 text-fg-3" />}
          >
            Home
          </DrawerRow>

          <p className="px-1.5 pt-2 pb-0.5 text-label tracking-[0.04em] text-fg-3 uppercase">
            Switch expert
          </p>
          {experts.map((expert) => (
            <DrawerRow
              key={expert.id}
              href={`/experts/${expert.name}`}
              active={expert.name === activeSlug}
              // The rail's own form, so the two navigations do not announce the
              // same expert differently.
              label={[displayName(expert), subtitle(expert)].filter(Boolean).join(' — ')}
              icon={
                <span className="relative grid shrink-0 place-items-center">
                  <Avatar expert={expert} size={24} />
                  {isBuilding(expert) && (
                    <span
                      aria-hidden="true"
                      className="animate-pulse-dot pointer-events-none absolute inset-0 rounded-card ring-2 ring-warn"
                    />
                  )}
                </span>
              }
              trailing={
                <StatusDot state={dotState(expert.status, expert.readiness, expert.build_active)} />
              }
            >
              {displayName(expert)}
            </DrawerRow>
          ))}

          <DrawerRow
            href="/experts/new"
            active={pathname === '/experts/new'}
            icon={<Plus className="size-4 text-fg-3" />}
          >
            New expert
          </DrawerRow>
        </nav>

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
        {/* *Account*, not "Settings": the expert's own settings are a row in the
            sidebar above, and one word with one gear for two different pages is
            how you end up on the wrong one. */}
        <Link
          href="/settings"
          className="flex min-h-(--row-h) items-center gap-2 rounded-row px-1.5 py-1 text-sm text-fg-2 hover:bg-raised"
        >
          {me ? (
            <UserAvatar name={me.name} email={me.email} avatarUrl={me.avatar_url} size={20} />
          ) : (
            <Settings className="size-4 shrink-0 text-fg-3" />
          )}
          <span className="min-w-0 flex-1">
            <span className="block truncate">Account</span>
            {me?.email && <span className="block truncate text-xs text-fg-3">{me.email}</span>}
          </span>
        </Link>
      </div>
    </Sheet>
  )
}

/** One named row in the drawer's expert list. */
function DrawerRow({
  href,
  active,
  icon,
  label,
  trailing,
  children,
}: {
  href: string
  active: boolean
  icon: React.ReactNode
  /** An accessible name that says more than the visible text. */
  label?: string
  trailing?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Link
      href={href}
      aria-label={label}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex h-(--row-h) items-center gap-2 rounded-row px-1.5 text-sm',
        'transition-colors duration-(--dur-1)',
        active ? 'bg-raised text-fg' : 'text-fg-2 hover:bg-raised hover:text-fg'
      )}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {trailing}
    </Link>
  )
}
