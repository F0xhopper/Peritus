'use client'

import { Menu, MoreHorizontal, Search } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { Avatar } from '@/components/identity/avatar'
import { MenuContent, MenuRoot, MenuTrigger } from '@/components/ui/menu'
import { cn } from '@/lib/cn'
import { displayName } from '@/lib/persona'
import { useShell } from '@/components/shell/shell-context'
import type { ExpertSummary } from '@/lib/api/types'

/**
 * The breadcrumb bar: 40px, 44px under a coarse pointer.
 *
 * One line, and a strict budget on what may be in it: the menu button below
 * `md`, the 20px avatar, the persona name, the page title truncated, **one**
 * action, and an overflow menu for everything else. A second action creeping in
 * here is what turns a 44px bar on a 360px screen into three truncated words.
 *
 * **That action is quiet** — `secondary` at most. The bar is chrome, and a
 * filled accent pill in it outshouts the page it belongs to: on the Overview it
 * was the brightest thing on a page whose own content is the argument, and it
 * was the only filled control in the entire shell. The one exception is the
 * build page's *Chat now*, which appears at the moment an expert becomes
 * answerable — the only top-bar action that is a real call to action rather
 * than a shortcut to something already on the page.
 */

export interface TopBarProps {
  expert?: ExpertSummary | null
  /** The page, or the chat title. Truncates first when space runs out. */
  title: string
  /** One button. Anything more belongs in `overflow`. */
  action?: React.ReactNode
  /**
   * A second, quieter control, to the left of the action.
   *
   * The budget above is still one *prominent* action; this exists for the
   * Overview's Share, which is the thing an owner looks for in the top-right of
   * a page and could not find inside the ⋯ menu. `ghost` only, and icon-only
   * below `sm`, so the title keeps its width on a phone.
   */
  secondary?: React.ReactNode
  overflow?: React.ReactNode
  /** Replaces the title with an editable field (the chat rename). */
  titleSlot?: React.ReactNode
  /** Drop the palette's search icon, for a page whose one action is its own
   *  search — two identical magnifiers side by side is a guessing game. */
  hideSearch?: boolean
}

export function TopBar({
  expert,
  title,
  action,
  secondary,
  overflow,
  titleSlot,
  hideSearch,
}: TopBarProps) {
  const { openNav, openPalette, navTriggerRef, sidebarCollapsed } = useShell()
  // Both of these live in the sidebar from `lg`. Folded away, they come back
  // here, or a collapsed shell would have no navigation and no search at all.
  const railOnly = sidebarCollapsed ? '' : 'lg:hidden'

  return (
    <header
      className={cn(
        'flex h-topbar-touch shrink-0 items-center gap-2 border-b border-border-soft bg-bg px-2 md:h-topbar md:px-3'
      )}
    >
      <button
        ref={navTriggerRef}
        type="button"
        onClick={openNav}
        aria-label="Open navigation"
        className={cn(
          'grid size-(--icon-btn) shrink-0 place-items-center rounded-row text-fg-3',
          'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg',
          railOnly
        )}
      >
        <Menu className="size-4" />
      </button>

      {/* On the expert's own Overview the crumb is text, not a link to the page
          it is already on — a self-link is a dead end a keyboard user has to
          tab through and a screen reader announces as a way out. */}
      {expert && <Crumb expert={expert} />}

      {/* Not a heading: this is the breadcrumb's leaf, and the page below it
          owns the document's one `h1`. Two `h1`s per page is a real
          accessibility fault, and a screen reader announcing the same words
          twice in a row is the symptom. */}
      <div className="min-w-0 flex-1">
        {titleSlot ?? <p className="truncate text-sm font-medium text-fg">{title}</p>}
      </div>

      {/* The trailing controls are one group with their own rhythm.
          On the header's own `gap-2` the ⋯ sat 8px from the filled action and
          12px from the window edge, so it read as part of the button rather
          than as its own control; at `md:gap-3` the gaps either side of it
          match, and it reads as one cluster in the corner. Below `md` the gap
          stays 8px — a 44px target already separates itself, and every pixel
          there is taken from the title. */}
      <div className="flex shrink-0 items-center gap-2 md:gap-3">
        {!hideSearch && (
          <button
            type="button"
            onClick={openPalette}
            aria-label="Search"
            className={cn(
              'grid size-(--icon-btn) shrink-0 place-items-center rounded-row text-fg-3',
              'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg',
              railOnly
            )}
          >
            <Search className="size-4" />
          </button>
        )}

        {secondary}
        {action}

        {overflow && (
          <MenuRoot>
            <MenuTrigger
              aria-label="More actions"
              className="grid size-(--icon-btn) shrink-0 place-items-center rounded-row text-fg-3 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
            >
              <MoreHorizontal className="size-4" />
            </MenuTrigger>
            <MenuContent>{overflow}</MenuContent>
          </MenuRoot>
        )}
      </div>
    </header>
  )
}

function Crumb({ expert }: { expert: ExpertSummary }) {
  const pathname = usePathname()
  const here = pathname === `/experts/${expert.name}`
  const inner = (
    <>
      <Avatar expert={expert} size={20} />
      <span className="hidden max-w-40 truncate text-sm text-fg-2 sm:inline">
        {displayName(expert)}
      </span>
      <span aria-hidden="true" className="hidden text-fg-4 sm:inline">
        /
      </span>
    </>
  )
  const className = 'flex min-h-(--row-h) min-w-0 shrink-0 items-center gap-1.5'

  if (here) {
    return (
      <span aria-current="page" className={className}>
        {inner}
      </span>
    )
  }
  return (
    <Link href={`/experts/${expert.name}`} className={className}>
      {inner}
    </Link>
  )
}
