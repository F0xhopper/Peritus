import { redirect } from 'next/navigation'

/**
 * The concept graph became the Map view of the Knowledge page
 * (docs/plans/expert-brain.md). `?limit=` has no meaning there — the Map draws
 * the concepts its sources share — so it is dropped rather than carried.
 */
export default async function GraphRedirect({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  redirect(`/experts/${encodeURIComponent(slug)}/knowledge?view=map`)
}
