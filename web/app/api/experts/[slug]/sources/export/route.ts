import { forwardDownload, pickParams, query } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/**
 * Stream the ledger export. `Content-Type` and `Content-Disposition` are passed
 * through unchanged so the browser saves it under the filename the API chose,
 * which encodes the slug and the decision filter.
 *
 * A 507 (corpus over the export guard) comes through as a JSON body; the page
 * renders the message rather than saving a truncated file.
 */
export const dynamic = 'force-dynamic'

export async function GET(request: Request, { params }: Ctx) {
  const { slug } = await params
  const q = query(pickParams(request.url, ['format', 'decision']))
  return forwardDownload(`/experts/${encodeURIComponent(slug)}/corpus-report/export${q}`)
}
