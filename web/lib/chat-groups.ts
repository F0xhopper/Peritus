import type { ConversationSummary } from '@/lib/api/types'

/**
 * Chats under day headings — Today, Yesterday, This week, Older.
 *
 * Grouping is what a reader expects of a chat list and it scans without typing,
 * which is why the sidebar's filter field only appears once a list is long.
 *
 * **`now` is a parameter, not `Date.now()`.** The heading a chat falls under
 * depends on the current time, so computing it during render would make the
 * server's HTML and the client's first render disagree whenever the two land
 * either side of midnight — and a hydration mismatch is not a warning here, it
 * makes React throw the server's markup away. The caller passes `null` until
 * the browser has taken over, which renders one ungrouped list: exactly what
 * the server can safely produce.
 */
export interface ChatGroup {
  /** Null for the single pre-hydration group, which renders no heading. */
  label: string | null
  chats: ConversationSummary[]
}

const DAY_MS = 86_400_000

export function groupChats(chats: ConversationSummary[], now: Date | null): ChatGroup[] {
  if (!now) return chats.length > 0 ? [{ label: null, chats }] : []

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const groups = new Map<string, ConversationSummary[]>()
  // Insertion order is the display order, and the list arrives newest first.
  for (const label of ['Today', 'Yesterday', 'This week', 'Older']) groups.set(label, [])

  for (const chat of chats) {
    const at = Date.parse(chat.last_message_at)
    // An unparseable timestamp is not "very old" — it is unknown, and Older is
    // the only heading that does not claim something about when it happened.
    const label = Number.isNaN(at)
      ? 'Older'
      : at >= startOfToday
        ? 'Today'
        : at >= startOfToday - DAY_MS
          ? 'Yesterday'
          : at >= startOfToday - 7 * DAY_MS
            ? 'This week'
            : 'Older'
    groups.get(label)!.push(chat)
  }

  return [...groups.entries()]
    .filter(([, list]) => list.length > 0)
    .map(([label, list]) => ({ label, chats: list }))
}
