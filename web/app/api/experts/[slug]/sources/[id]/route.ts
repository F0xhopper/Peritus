import { NextResponse } from 'next/server'

import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string; id: string }>
}

export async function DELETE(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug, id } = await params
  if (!/^\d+$/.test(id)) {
    return NextResponse.json({ detail: 'Source id must be a number.' }, { status: 400 })
  }
  return forward(`/experts/${encodeURIComponent(slug)}/sources/${id}`, { method: 'DELETE' })
}
