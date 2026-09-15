import { NextResponse } from 'next/server'

import { forwardStream, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ id: string }>
}

/**
 * Ask a question and stream the answer.
 *
 * A POST, which is why nothing in this app uses `EventSource`. A 409 means
 * another tab (or this one, before a refresh) is still streaming an answer into
 * this conversation; the client shows "still answering" and re-enables after
 * the claim window rather than retrying blindly.
 */
export const dynamic = 'force-dynamic'
export const maxDuration = 300

export async function POST(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const body = await jsonBody<{ question?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.question !== 'string' || !body.question.trim()) {
    return NextResponse.json({ detail: 'Ask a question.' }, { status: 400 })
  }

  const { id } = await params
  return forwardStream(`/conversations/${encodeURIComponent(id)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ question: body.question.trim() }),
  })
}
