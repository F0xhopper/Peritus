'use client'

import { MessageSquare, MoreHorizontal, Trash2 } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { Avatar } from '@/components/identity/avatar'
import { TopBar } from '@/components/shell/top-bar'
import { Empty } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import {
  MenuContent,
  MenuItem,
  MenuLinkItem,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
} from '@/components/ui/menu'
import { RelativeTime } from '@/components/ui/relative-time'
import { cn } from '@/lib/cn'
import { chatTitle, plural } from '@/lib/format'
import { displayName } from '@/lib/persona'
import type { ConversationSummary, ExpertSummary } from '@/lib/api/types'

/**
 * Every conversation, grouped by expert.
 *
 * Delete is optimistic with a five-second undo, and the DELETE is only sent
 * when the window closes. A chat is a real piece of work — a question someone
 * asked and an answer with citations — so "undo" has to be a real undo, not a
 * confirmation dialog in front of an irreversible action.
 */
const UNDO_MS = 5000

export function ChatsListPage({
  conversations,
  experts,
}: {
  conversations: ConversationSummary[]
  experts: ExpertSummary[]
}) {
  const router = useRouter()
  const [filter, setFilter] = useState('')
  // Rows hidden pending an undo. Not removed from the server yet.
  const [pendingDelete, setPendingDelete] = useState<Set<string>>(() => new Set())

  const byName = useMemo(() => new Map(experts.map((expert) => [expert.name, expert])), [experts])

  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const visible = conversations.filter(
      (conversation) =>
        !pendingDelete.has(conversation.id) &&
        (!needle || (conversation.title ?? '').toLowerCase().includes(needle))
    )
    const map = new Map<string, ConversationSummary[]>()
    for (const conversation of visible) {
      const list = map.get(conversation.expert_slug) ?? []
      list.push(conversation)
      map.set(conversation.expert_slug, list)
    }
    return [...map.entries()]
  }, [conversations, filter, pendingDelete])

  const remove = (conversation: ConversationSummary) => {
    setPendingDelete((previous) => new Set(previous).add(conversation.id))
    let undone = false

    toast('Chat deleted', {
      duration: UNDO_MS,
      action: {
        label: 'Undo',
        onClick: () => {
          undone = true
          setPendingDelete((previous) => {
            const next = new Set(previous)
            next.delete(conversation.id)
            return next
          })
        },
      },
      onAutoClose: () => {
        if (undone) return
        void (async () => {
          try {
            const res = await fetch(`/api/conversations/${conversation.id}`, { method: 'DELETE' })
            if (!res.ok) throw new Error()
            router.refresh()
          } catch {
            // Put the row back: nothing was deleted.
            setPendingDelete((previous) => {
              const next = new Set(previous)
              next.delete(conversation.id)
              return next
            })
            toast.error('Could not delete that chat.')
          }
        })()
      },
    })
  }

  return (
    <>
      <TopBar title="Chats" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-3xl px-4 pt-4 pb-10 md:px-6">
          <h1 className="text-title font-medium text-fg">Chats</h1>
          <p className="mt-1 text-sm text-fg-3">
            Every conversation, grouped by the expert that answered it.
          </p>

          {conversations.length > 6 && (
            <Input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Search by title"
              aria-label="Search chats"
              className="mt-4"
            />
          )}

          {groups.length === 0 ? (
            <Empty icon={MessageSquare} className="mt-8">
              {conversations.length === 0
                ? 'No chats yet. Open an expert from the rail and ask it something.'
                : 'No chats match that search.'}
            </Empty>
          ) : (
            <div className="mt-5 space-y-6">
              {groups.map(([slug, list]) => {
                const expert =
                  byName.get(slug) ??
                  ({
                    name: slug,
                    persona_name: list[0].expert_persona_name,
                    topic: list[0].expert_topic,
                    avatar: null,
                    // See `recent-chats.tsx`: the joined version is what lets a
                    // chat with an expert outside this page still show its face.
                    picture: list[0].expert_picture_version
                      ? { version: list[0].expert_picture_version }
                      : null,
                  } as Pick<
                    ExpertSummary,
                    'name' | 'persona_name' | 'topic' | 'avatar' | 'picture'
                  >)

                return (
                  <section key={slug}>
                    <Link
                      href={`/experts/${slug}`}
                      className="flex min-h-(--row-h) items-center gap-2 transition-opacity duration-(--dur-1) hover:opacity-80"
                    >
                      <Avatar expert={expert} size={20} />
                      <h2 className="min-w-0 truncate text-sm font-medium text-fg">
                        {displayName(expert)}
                      </h2>
                      <span className="shrink-0 text-xs text-fg-3">{list.length}</span>
                    </Link>

                    <ul className="mt-2 space-y-0.5 rounded-card bg-panel p-1">
                      {list.map((conversation) => (
                        <li key={conversation.id} className="group relative">
                          <Link
                            href={`/chats/${conversation.id}`}
                            prefetch
                            className={cn(
                              'flex h-(--row-h) items-center gap-2 rounded-row px-2 pr-10 text-sm',
                              'transition-colors duration-(--dur-1) hover:bg-raised'
                            )}
                          >
                            <span className="min-w-0 flex-1 truncate text-fg-2">
                              {chatTitle(conversation.title)}
                            </span>
                            <span className="shrink-0 text-xs text-fg-3">
                              {plural(conversation.message_count, 'msg', 'msgs')}
                            </span>
                            <RelativeTime
                              iso={conversation.last_message_at}
                              className="hidden shrink-0 text-xs text-fg-3 sm:inline"
                            />
                          </Link>

                          <MenuRoot>
                            <MenuTrigger
                              aria-label={`Actions for ${conversation.title ?? 'this chat'}`}
                              className={cn(
                                'absolute top-1/2 right-1.5 grid size-(--icon-btn-sm) -translate-y-1/2 place-items-center',
                                'rounded-chip text-fg-3 transition-[opacity,color] duration-(--dur-1)',
                                'hover:text-fg',
                                'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
                                '[@media(hover:none)]:opacity-100'
                              )}
                            >
                              <MoreHorizontal className="size-3.5" />
                            </MenuTrigger>
                            <MenuContent>
                              <MenuLinkItem render={<Link href={`/chats/${conversation.id}`} />}>
                                Open
                              </MenuLinkItem>
                              <MenuLinkItem render={<Link href={`/experts/${slug}`} />}>
                                Open the expert
                              </MenuLinkItem>
                              <MenuSeparator />
                              <MenuItem tone="danger" onClick={() => remove(conversation)}>
                                <Trash2 className="size-3.5" />
                                Delete
                              </MenuItem>
                            </MenuContent>
                          </MenuRoot>
                        </li>
                      ))}
                    </ul>
                  </section>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
