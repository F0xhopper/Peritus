import { forward, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

export async function POST(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const body = await jsonBody<{ url?: string; title?: string; author?: string }>(request)
  if (isResponse(body)) return body
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/sources/url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
