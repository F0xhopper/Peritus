'use client'

import {
  FileText,
  LayoutGrid,
  MessageSquare,
  Network,
  Plus,
  Search,
  Settings as SettingsIcon,
  Table,
  Wallet,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useMemo, useState, useSyncExternalStore } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { useShell } from '@/components/shell/shell-context'
import { Input } from '@/components/ui/input'
import { StatusDot, dotState } from '@/components/ui/status-dot'
import { RelativeTime } from '@/components/ui/relative-time'
import { cn } from '@/lib/cn'
import { chatTitle } from '@/lib/format'
import { displayName, subtitle } from '@/lib/persona'
import { useActiveSlug } from '@/components/shell/rail'
import { focusAskField } from '@/components/chat/new-chat-composer'
import type { ConversationSummary, CreditState, ExpertSummary } from '@/lib/api/types'

/**
 * The second column: the selected expert's pages and chats, or — on Home — the
 * workspace.
 *
 * Active rows are a rounded `--raised` fill with no rule and no left bar. That
 * is the third reference's rule (web-design.md §1c): grouping is done by
 * rounded surfaces, so the shell carries far fewer borders.
 *
 * **This column never lists the experts.** The rail immediately to its left
 * *is* the expert list — one avatar each, with the name in a tooltip — so a
 * second list of the same five names in the next column said nothing new and
 * pushed everything that was actually useful below the fold. Home's second
 * column is the two things the rail cannot reach: where to go in the workspace,
 * and the chats, which belong to no single expert.
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
  className,
}: ExpertSidebarProps) {
  // A chat belongs to an expert even though its URL does not name one, so the
  // sidebar stays on that expert while a conversation is open.
  const slug = useActiveSlug(conversations)
  const selected = experts.find((e) => e.name === slug) ?? null

  return (
    <div className={cn('flex h-full min-h-0 flex-col bg-panel', className)}>
      {showSearch && <SearchTrigger />}
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

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return conversations
    return conversations.filter((c) => (c.title ?? '').toLowerCase().includes(needle))
  }, [conversations, filter])

  return (
    <>
      {/* The identity header, on the neutral identity wash. */}
      <div className="shrink-0 p-2">
        <Link
          href={base}
          className="flex items-start gap-2.5 rounded-card bg-expert-soft p-2.5 transition-colors duration-(--dur-1) hover:bg-expert/15"
        >
          <Avatar expert={expert} size={32} />
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              <span className="truncate text-sm font-medium text-fg">
                {displayName(expert)}
              </span>
              <StatusDot state={dotState(expert.status, expert.readiness, expert.build_active)} />
            </span>
            {subtitle(expert) && (
              <span className="mt-0.5 block truncate text-xs text-fg-3">{subtitle(expert)}</span>
            )}
          </span>
        </Link>
      </div>

      <nav
        aria-label={`${displayName(expert)} pages`}
        className="shrink-0 space-y-0.5 px-2 pb-1"
      >
        <SidebarRow href={base} icon={FileText} active={pathname === base}>
          Overview
        </SidebarRow>
        <SidebarRow
          href={`${base}/sources`}
          icon={Table}
          active={pathname.startsWith(`${base}/sources`)}
          count={expert.source_count || undefined}
        >
          Sources
        </SidebarRow>
        <SidebarRow
          href={`${base}/graph`}
          icon={Network}
          active={pathname.startsWith(`${base}/graph`)}
          count={expert.node_count || undefined}
        >
          Graph
        </SidebarRow>
        <SidebarRow
          href={`${base}/settings`}
          icon={SidebarSettingsIcon}
          active={pathname.startsWith(`${base}/settings`)}
        >
          Settings
        </SidebarRow>
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

        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto overscroll-contain pan-y">
          {filtered.length === 0 ? (
            <p className="px-1.5 py-2 text-xs text-fg-3">
              {conversations.length > 0
                ? 'No chats match.'
                : expert.readiness !== 'pending'
                  ? 'No chats yet. Ask this expert something.'
                  : 'No chats — this expert cannot answer yet.'}
            </p>
          ) : (
            filtered.map((conversation) => (
              <ChatRow
                key={conversation.id}
                conversation={conversation}
                active={pathname === `/chats/${conversation.id}`}
              />
            ))
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
            <SidebarRow href="/settings#credits" icon={Wallet} active={false} count={credits.balance}>
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

        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto overscroll-contain pan-y">
          {filtered.length === 0 ? (
            <p className="px-1.5 py-2 text-xs text-fg-3">
              {conversations.length === 0
                ? 'No chats yet. Open an expert to ask it something.'
                : 'No chats match.'}
            </p>
          ) : (
            filtered.map((conversation) => (
              <ChatRow
                key={conversation.id}
                conversation={conversation}
                expert={experts.find((e) => e.name === conversation.expert_slug) ?? null}
                active={pathname === `/chats/${conversation.id}`}
              />
            ))
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
function SearchTrigger() {
  const { openPalette } = useShell()
  const shortcut = useSyncExternalStore(
    noopSubscribe,
    () => (/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘K' : 'Ctrl K'),
    () => null,
  )

  return (
    <div className="shrink-0 px-2 pt-2">
      <button
        type="button"
        onClick={openPalette}
        className={cn(
          'flex h-(--row-h) w-full items-center gap-2 rounded-row border border-border bg-raised px-2 text-sm text-fg-3',
          'transition-colors duration-(--dur-1) hover:border-fg-4 hover:text-fg-2',
        )}
      >
        <Search className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate text-left">Search</span>
        {shortcut && (
          <kbd aria-hidden className="hidden font-sans text-xs text-fg-3 pointer-fine:inline">{shortcut}</kbd>
        )}
      </button>
    </div>
  )
}

const noopSubscribe = () => () => {}

// ── rows ────────────────────────────────────────────────────────────────────

function SidebarRow({
  href,
  icon: Icon,
  active,
  count,
  children,
}: {
  href: string
  icon: React.ComponentType<{ className?: string }>
  active: boolean
  count?: number
  children: React.ReactNode
}) {
  return (
    <Link
      href={href}
      prefetch
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex h-(--row-h) items-center gap-2 rounded-row px-1.5 text-sm',
        'transition-colors duration-(--dur-1)',
        active ? 'bg-raised text-fg' : 'text-fg-2 hover:bg-raised hover:text-fg',
      )}
    >
      <Icon className={cn('size-4 shrink-0', active ? 'text-fg-2' : 'text-fg-3')} />
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {count !== undefined && <span className="text-xs text-fg-3">{count}</span>}
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
    <div className="flex h-(--row-h) shrink-0 items-center gap-1 px-1.5">
      <span className="text-label tracking-[0.04em] text-fg-3 uppercase">{label}</span>
      {count !== undefined && count > 0 && (
        <span className="text-xs text-fg-3">{count}</span>
      )}
      {action && (
        <Link
          href={action.href}
          aria-label={action.label}
          onClick={(event) => {
            // Already on the page the link points into: Next only scrolls to a
            // hash, so put the cursor in the question field as well.
            if (focusAskField(action.href)) event.preventDefault()
          }}
          className="ml-auto grid size-(--icon-btn-sm) place-items-center rounded-chip text-fg-3 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
        >
          <Plus className="size-3.5" />
        </Link>
      )}
    </div>
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
    <Link
      href={`/chats/${conversation.id}`}
      prefetch
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex h-(--row-h) items-center gap-2 rounded-row px-1.5 text-sm',
        'transition-colors duration-(--dur-1)',
        active ? 'bg-raised text-fg' : 'text-fg-2 hover:bg-raised hover:text-fg',
      )}
    >
      {expert && (
        <span className="shrink-0">
          <Avatar expert={expert} size={18} />
        </span>
      )}
      <span className="min-w-0 flex-1 truncate">
        {chatTitle(conversation.title)}
      </span>
      <RelativeTime
        iso={conversation.last_message_at}
        className="shrink-0 text-xs text-fg-3"
      />
    </Link>
  )
}

// `Settings` collides with the page component's name in a few files; aliased
// here so the import list above reads as the rows do.
const SidebarSettingsIcon = SettingsIcon
