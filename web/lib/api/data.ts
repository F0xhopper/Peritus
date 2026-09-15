import 'server-only'

import { cookies } from 'next/headers'
import { notFound, redirect } from 'next/navigation'
import { cache } from 'react'

import { ApiError, NotAuthenticatedError, isNextControlFlow } from '@/lib/api/errors'
import { proxyJson } from '@/lib/api/proxy'
import { ACCESS_COOKIE, REFRESH_COOKIE } from '@/lib/auth/cookies'
import type {
  BuildStatus,
  BuildUsage,
  ConversationDetail,
  ConversationSummary,
  CorpusReport,
  CreditState,
  ExpertWithCatalog,
  ExpertSummary,
  GraphResponse,
  LedgerEntry,
  Me,
  ScreeningFlow,
  SharedExpert,
  ShareState,
  SourceDecision,
  SourceSort,
} from '@/lib/api/types'

/**
 * Server-component fetchers. Each one turns the two failures a page cannot
 * render into the framework's own control flow: a dead session becomes a
 * redirect to `/login`, and a 404 becomes `notFound()`.
 *
 * Everything else is rethrown for the segment's `error.tsx`.
 */

/**
 * Run a fetch, translating auth and missing-resource failures.
 *
 * The `isNextControlFlow` rethrow is not optional: `redirect()` and
 * `notFound()` both work by throwing, and a `catch` that swallowed them would
 * turn a deliberate 404 into a rendered error page.
 */
async function safely<T>(
  fetcher: () => Promise<T>,
  opts: { next?: string; notFoundOn404?: boolean } = {},
): Promise<T> {
  try {
    return await fetcher()
  } catch (error) {
    if (isNextControlFlow(error)) throw error
    if (error instanceof NotAuthenticatedError) {
      redirect(`/login?next=${encodeURIComponent(opts.next ?? '/experts')}`)
    }
    if (error instanceof ApiError) {
      if (error.status === 401) {
        redirect(`/login?next=${encodeURIComponent(opts.next ?? '/experts')}`)
      }
      if (error.status === 404 && opts.notFoundOn404 !== false) notFound()
    }
    throw error
  }
}

/**
 * A fetch whose absence is not an error. Used for the endpoints that 404 by
 * design until something exists — build status before the first job, usage
 * before any is metered — so a page can render the "not yet" state instead of
 * a 404 page.
 */
async function optional<T>(fetcher: () => Promise<T>): Promise<T | null> {
  try {
    return await fetcher()
  } catch (error) {
    if (isNextControlFlow(error)) throw error
    if (error instanceof ApiError && error.status === 404) return null
    if (error instanceof NotAuthenticatedError) redirect('/login')
    throw error
  }
}

// ── identity and billing ────────────────────────────────────────────────────

export function getMe(next?: string) {
  return safely(() => proxyJson<Me>('/auth/me'), { next })
}

export function getBilling(next?: string) {
  return safely(() => proxyJson<CreditState>('/billing/me'), { next })
}

export function getLedger(limit = 50, next?: string) {
  return safely(() => proxyJson<LedgerEntry[]>(`/billing/ledger?limit=${limit}`), { next })
}

// ── experts ─────────────────────────────────────────────────────────────────

export function getExperts(next?: string) {
  return safely(() => proxyJson<ExpertSummary[]>('/experts'), { next })
}

/**
 * Memoised per request, so a page's `generateMetadata` and the page itself
 * share one API call — which is what lets every expert page title itself with
 * the persona name rather than the slug.
 */
export const getExpert = cache((slug: string) =>
  safely(() => proxyJson<ExpertWithCatalog>(`/experts/${encodeURIComponent(slug)}`), {
    next: `/experts/${slug}`,
  }),
)

/**
 * The expert, or null when the caller can no longer read it. For a page that
 * reaches an expert through something the caller owns — a chat started through
 * a share link that has since been turned off — and must still render.
 */
export function getExpertIfReadable(slug: string) {
  return optional(() => proxyJson<ExpertWithCatalog>(`/experts/${encodeURIComponent(slug)}`))
}

/** Null until the expert has ever had a build job. */
export function getBuildStatus(slug: string) {
  return optional(() =>
    proxyJson<BuildStatus>(`/experts/${encodeURIComponent(slug)}/build/status`),
  )
}

/** Null until the latest job has metered some spend. */
export function getBuildUsage(slug: string) {
  return optional(() => proxyJson<BuildUsage>(`/experts/${encodeURIComponent(slug)}/build/usage`))
}

// ── sharing ─────────────────────────────────────────────────────────────────

/**
 * The owner's share link, or null for anyone who is not the owner (the API
 * 404s them, deliberately without saying whether a link exists).
 */
export function getShareState(slug: string) {
  return optional(() => proxyJson<ShareState>(`/experts/${encodeURIComponent(slug)}/share`))
}

/**
 * The card behind a share link, with no session, or null when the link is
 * unknown, reset or turned off. Memoised per request: the page's metadata (the
 * link preview) and the page itself both read it.
 */
export const getSharedExpert = cache(async (token: string): Promise<SharedExpert | null> => {
  try {
    return await proxyJson<SharedExpert>(`/share/${encodeURIComponent(token)}`, {
      anonymous: true,
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
})

/**
 * Whether this request carries a session, without spending an API call or
 * redirecting. For public pages that only change their call to action — the
 * API still decides what a session can actually do.
 */
export async function hasSession(): Promise<boolean> {
  const jar = await cookies()
  return Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value)
}

// ── the ledger ──────────────────────────────────────────────────────────────

export interface CorpusQuery {
  decision?: SourceDecision
  sort?: SourceSort
  limit?: number
  offset?: number
}

export function getCorpusReport(slug: string, query: CorpusQuery = {}) {
  const params = new URLSearchParams({
    decision: query.decision ?? 'all',
    sort: query.sort ?? 'decision',
    limit: String(query.limit ?? 100),
    offset: String(query.offset ?? 0),
  })
  return safely(
    () => proxyJson<CorpusReport>(`/experts/${encodeURIComponent(slug)}/corpus-report?${params}`),
    { next: `/experts/${slug}/sources` },
  )
}

/**
 * The screening-flow report, for its `selection` block.
 *
 * Null on any API failure, not only a 404: the Sources page *is* the ledger,
 * and this report only annotates it, so a slow or failing funnel query must
 * not take the ledger down with it. A dead session still redirects.
 */
export async function getScreeningFlow(slug: string): Promise<ScreeningFlow | null> {
  try {
    return await optional(() =>
      proxyJson<ScreeningFlow>(`/experts/${encodeURIComponent(slug)}/screening-flow`),
    )
  } catch (error) {
    if (isNextControlFlow(error)) throw error
    if (error instanceof ApiError) return null
    throw error
  }
}

// ── graph ───────────────────────────────────────────────────────────────────

export function getGraph(slug: string, limit = 400) {
  return safely(
    () => proxyJson<GraphResponse>(`/experts/${encodeURIComponent(slug)}/graph?limit=${limit}`),
    { next: `/experts/${slug}/graph` },
  )
}

// ── conversations ───────────────────────────────────────────────────────────

export function getConversations(limit = 20, next?: string) {
  return safely(() => proxyJson<ConversationSummary[]>(`/conversations?limit=${limit}`), { next })
}

export function getExpertConversations(slug: string) {
  return safely(
    () =>
      proxyJson<ConversationSummary[]>(`/experts/${encodeURIComponent(slug)}/conversations`),
    { next: `/experts/${slug}` },
  )
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Memoised per request (metadata and page both read it). An id that is not a
 * UUID is a 404 here: the API answers it with a 422, which reached the error
 * boundary as "Something went wrong — Unprocessable Content" and a Try again
 * that could never succeed.
 */
export const getConversation = cache((id: string) => {
  if (!UUID.test(id)) notFound()
  return safely(
    () => proxyJson<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`),
    { next: `/chats/${id}` },
  )
})
