import { describe, expect, it } from 'vitest'

import { groupChats } from '@/lib/chat-groups'
import type { ConversationSummary } from '@/lib/api/types'

/**
 * The sidebar's day headings. The date arithmetic is here rather than trusted
 * to a component, and the pre-hydration case is a test of its own because it is
 * the one that keeps a "Today" heading from becoming a hydration mismatch.
 */
const NOW = new Date('2026-09-16T10:00:00Z')

function chat(id: string, at: string): ConversationSummary {
  return {
    id,
    expert_slug: 'beekeeping',
    expert_topic: 'Beekeeping',
    expert_persona_name: null,
    title: id,
    message_count: 2,
    created_at: at,
    last_message_at: at,
  } as ConversationSummary
}

describe('grouping chats by day', () => {
  it('splits today, yesterday, this week and older, in that order', () => {
    const groups = groupChats(
      [
        chat('this-morning', '2026-09-16T08:00:00Z'),
        chat('yesterday', '2026-09-15T22:00:00Z'),
        chat('four-days', '2026-09-12T09:00:00Z'),
        chat('last-month', '2026-08-12T09:00:00Z'),
      ],
      NOW
    )
    expect(groups.map((group) => [group.label, group.chats.map((c) => c.id)])).toEqual([
      ['Today', ['this-morning']],
      ['Yesterday', ['yesterday']],
      ['This week', ['four-days']],
      ['Older', ['last-month']],
    ])
  })

  it('leaves out a heading with nothing under it', () => {
    const groups = groupChats([chat('a', '2026-09-16T08:00:00Z')], NOW)
    expect(groups.map((group) => group.label)).toEqual(['Today'])
  })

  it('renders one unlabelled group before the browser takes over', () => {
    // `null` is what the server and the first client render both pass, so the
    // two agree: a heading that depends on the clock cannot be in the HTML.
    const groups = groupChats([chat('a', '2026-09-16T08:00:00Z')], null)
    expect(groups).toEqual([{ label: null, chats: expect.any(Array) }])
    expect(groupChats([], null)).toEqual([])
  })

  it('files an unparseable timestamp under Older, never under Today', () => {
    const groups = groupChats([chat('broken', 'not a date')], NOW)
    expect(groups.map((group) => group.label)).toEqual(['Older'])
  })
})
