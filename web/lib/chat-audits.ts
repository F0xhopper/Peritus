import type {
  ChatRetrievalAuditEvent,
  ConversationMessage,
  StoredAnswerAudit,
} from '@/lib/api/types'

/**
 * Stored retrieval trails, matched to the answers they belong to.
 *
 * The API records one trail per answer and the chat stream emits it live, but
 * the *stored* one was never read back — so "Show how this was answered" was a
 * session-only action that vanished on reload, on a page whose whole argument
 * is that the reasoning is on the record.
 *
 * A trail is keyed by its question, not by a message id (the audit table
 * predates any link to one), so the same question asked twice is matched in
 * order: audits arrive newest first, and reversing them lines them up with the
 * transcript.
 */
export function auditsByMessageId(
  messages: ConversationMessage[],
  audits: StoredAnswerAudit[]
): Map<number, ChatRetrievalAuditEvent> {
  const queued = new Map<string, StoredAnswerAudit[]>()
  for (const audit of [...audits].reverse()) {
    const key = audit.question.trim()
    const list = queued.get(key)
    if (list) list.push(audit)
    else queued.set(key, [audit])
  }

  const out = new Map<number, ChatRetrievalAuditEvent>()
  for (const [index, message] of messages.entries()) {
    if (message.role !== 'assistant') continue
    const question = messages[index - 1]
    if (question?.role !== 'user') continue
    const list = queued.get(question.content.trim())
    const audit = list?.shift()
    if (audit) out.set(message.id, asEvent(audit))
  }
  return out
}

/** A stored trail in the shape the answer card renders. */
export function asEvent(audit: StoredAnswerAudit): ChatRetrievalAuditEvent {
  return {
    type: 'retrieval_audit',
    audit_id: audit.audit_id,
    // It is in the database — that is what makes it readable at all here.
    persisted: true,
    passages_considered: audit.passages.retrieved,
    passages_in_prompt: audit.passages.in_context,
    passages_cited: audit.passages.cited,
    subqueries: audit.subqueries,
    follow_ups: audit.followup_queries,
    coverage_verdict:
      audit.coverage_satisfied === null
        ? null
        : audit.coverage_satisfied
          ? 'adequate'
          : 'thin — the search did not meet its targets',
  }
}
