import { forwardStream, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import type { BuildRequestBody } from '@/lib/api/types'

/**
 * Start (or attach to) a build, and stream its event log.
 *
 * The response is the stream, so this cannot be buffered: the `created` event
 * carries the server's slug, and the client needs it to navigate before the
 * build has done anything. Never slugify on the client — the server steps over
 * other people's slugs with a numeric suffix and only it knows which it chose.
 *
 * A 402 arrives here as a normal non-2xx with the entitlement payload in
 * `detail`, which `forwardStream` passes through intact.
 */
export const dynamic = 'force-dynamic'
export const maxDuration = 60

export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const body = await jsonBody<BuildRequestBody>(request)
  if (isResponse(body)) return body

  return forwardStream('/experts/build', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({
      topic: body.topic,
      // Omitted means "the deepest tier this plan and balance allow" — the
      // Auto option. Sending null explicitly is the same thing to the API.
      ...(body.tier ? { tier: body.tier } : {}),
      ...(body.sources?.length ? { sources: body.sources } : {}),
    }),
  })
}
