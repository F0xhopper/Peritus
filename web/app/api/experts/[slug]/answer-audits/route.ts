import { forward, pickParams, query } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/**
 * The retrieval trails for answers already in a conversation.
 *
 * The chat stream emits one of these live per answer, and the chat page used to
 * show it only there — so "how this was answered" existed until the reader hit
 * reload and then never again, although the API had recorded it all along. The
 * upstream endpoint is scoped to the caller's own conversations.
 */
export async function GET(request: Request, { params }: Ctx) {
  const { slug } = await params
  const q = query(pickParams(request.url, ['conversation_id', 'limit', 'offset']))
  return forward(`/experts/${encodeURIComponent(slug)}/answer-audits${q}`)
}
