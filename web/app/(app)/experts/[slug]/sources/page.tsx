import { redirect } from 'next/navigation'

/**
 * Sources became the List view of the Knowledge page (docs/plans/expert-brain.md).
 * Old links — a citation's `?source=`, the Overview's `?concept=` — keep working:
 * every parameter is carried over, and the view is the one the link meant.
 */
export default async function SourcesRedirect({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const [{ slug }, query] = await Promise.all([params, searchParams])
  redirect(knowledgeUrl(slug, query, 'list'))
}

function knowledgeUrl(
  slug: string,
  query: Record<string, string | string[] | undefined>,
  view: 'map' | 'list'
): string {
  const next = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (typeof value === 'string') next.set(key, value)
  }
  next.set('view', view)
  return `/experts/${encodeURIComponent(slug)}/knowledge?${next}`
}
