import { forwardStream, pickParams, query } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/**
 * Tail a build's durable event log from a cursor.
 *
 * `after` is the last `seq` the client saw, so a dropped connection resumes
 * without replaying (or losing) events. Sixty seconds per connection is fine —
 * builds run for minutes and the client reconnects with the cursor.
 */
export const dynamic = 'force-dynamic'
export const maxDuration = 60

export async function GET(request: Request, { params }: Ctx) {
  const { slug } = await params
  const q = query(pickParams(request.url, ['after']))
  return forwardStream(`/experts/${encodeURIComponent(slug)}/build/events${q}`, {
    headers: { Accept: 'text/event-stream' },
  })
}
