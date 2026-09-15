import type { ExpertSummary } from '@/lib/api/types'

/**
 * Whether the caller may change this expert: rebuild, re-skin, add or remove
 * sources, share it, delete it.
 *
 * A rendering decision only. Every mutating endpoint re-checks ownership, so a
 * control this hides would 404 anyway — hiding it is what keeps a viewer from
 * meeting a button that cannot work. An older server that sends no `access`
 * only ever returned the caller's own experts, hence the default.
 */
export function canManage(expert: Pick<ExpertSummary, 'access'>): boolean {
  return expert.access !== 'viewer'
}

/** The share page for a token. Relative, so it works on any origin. */
export function sharePath(token: string): string {
  return `/share/${encodeURIComponent(token)}`
}

/** The picture behind a share link, for the anonymous page and its preview. */
export function sharedPictureUrl(token: string, version: string): string {
  return `/api/share/${encodeURIComponent(token)}/picture?v=${encodeURIComponent(version)}`
}
