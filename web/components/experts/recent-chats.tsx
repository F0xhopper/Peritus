import Link from 'next/link'

import { Avatar } from '@/components/identity/avatar'
import { RelativeTime } from '@/components/ui/relative-time'
import { cn } from '@/lib/cn'
import { chatTitle } from '@/lib/format'
import { displayName } from '@/lib/persona'

import type { ConversationSummary, ExpertSummary } from '@/lib/api/types'

/** The recent-chats list on Home. 44px rows come from `--row-h` on touch. */
export function RecentChats({
  conversations,
  experts,
  className,
}: {
  conversations: ConversationSummary[]
  experts: ExpertSummary[]
  className?: string
}) {
  const byName = new Map(experts.map((expert) => [expert.name, expert]))

  return (
    <ul className={cn('rounded-card border border-border-soft bg-panel p-1', className)}>
      {conversations.map((conversation) => {
        // The conversation carries the joined expert columns, so a missing
        // entry in the map (an expert outside this page's list) still renders.
        const expert =
          byName.get(conversation.expert_slug) ??
          ({
            name: conversation.expert_slug,
            persona_name: conversation.expert_persona_name,
            topic: conversation.expert_topic,
            avatar: null,
            // The summary carries the picture's version for exactly this: a
            // chat whose expert is not on this page still draws the right
            // tile instead of falling back to two letters.
            picture: conversation.expert_picture_version
              ? { version: conversation.expert_picture_version }
              : null,
          } as Pick<ExpertSummary, 'name' | 'persona_name' | 'topic' | 'avatar' | 'picture'>)

        return (
          <li key={conversation.id}>
            <Link
              href={`/chats/${conversation.id}`}
              prefetch
              className="flex h-(--row-h) items-center gap-2.5 rounded-row px-2 transition-colors duration-(--dur-1) hover:bg-raised"
            >
              <Avatar expert={expert} size={20} />
              <span className="min-w-0 flex-1 truncate text-sm text-fg-2">
                {chatTitle(conversation.title)}
              </span>
              <span className="hidden shrink-0 truncate text-xs text-fg-3 sm:block sm:max-w-40">
                {displayName(expert)}
              </span>
              <RelativeTime
                iso={conversation.last_message_at}
                className="shrink-0 text-xs text-fg-3"
              />
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
