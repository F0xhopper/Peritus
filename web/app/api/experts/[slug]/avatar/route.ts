import { forward, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import type { ExpertAvatar } from '@/lib/api/types'

interface Ctx {
  params: Promise<{ slug: string }>
}

/** Pin the expert's picture avatar, or `{avatar: null}` to reset to derived. */
export async function PUT(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const body = await jsonBody<{ avatar: ExpertAvatar | null }>(request)
  if (isResponse(body)) return body
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/avatar`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ avatar: body.avatar ?? null }),
  })
}
