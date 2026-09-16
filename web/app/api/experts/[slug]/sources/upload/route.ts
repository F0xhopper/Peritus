import { NextResponse } from 'next/server'

import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/** Matches `MAX_UPLOAD_BYTES` in `api/src/peritus/api/schemas/sources.py`. */
const MAX_BYTES = 20 * 1024 * 1024
const ACCEPTED_TYPES = new Set([
  'application/pdf',
  'text/plain',
  'text/markdown',
  'text/x-markdown',
])
const ACCEPTED_SUFFIXES = ['.pdf', '.txt', '.md', '.markdown', '.text']

/**
 * Forward a PDF or text upload as multipart.
 *
 * The size and type are checked here as well as upstream, because rejecting a
 * 40 MB file after it has crossed the wire twice is a worse experience than
 * rejecting it after one hop — and because `Content-Type` from a file picker is
 * unreliable enough that the extension has to be part of the test.
 *
 * The form is rebuilt rather than the raw body being streamed through: reading
 * `formData()` is what makes the size check possible at all, and re-encoding
 * gives `fetch` a boundary it owns.
 */
export const dynamic = 'force-dynamic'
export const maxDuration = 60

export async function POST(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params

  let incoming: FormData
  try {
    incoming = await request.formData()
  } catch {
    return NextResponse.json({ detail: 'Expected a file upload.' }, { status: 400 })
  }

  const file = incoming.get('file')
  if (!(file instanceof File)) {
    return NextResponse.json({ detail: 'No file was attached.' }, { status: 400 })
  }
  if (file.size === 0) {
    return NextResponse.json({ detail: 'That file is empty.' }, { status: 400 })
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json(
      { detail: `That file is larger than the ${MAX_BYTES / (1024 * 1024)} MB limit.` },
      { status: 413 }
    )
  }

  const lowered = file.name.toLowerCase()
  const looksAccepted =
    ACCEPTED_TYPES.has(file.type) ||
    file.type.startsWith('text/') ||
    ACCEPTED_SUFFIXES.some((s) => lowered.endsWith(s))
  if (!looksAccepted) {
    return NextResponse.json(
      {
        detail: 'Only PDF, .txt and .md files can be uploaded. For a web page, use the URL tab.',
      },
      { status: 415 }
    )
  }

  const outgoing = new FormData()
  outgoing.set('file', file, file.name)
  const title = incoming.get('title')
  if (typeof title === 'string' && title.trim()) outgoing.set('title', title.trim())
  const author = incoming.get('author')
  if (typeof author === 'string' && author.trim()) outgoing.set('author', author.trim())

  // No Content-Type header: `fetch` sets it with the boundary it generated for
  // this FormData, and naming it by hand would produce a body the API cannot
  // parse.
  return forward(`/experts/${encodeURIComponent(slug)}/sources/upload`, {
    method: 'POST',
    body: outgoing,
  })
}
