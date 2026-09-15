import { forward } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ token: string }>
}

/**
 * The picture behind a live share link, with no session.
 *
 * Anonymous on purpose: this is what the share page shows a signed-out visitor
 * and what a chat app fetches to unfurl the link. It is revalidated on every
 * use rather than cached immutably, so a link that has been turned off stops
 * serving its image too. `If-None-Match` is passed through so that
 * revalidation is a 304.
 */
export async function GET(request: Request, { params }: Ctx) {
  const { token } = await params
  const ifNoneMatch = request.headers.get('if-none-match')
  return forward(`/share/${encodeURIComponent(token)}/picture`, {
    anonymous: true,
    headers: ifNoneMatch ? { 'If-None-Match': ifNoneMatch } : undefined,
  })
}
