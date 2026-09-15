import { forward, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ id: string }>
}

export async function GET(_request: Request, { params }: Ctx) {
  const { id } = await params
  return forward(`/conversations/${encodeURIComponent(id)}`)
}

export async function PATCH(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const body = await jsonBody<{ title?: string }>(request)
  if (isResponse(body)) return body
  const { id } = await params
  return forward(`/conversations/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: body.title }),
  })
}

export async function DELETE(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { id } = await params
  return forward(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
