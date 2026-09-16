import { describe, expect, it } from 'vitest'

import { asEvent, auditsByMessageId } from '@/lib/chat-audits'
import type { ConversationMessage, StoredAnswerAudit } from '@/lib/api/types'

/**
 * Matching stored trails to the answers they belong to. The audit table keys on
 * the question, not on a message id, so the same question asked twice is the
 * case that decides whether this is right.
 */
function message(id: number, role: 'user' | 'assistant', content: string): ConversationMessage {
  return {
    id,
    role,
    content,
    citations: null,
    has_contradiction: false,
    interrupted: false,
    created_at: '2026-09-16T09:00:00Z',
  }
}

function audit(question: string, cited: number): StoredAnswerAudit {
  return {
    audit_id: `a${cited}`,
    conversation_id: 'c1',
    question,
    subqueries: ['a sub-query'],
    followup_queries: [],
    coverage_satisfied: true,
    second_pass: false,
    passages: {
      retrieved: 23,
      duplicate_hits: 1,
      unique: 22,
      in_context: 15,
      cited,
      not_in_context: 7,
      context_cap: 15,
    },
    sources: { in_context: 8, cited },
    contradiction_traversed: false,
    answer_chars: 900,
    created_at: '2026-09-16T09:00:01Z',
  }
}

describe('matching trails to answers', () => {
  it('attaches each trail to the answer that followed its question', () => {
    const messages = [
      message(1, 'user', 'What is varroa?'),
      message(2, 'assistant', 'A mite.'),
      message(3, 'user', 'How is it treated?'),
      message(4, 'assistant', 'Several ways.'),
    ]
    // Newest first, as the API returns them.
    const map = auditsByMessageId(messages, [
      audit('How is it treated?', 3),
      audit('What is varroa?', 2),
    ])
    expect(map.get(2)?.passages_cited).toBe(2)
    expect(map.get(4)?.passages_cited).toBe(3)
  })

  it('matches a repeated question in the order it was asked', () => {
    const messages = [
      message(1, 'user', 'Again?'),
      message(2, 'assistant', 'First answer.'),
      message(3, 'user', 'Again?'),
      message(4, 'assistant', 'Second answer.'),
    ]
    const map = auditsByMessageId(messages, [audit('Again?', 9), audit('Again?', 1)])
    expect(map.get(2)?.passages_cited).toBe(1)
    expect(map.get(4)?.passages_cited).toBe(9)
  })

  it('leaves an answer with no trail alone rather than guessing', () => {
    const messages = [message(1, 'user', 'Unrecorded?'), message(2, 'assistant', 'Answer.')]
    expect(auditsByMessageId(messages, []).size).toBe(0)
  })

  it('reads as the card expects, and says a thin search was thin', () => {
    const event = asEvent({ ...audit('q', 2), coverage_satisfied: false })
    expect(event.type).toBe('retrieval_audit')
    expect(event.persisted).toBe(true)
    expect(event.passages_considered).toBe(23)
    expect(event.passages_in_prompt).toBe(15)
    expect(event.coverage_verdict).toMatch(/thin/)
    expect(asEvent({ ...audit('q', 2), coverage_satisfied: null }).coverage_verdict).toBeNull()
  })
})
