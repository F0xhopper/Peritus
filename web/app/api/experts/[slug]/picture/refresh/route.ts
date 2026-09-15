import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/**
 * Search Wikimedia again for a picture of this expert's subject.
 *
 * Synchronous upstream — five or six HTTP requests, no model call — so this
 * returns the updated expert rather than a job to poll. The API throttles it
 * per user, and a search that finds nothing acceptable comes back as a 422
 * whose `detail` is the sentence to show.
 */
export async function POST(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/picture/refresh`, { method: 'POST' })
}
