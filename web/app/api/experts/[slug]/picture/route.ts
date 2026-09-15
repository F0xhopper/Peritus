import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/**
 * The found picture's bytes, proxied same-origin.
 *
 * Going through the BFF rather than hotlinking Wikimedia is the whole point:
 * there is no third-party origin in the browser, no `images.remotePatterns`,
 * and a link that cannot rot when a file is renamed on Commons.
 *
 * `If-None-Match` is passed upstream so the API's 304 reaches the browser and
 * the image is revalidated rather than re-sent. The `?v=` the client appends is
 * ignored by the API — it exists to move the URL when the picture changes, which
 * is what makes the `immutable` cache header safe.
 */
export async function GET(request: Request, { params }: Ctx) {
  const { slug } = await params
  const ifNoneMatch = request.headers.get('if-none-match')
  return forward(`/experts/${encodeURIComponent(slug)}/picture`, {
    headers: ifNoneMatch ? { 'If-None-Match': ifNoneMatch } : undefined,
  })
}

/** Remove the picture; the expert falls back to its recipe or its monogram. */
export async function DELETE(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/picture`, { method: 'DELETE' })
}
