'use client'

import {
  FileText,
  LayoutGrid,
  MessageSquare,
  MoreHorizontal,
  Orbit,
  PanelLeftClose,
  Plus,
  Search,
  SlidersHorizontal,
  Wallet,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useMemo, useState, useSyncExternalStore } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { useShell } from '@/components/shell/shell-context'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { MenuContent, MenuItem, MenuRoot, MenuSeparator, MenuTrigger } from '@/components/ui/menu'
import { StatusDot, dotState } from '@/components/ui/status-dot'
import { RelativeTime } from '@/components/ui/relative-time'
import { Tooltip } from '@/components/ui/tooltip'
import { useApiAction } from '@/hooks/use-api-action'
import { canManage } from '@/lib/access'
import { apiSend, apiVoid } from '@/lib/api/client'
import { cn } from '@/lib/cn'
import { chatTitle, formatInt } from '@/lib/format'
import { groupChats } from '@/lib/chat-groups'
import { displayName } from '@/lib/persona'
import { useActiveSlug } from '@/components/shell/rail'
import { focusAskField } from '@/components/chat/new-chat-composer'
import type { ConversationSummary, CreditState, ExpertSummary } from '@/lib/api/types'

/**
 * The second column: the selected expert's pages and chats, or — on Home — the
 * workspace.
 *
 * Active rows are a `--raised` pill with a hairline edge and no left bar; a
 * resting row is text on the ground. The column itself is on the ground too,
 * and its trailing hairline is the only rule between the navigation and the
 * page.
 *
 * **This column never lists the experts.** The rail immediately to its left
 * *is* the expert list — one avatar each, with the name in a tooltip — so a
 * second list of the same five names in the next column said nothing new and
 * pushed everything that was actually useful below the fold. Home's second
 * column is the two things the rail cannot reach: where to go in the workspace,
 * and the chats, which belong to no single expert. On a phone the drawer lists
 * them by name, where there is no rail and no hover.
 */

export interface ExpertSidebarProps {
  experts: ExpertSummary[]
  conversations: ConversationSummary[]
  credits: CreditState | null
  /**
   * The palette trigger at the top of the column. Only the layout's inline
   * sidebar shows it: inside the nav drawer the page's top bar already has the
   * search button, and opening the palette from within the drawer would stack
   * one modal on another.
   */
  showSearch?: boolean
  /**
   * The layout's own instance, which folds away at `lg` (`⌘\`). The copy
   * inside the nav drawer is never collapsible — it *is* the fallback.
   */
  collapsible?: boolean
  className?: string
}

/**
 * Which expert's pages to show is read from the path here rather than passed
 * in, so the sidebar is rendered once by the layout and survives every
 * navigation inside the app without the layout re-running.
 */
export function ExpertSidebar({
  experts,
  conversations,
  credits,
  showSearch = false,
  collapsible = false,
  className,
}: ExpertSidebarProps) {
  // A chat belongs to an expert even though its URL does not name one, so the
  // sidebar stays on that expert while a conversation is open.
  const slug = useActiveSlug(conversations)
  const selected = experts.find((e) => e.name === slug) ?? null
  const { sidebarCollapsed } = useShell()

  // The grid drops this column's track at the same time (`ShellGrid`), so a
  // collapsed sidebar takes no width rather than being hidden inside one — but
  // the edge that brings it back has to outlive it.
  if (collapsible && sidebarCollapsed) return <SidebarRail collapsed />

  return (
    <div
      data-sidebar
      className={cn(
        'relative flex h-full min-h-0 flex-col border-r border-border-soft bg-bg',
        className
      )}
    >
      {collapsible && <SidebarRail collapsed={false} />}
      {showSearch && <SearchTrigger collapsible={collapsible} />}
      {selected ? (
        <ExpertForm
          expert={selected}
          conversations={conversations.filter((c) => c.expert_slug === selected.name)}
        />
      ) : (
        <HomeForm experts={experts} conversations={conversations} credits={credits} />
      )}
    </div>
  )
}

// ── an expert is selected ───────────────────────────────────────────────────

function ExpertForm({
  expert,
  conversations,
}: {
  expert: ExpertSummary
  conversations: ConversationSummary[]
}) {
  const pathname = usePathname()
  const [filter, setFilter] = useState('')
  const base = `/experts/${expert.name}`
  const onOverview = pathname === base

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return conversations
    return conversations.filter((c) => (c.title ?? '').toLowerCase().includes(needle))
  }, [conversations, filter])

  return (
    <>
      {/* The identity header, on the neutral identity wash.
          **It is identity, not selection.** The card and the *Overview* row
          below it go to the same page, so when the card also took an active
          fill the column opened with two lit surfaces stacked on top of each
          other. The fill here says "this is the expert"; the row says "this is
          the page you are on", and only one of them ever lights up. */}
      <div className="shrink-0 p-2">
        <Link
          href={base}
          className="flex items-start gap-2.5 rounded-card border border-border-soft bg-panel p-2.5 transition-colors duration-(--dur-1) hover:border-border hover:bg-raised"
        >
          <Avatar expert={expert} size={32} />
          <span className="min-w-0 flex-1">
            <span className="flex items-start gap-1.5">
              {/* Two lines, not one: the name is the subject now, and a subject
                  is often a phrase. */}
              <span className="line-clamp-2 text-sm font-medium text-fg">
                {displayName(expert)}
              </span>
              <StatusDot state={dotState(expert.status, expert.readiness, expert.build_active)} />
            </span>
          </span>
        </Link>
      </div>

      <nav aria-label={`${displayName(expert)} pages`} className="shrink-0 space-y-0.5 px-2 pb-1">
        <SidebarRow href={base} icon={FileText} active={onOverview}>
          Overview
        </SidebarRow>
        {/* One row where Sources and Concepts used to be two
            (docs/plans/expert-brain.md). The count is the sources: the old
            "Concepts" count was every node in the graph, claims included, and
            two thirds of those are sentences. */}
        <SidebarRow
          href={`${base}/knowledge`}
          icon={Orbit}
          active={pathname.startsWith(`${base}/knowledge`)}
          count={expert.source_count || undefined}
          countLabel={
            expert.source_count
              ? `${expert.source_count} ${expert.source_count === 1 ? 'source' : 'sources'}`
              : undefined
          }
        >
          Knowledge
        </SidebarRow>
        {canManage(expert) && (
          // Named and iconed apart from the account's Settings, which is the
          // gear directly below-left in the rail and at the foot of the drawer.
          <SidebarRow
            href={`${base}/settings`}
            icon={SlidersHorizontal}
            active={pathname.startsWith(`${base}/settings`)}
          >
            Expert settings
          </SidebarRow>
        )}
      </nav>

      <div className="flex min-h-0 flex-1 flex-col px-2 pb-2">
        <SectionHeader
          label="Chats"
          count={conversations.length}
          action={
            expert.readiness !== 'pending'
              ? { href: `${base}#ask`, label: 'Ask a new question' }
              : undefined
          }
        />

        {conversations.length > 12 && (
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter chats"
            aria-label="Filter chats"
            className="mb-1 shrink-0 text-xs"
          />
        )}

        <div className="pan-y min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {filtered.length === 0 ? (
            <p className="px-3 py-2 text-xs text-fg-3">
              {conversations.length > 0
                ? 'No chats match.'
                : expert.readiness !== 'pending'
                  ? 'No chats yet. Ask this expert something.'
                  : 'No chats — this expert cannot answer yet.'}
            </p>
          ) : (
            <ChatList chats={filtered} />
          )}
        </div>
      </div>
    </>
  )
}

// ── Home is selected ────────────────────────────────────────────────────────

function HomeForm({
  experts,
  conversations,
  credits,
}: {
  experts: ExpertSummary[]
  conversations: ConversationSummary[]
  credits: CreditState | null
}) {
  const pathname = usePathname()
  const [filter, setFilter] = useState('')
  // Every credit element disappears when the API is not enforcing them, rather
  // than showing a balance that means nothing.
  const showCredits = credits?.credits_enforced === true

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return conversations
    return conversations.filter((c) => (c.title ?? '').toLowerCase().includes(needle))
  }, [conversations, filter])

  return (
    <>
      <div className="shrink-0 p-2">
        <nav aria-label="Workspace" className="space-y-0.5">
          <SidebarRow
            href="/experts"
            icon={LayoutGrid}
            active={pathname === '/experts'}
            count={experts.length || undefined}
          >
            All experts
          </SidebarRow>
          <SidebarRow
            href="/chats"
            icon={MessageSquare}
            active={pathname === '/chats'}
            count={conversations.length || undefined}
          >
            All chats
          </SidebarRow>
          <SidebarRow href="/experts/new" icon={Plus} active={pathname === '/experts/new'}>
            New expert
          </SidebarRow>
          {showCredits && (
            // To the Credits section, and never "active": on /settings the page
            // is titled Settings and opens with Account, so highlighting Credits
            // there said you were somewhere you were not.
            <SidebarRow
              href="/settings#credits"
              icon={Wallet}
              active={false}
              // Every other number in this column counts the things in its row.
              // A bare "2" here read as two credit items.
              countText={`${credits.balance} cr`}
              countLabel={`${credits.balance} credits`}
            >
              Credits
            </SidebarRow>
          )}
        </nav>
      </div>

      <div className="flex min-h-0 flex-1 flex-col px-2 pb-2">
        <SectionHeader label="Chats" count={conversations.length} />

        {conversations.length > 12 && (
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter chats"
            aria-label="Filter chats"
            className="mb-1 shrink-0 text-xs"
          />
        )}

        <div className="pan-y min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {filtered.length === 0 ? (
            <p className="px-3 py-2 text-xs text-fg-3">
              {conversations.length === 0
                ? 'No chats yet. Open an expert to ask it something.'
                : 'No chats match.'}
            </p>
          ) : (
            <ChatList chats={filtered} experts={experts} />
          )}
        </div>
      </div>
    </>
  )
}

// ── search ──────────────────────────────────────────────────────────────────

/**
 * Opens the ⌘K palette. From `lg` up the top bar has no search button, so
 * without this the palette was reachable only by a shortcut nothing on screen
 * mentioned.
 *
 * Drawn as a field because that is what it does, but it is a button: typing
 * happens in the palette, which already owns the filtering and the keyboard.
 * The shortcut hint waits for the client — the server cannot know whether to
 * say ⌘ or Ctrl — and is hidden on a coarse pointer, where there is no keyboard
 * to press it on.
 */
function SearchTrigger({ collapsible }: { collapsible: boolean }) {
  const { openPalette, toggleSidebar } = useShell()
  const mac = useSyncExternalStore(
    noopSubscribe,
    () => /Mac|iPhone|iPad/.test(navigator.platform),
    () => null
  )
  const shortcut = mac === null ? null : mac ? '⌘K' : 'Ctrl K'

  return (
    // The top bar's height and the top bar's hairline, so the line under the
    // page's bar carries on across the navigation to the window's edge.
    <div className="flex h-topbar shrink-0 items-center gap-1 border-b border-border-soft px-2">
      <button
        type="button"
        onClick={openPalette}
        className={cn(
          'flex h-(--row-h) w-full items-center gap-2 rounded-full border border-border bg-panel pr-1.5 pl-3 text-sm text-fg-3',
          'transition-colors duration-(--dur-1) hover:border-fg-4 hover:text-fg-2'
        )}
      >
        <Search className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate text-left">Search</span>
        {shortcut && (
          <kbd
            aria-hidden
            className="hidden rounded-full border border-border bg-raised px-1.5 font-sans text-label leading-[18px] text-fg-2 pointer-fine:inline"
          >
            {shortcut}
          </kbd>
        )}
      </button>
      {/* The visible way to fold the column away. The edge strip does the
          same, but nobody finds a control that is invisible until hovered. */}
      {collapsible && (
        <Tooltip
          side="bottom"
          content={mac === false ? 'Collapse sidebar (Ctrl \\)' : 'Collapse sidebar (⌘\\)'}
        >
          <button
            type="button"
            onClick={toggleSidebar}
            aria-label="Collapse the sidebar"
            className={cn(
              'grid size-(--row-h) shrink-0 place-items-center rounded-full text-fg-3',
              'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg'
            )}
          >
            <PanelLeftClose className="size-4" />
          </button>
        </Tooltip>
      )}
    </div>
  )
}

/**
 * The column's own edge, as the control that folds it away.
 *
 * A drag-handle-shaped strip down the sidebar's trailing edge: invisible until
 * you reach it, a hairline under the cursor, and a click toggles the column
 * (`⌘\` does the same from the keyboard). It replaces a button in the search
 * row, which spent a permanent 28px of the column's one toolbar on something
 * used once a session — and it puts the affordance where the hand already goes
 * to resize a panel.
 *
 * Collapsed, the strip sits against the rail instead, `fixed`, because the
 * column it belonged to no longer has a track in the grid.
 */
function SidebarRail({ collapsed }: { collapsed: boolean }) {
  const { toggleSidebar } = useShell()
  return (
    <button
      type="button"
      onClick={toggleSidebar}
      // Hidden from assistive tech and the tab order: the labelled buttons in
      // the search row and the top bar are the accessible controls; this is a
      // bigger mouse target for the same action.
      aria-hidden="true"
      tabIndex={-1}
      title={collapsed ? 'Expand the sidebar' : 'Collapse the sidebar'}
      className={cn(
        'group absolute inset-y-0 z-20 hidden w-3 lg:block',
        // The cursor says which way it goes before anything is clicked.
        // Centred on the boundary in both states, so the hairline lands on the
        // edge itself: collapsed, `left-rail` put the strip's *start* there and
        // drew the line 6px into the page.
        collapsed
          ? 'fixed left-[calc(var(--spacing-rail)-0.375rem)] cursor-e-resize'
          : '-right-1.5 cursor-w-resize'
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-transparent',
          'transition-colors duration-(--dur-1) group-hover:bg-fg-4 group-focus-visible:bg-fg'
        )}
      />
    </button>
  )
}

const noopSubscribe = () => () => {}

// ── rows ────────────────────────────────────────────────────────────────────

function SidebarRow({
  href,
  icon: Icon,
  active,
  count,
  countText,
  countLabel,
  children,
}: {
  href: string
  icon: React.ComponentType<{ className?: string }>
  active: boolean
  count?: number
  /** Overrides the rendered count, for a value that is not a number of rows. */
  countText?: string
  /** What the count *means*, for a reader who cannot infer it from the label. */
  countLabel?: string
  children: React.ReactNode
}) {
  const shown = countText ?? (count === undefined ? null : formatInt(count))
  return (
    <Link
      href={href}
      prefetch
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex h-(--row-h) items-center gap-2.5 rounded-full px-3 text-sm',
        'ring-1 transition-colors duration-(--dur-1) ring-inset',
        active
          ? 'bg-raised font-medium text-fg ring-border'
          : 'text-fg-2 ring-transparent hover:bg-raised hover:text-fg'
      )}
    >
      <Icon className={cn('size-4 shrink-0', active ? 'text-fg' : 'text-fg-3')} />
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {/* `title` only. An `aria-label` here would rename the whole row — the
          Credits link announced itself as "Credits 2 credits" — and make a
          plain span something a label query can find. */}
      {shown !== null && (
        <span
          title={countLabel}
          className={cn(
            'rounded-full border px-1.5 text-label leading-[18px]',
            active ? 'border-transparent bg-fg text-bg' : 'border-border text-fg-3'
          )}
        >
          {shown}
        </span>
      )}
    </Link>
  )
}

/**
 * A section label, its count, and at most one action.
 *
 * Shared by both forms so the two states of this column have the same rhythm:
 * one `--row-h` header, then rows. The label is not a heading element — the
 * page below owns the document outline, and a sidebar full of `h3`s makes a
 * screen reader's heading list useless for navigating the actual content.
 */
function SectionHeader({
  label,
  count,
  action,
}: {
  label: string
  count?: number
  action?: { href: string; label: string }
}) {
  return (
    <div className="flex h-(--row-h) shrink-0 items-center gap-1 px-3">
      <span className="text-label tracking-[0.04em] text-fg-3 uppercase">{label}</span>
      {count !== undefined && count > 0 && <span className="text-xs text-fg-3">{count}</span>}
      {action && (
        // Labelled *and* tipped: a bare `+` at the head of a chat list is a
        // guess for anyone with a mouse, and `aria-label` says nothing to them.
        <Tooltip content={action.label} side="right">
          <Link
            href={action.href}
            aria-label={action.label}
            onClick={(event) => {
              // Already on the page the link points into: Next only scrolls to
              // a hash, so put the cursor in the question field as well.
              if (focusAskField(action.href)) event.preventDefault()
            }}
            className="ml-auto grid size-(--icon-btn-sm) place-items-center rounded-chip text-fg-3 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
          >
            <Plus className="size-3.5" />
          </Link>
        </Tooltip>
      )}
    </div>
  )
}

/**
 * The chats, under day headings.
 *
 * The headings depend on what time it is, so they appear only once the browser
 * has taken over: the server renders one ungrouped list and the first client
 * render matches it, which is the only way to put "Today" in a list without
 * risking a hydration mismatch at midnight. See `lib/chat-groups.ts`.
 */
function ChatList({ chats, experts }: { chats: ConversationSummary[]; experts?: ExpertSummary[] }) {
  const pathname = usePathname()
  const mounted = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  )
  const groups = useMemo(() => groupChats(chats, mounted ? new Date() : null), [chats, mounted])

  return (
    <>
      {groups.map((group) => (
        <div key={group.label ?? 'all'} className="space-y-0.5">
          {group.label && (
            <p className="px-3 pt-2 pb-0.5 text-label tracking-[0.04em] text-fg-3 uppercase">
              {group.label}
            </p>
          )}
          {group.chats.map((conversation) => (
            <ChatRow
              key={conversation.id}
              conversation={conversation}
              expert={experts?.find((e) => e.name === conversation.expert_slug) ?? null}
              active={pathname === `/chats/${conversation.id}`}
            />
          ))}
        </div>
      ))}
    </>
  )
}

function ChatRow({
  conversation,
  expert,
  active,
}: {
  conversation: ConversationSummary
  /** Only on Home, where the list spans experts and the title alone is ambiguous. */
  expert?: ExpertSummary | null
  active: boolean
}) {
  return (
    <div
      className={cn(
        'group relative rounded-full ring-1 transition-colors duration-(--dur-1) ring-inset',
        active ? 'bg-raised ring-border' : 'ring-transparent hover:bg-raised'
      )}
    >
      <Link
        href={`/chats/${conversation.id}`}
        prefetch
        aria-current={active ? 'page' : undefined}
        className={cn(
          'flex h-(--row-h) items-center gap-2 rounded-full pr-8 pl-3 text-sm',
          active ? 'font-medium text-fg' : 'text-fg-2 group-hover:text-fg'
        )}
      >
        {expert && (
          <span className="shrink-0">
            <Avatar expert={expert} size={18} />
          </span>
        )}
        <span className="min-w-0 flex-1 truncate">{chatTitle(conversation.title)}</span>
        <RelativeTime iso={conversation.last_message_at} className="shrink-0 text-xs text-fg-3" />
      </Link>
      <ChatRowMenu conversation={conversation} active={active} />
    </div>
  )
}

/**
 * Rename and Delete, on the row.
 *
 * Both already existed — in the *chat page's* overflow, which you had to open
 * the chat to reach. Hidden until hover or focus with a fine pointer, always
 * visible where there is no hover.
 */
function ChatRowMenu({
  conversation,
  active,
}: {
  conversation: ConversationSummary
  active: boolean
}) {
  const router = useRouter()
  const [renaming, setRenaming] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [title, setTitle] = useState(conversation.title ?? '')

  const { run: rename, pending: saving } = useApiAction(
    () =>
      apiSend(
        `/api/conversations/${conversation.id}`,
        'PATCH',
        { title: title.trim() },
        'Could not rename that chat.'
      ),
    {
      error: 'Could not rename that chat.',
      onSuccess: () => setRenaming(false),
    }
  )

  const { run: remove, pending: deleting } = useApiAction(
    () =>
      apiVoid(
        `/api/conversations/${conversation.id}`,
        { method: 'DELETE' },
        'Could not delete that chat.'
      ),
    {
      error: 'Could not delete that chat.',
      onSuccess: () => {
        setConfirming(false)
        // The open chat just stopped existing; staying on it would 404 on the
        // next refresh. Its expert is the nearest page that still does.
        if (active) router.push(`/experts/${conversation.expert_slug}`)
      },
    }
  )

  return (
    <>
      <MenuRoot>
        <MenuTrigger
          aria-label={`Actions for ${chatTitle(conversation.title)}`}
          className={cn(
            'absolute top-1/2 right-1 grid size-(--icon-btn-sm) -translate-y-1/2 place-items-center',
            'rounded-chip text-fg-3 transition-[opacity,color] duration-(--dur-1) hover:text-fg',
            'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
            '[@media(hover:none)]:opacity-100'
          )}
        >
          <MoreHorizontal className="size-3.5" />
        </MenuTrigger>
        <MenuContent align="start">
          <MenuItem
            onClick={() => {
              setTitle(conversation.title ?? '')
              setRenaming(true)
            }}
          >
            Rename
          </MenuItem>
          <MenuSeparator />
          <MenuItem tone="danger" onClick={() => setConfirming(true)}>
            Delete chat
          </MenuItem>
        </MenuContent>
      </MenuRoot>

      {/* Mounted only while open. A sidebar holds twenty chat rows, and two
          dialogs each — forty Base UI trees — is work the shell does on every
          page load for something almost nobody opens. */}
      {renaming && (
        <Dialog
          open
          onOpenChange={setRenaming}
          title="Rename this chat"
          footer={
            <>
              <Button variant="ghost" onClick={() => setRenaming(false)}>
                Cancel
              </Button>
              <Button
                loading={saving}
                disabled={title.trim().length === 0}
                onClick={() => void rename()}
                minWidth={92}
              >
                Rename
              </Button>
            </>
          }
        >
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            aria-label="New chat title"
            autoFocus
            onKeyDown={(event) => {
              if (event.key === 'Enter' && title.trim().length > 0) void rename()
            }}
          />
        </Dialog>
      )}

      {confirming && (
        <Dialog
          open
          onOpenChange={setConfirming}
          title="Delete this chat?"
          description="The whole conversation goes. The expert and its sources are untouched."
          disablePointerDismissal
          footer={
            <>
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                Keep it
              </Button>
              <Button
                variant="danger"
                loading={deleting}
                onClick={() => void remove()}
                minWidth={92}
              >
                Delete
              </Button>
            </>
          }
        >
          <p className="text-sm text-fg-3">{chatTitle(conversation.title)}</p>
        </Dialog>
      )}
    </>
  )
}
