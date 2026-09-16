'use client'

import {
  FileText,
  Moon,
  MessageSquare,
  Network,
  Plus,
  Search,
  Settings,
  Sun,
  Table,
  Monitor,
} from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { Sheet } from '@/components/shell/sheet'
import { useShell } from '@/components/shell/shell-context'
import { BaseDialog } from '@/components/ui/dialog'
import { cn } from '@/lib/cn'
import { displayName, subtitle } from '@/lib/persona'
import { chatTitle, relativeTime } from '@/lib/format'
import { useIsTabletUp } from '@/hooks/use-media-query'
import type { ConversationSummary, ExpertSummary } from '@/lib/api/types'

/**
 * ⌘K.
 *
 * Hand-rolled rather than taken from a library, because the list is three
 * fixed sections over data the shell already has in memory — there is nothing
 * to fetch, nothing to debounce, and a filter over two arrays is less code than
 * configuring a combobox. On a phone it is a full-height bottom sheet with the
 * field focused, since a centred 560px panel is not a phone surface.
 */

interface Item {
  id: string
  section: 'Experts' | 'Chats' | 'Actions'
  label: string
  hint?: string
  icon?: React.ReactNode
  run: () => void
  /** Everything searched, lowercased once at build time. */
  haystack: string
}

export function CommandPalette({
  experts,
  conversations,
}: {
  experts: ExpertSummary[]
  conversations: ConversationSummary[]
}) {
  const { paletteOpen, setPaletteOpen } = useShell()
  const router = useRouter()
  const { setTheme } = useTheme()
  const isTabletUp = useIsTabletUp()
  const [queryText, setQueryText] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // ⌘K / Ctrl+K anywhere. Not bound when a text field has focus and the user is
  // holding no modifier, so typing "k" in the composer never opens it.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        setPaletteOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setPaletteOpen])

  const close = () => {
    setPaletteOpen(false)
    setQueryText('')
    setCursor(0)
  }

  const items = useMemo<Item[]>(() => {
    const go = (href: string) => () => {
      close()
      router.push(href)
    }

    const expertItems: Item[] = experts.map((expert) => ({
      id: `expert:${expert.id}`,
      section: 'Experts',
      label: displayName(expert),
      hint: subtitle(expert) ?? undefined,
      icon: (
        <span>
          <Avatar expert={expert} size={16} />
        </span>
      ),
      run: go(`/experts/${expert.name}`),
      haystack: `${expert.persona_name ?? ''} ${expert.topic} ${expert.name}`.toLowerCase(),
    }))

    const chatItems: Item[] = conversations.map((conversation) => ({
      id: `chat:${conversation.id}`,
      section: 'Chats',
      label: chatTitle(conversation.title),
      hint: `${conversation.expert_persona_name ?? conversation.expert_topic} · ${relativeTime(conversation.last_message_at)}`,
      icon: <MessageSquare className="size-4 text-fg-3" />,
      run: go(`/chats/${conversation.id}`),
      haystack: `${conversation.title ?? ''} ${conversation.expert_topic}`.toLowerCase(),
    }))

    const actions: Item[] = [
      {
        id: 'action:new',
        section: 'Actions',
        label: 'Build a new expert',
        icon: <Plus className="size-4 text-fg-3" />,
        run: go('/experts/new'),
        haystack: 'build new expert create topic',
      },
      {
        id: 'action:experts',
        section: 'Actions',
        label: 'All experts',
        icon: <FileText className="size-4 text-fg-3" />,
        run: go('/experts'),
        haystack: 'home all experts',
      },
      {
        id: 'action:chats',
        section: 'Actions',
        label: 'All chats',
        icon: <MessageSquare className="size-4 text-fg-3" />,
        run: go('/chats'),
        haystack: 'all chats conversations',
      },
      {
        id: 'action:settings',
        section: 'Actions',
        label: 'Settings',
        icon: <Settings className="size-4 text-fg-3" />,
        run: go('/settings'),
        haystack: 'settings account credits theme',
      },
      {
        id: 'action:theme-dark',
        section: 'Actions',
        label: 'Dark theme',
        icon: <Moon className="size-4 text-fg-3" />,
        run: () => {
          setTheme('dark')
          close()
        },
        haystack: 'dark theme appearance',
      },
      {
        id: 'action:theme-light',
        section: 'Actions',
        label: 'Light theme',
        icon: <Sun className="size-4 text-fg-3" />,
        run: () => {
          setTheme('light')
          close()
        },
        haystack: 'light theme appearance',
      },
      {
        id: 'action:theme-system',
        section: 'Actions',
        label: 'Match the system theme',
        icon: <Monitor className="size-4 text-fg-3" />,
        run: () => {
          setTheme('system')
          close()
        },
        haystack: 'system theme appearance auto',
      },
    ]

    // One expert's sub-pages, so "graph" reaches the page and not only the
    // expert — the commonest thing to want from a palette.
    const subPages: Item[] = experts.flatMap((expert) => [
      {
        id: `sources:${expert.id}`,
        section: 'Actions' as const,
        label: `${displayName(expert)} — sources`,
        icon: <Table className="size-4 text-fg-3" />,
        run: go(`/experts/${expert.name}/sources`),
        haystack: `sources ledger ${expert.persona_name ?? ''} ${expert.topic}`.toLowerCase(),
      },
      {
        id: `graph:${expert.id}`,
        section: 'Actions' as const,
        label: `${displayName(expert)} — graph`,
        icon: <Network className="size-4 text-fg-3" />,
        run: go(`/experts/${expert.name}/graph`),
        haystack: `graph concepts ${expert.persona_name ?? ''} ${expert.topic}`.toLowerCase(),
      },
    ])

    return [...expertItems, ...chatItems, ...actions, ...subPages]
    // `close` and `go` are stable enough for a list rebuilt on every open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [experts, conversations, router, setTheme])

  const matches = useMemo(() => {
    const needle = queryText.trim().toLowerCase()
    const filtered = needle
      ? items.filter(
          (item) => item.haystack.includes(needle) || item.label.toLowerCase().includes(needle)
        )
      : // With no query, the sub-page actions are noise.
        items.filter((item) => !item.id.startsWith('sources:') && !item.id.startsWith('graph:'))
    return filtered.slice(0, 40)
  }, [items, queryText])

  const sections = useMemo(() => {
    const order: Item['section'][] = ['Experts', 'Chats', 'Actions']
    return order
      .map((section) => ({ section, rows: matches.filter((m) => m.section === section) }))
      .filter((group) => group.rows.length > 0)
  }, [matches])

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((c) => Math.min(c + 1, matches.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((c) => Math.max(c - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      matches[cursor]?.run()
    }
  }

  // Combobox semantics: the highlighted row was visual only, so a screen reader
  // heard nothing move as the arrows did.
  const listId = 'command-palette-results'
  const optionId = (index: number) => `command-palette-option-${index}`

  const body = (
    <div className="flex min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border-soft px-3">
        <Search className="size-4 shrink-0 text-fg-3" aria-hidden="true" />
        <input
          ref={inputRef}
          value={queryText}
          onChange={(event) => {
            setQueryText(event.target.value)
            setCursor(0)
          }}
          onKeyDown={onKeyDown}
          placeholder="Search experts, chats and actions"
          // Not just "Search": the top bar's own button carries that label, and
          // two controls with the same accessible name in one page is a real
          // ambiguity for anyone navigating by name.
          aria-label="Search experts, chats and actions"
          role="combobox"
          aria-expanded={matches.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={matches[cursor] ? optionId(cursor) : undefined}
          className="h-full min-w-0 flex-1 bg-transparent text-sm text-fg placeholder:text-fg-3 focus:outline-none"
        />
      </div>
      <div
        id={listId}
        role="listbox"
        aria-label="Results"
        className="pan-y min-h-0 flex-1 overflow-y-auto overscroll-contain p-1.5"
      >
        {sections.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-fg-3">Nothing matches.</p>
        ) : (
          sections.map((group) => (
            <div key={group.section} role="group" aria-label={group.section} className="mb-1">
              <p
                aria-hidden="true"
                className="px-2 pt-1.5 pb-1 text-label tracking-[0.04em] text-fg-3 uppercase"
              >
                {group.section}
              </p>
              {group.rows.map((item) => {
                const index = matches.indexOf(item)
                return (
                  <button
                    key={item.id}
                    id={optionId(index)}
                    type="button"
                    role="option"
                    aria-selected={index === cursor}
                    tabIndex={-1}
                    onMouseEnter={() => setCursor(index)}
                    onClick={item.run}
                    className={cn(
                      'flex h-(--row-h) min-h-9 w-full items-center gap-2 rounded-row px-2 text-left text-sm',
                      'transition-colors duration-(--dur-1)',
                      index === cursor ? 'bg-border text-fg' : 'text-fg-2'
                    )}
                  >
                    {item.icon}
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.hint && (
                      <span className="hidden max-w-48 shrink-0 truncate text-xs text-fg-3 sm:inline">
                        {item.hint}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          ))
        )}
      </div>
    </div>
  )

  if (!isTabletUp) {
    return (
      <Sheet
        open={paletteOpen}
        onOpenChange={(open) => (open ? setPaletteOpen(true) : close())}
        side="bottom"
        title="Search"
        hideTitle
        snapPoints={[0.92]}
      >
        {body}
      </Sheet>
    )
  }

  return (
    <BaseDialog.Root
      open={paletteOpen}
      onOpenChange={(open) => (open ? setPaletteOpen(true) : close())}
    >
      <BaseDialog.Portal>
        <BaseDialog.Backdrop className="fixed inset-0 z-40 bg-black/50 transition-opacity duration-(--dur-2) data-ending-style:opacity-0 data-ending-style:duration-(--dur-1) data-starting-style:opacity-0" />
        <BaseDialog.Popup
          initialFocus={inputRef}
          className={cn(
            'fixed top-[15vh] left-1/2 z-50 flex max-h-[60vh] w-[calc(100vw-3rem)] max-w-[560px] -translate-x-1/2 flex-col',
            // The palette and popovers are the only shadowed elements.
            'overflow-hidden rounded-panel border border-border bg-raised shadow-2xl shadow-black/40 outline-none',
            'transition-[opacity,transform] duration-(--dur-2) ease-(--ease-out)',
            'data-starting-style:scale-[0.98] data-starting-style:opacity-0',
            'data-ending-style:opacity-0 data-ending-style:duration-(--dur-1)'
          )}
        >
          <BaseDialog.Title className="sr-only">Search</BaseDialog.Title>
          {body}
        </BaseDialog.Popup>
      </BaseDialog.Portal>
    </BaseDialog.Root>
  )
}
